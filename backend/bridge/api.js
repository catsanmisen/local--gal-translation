/* Backend-owned transport. Launch credentials stay in memory and request headers. */
class ClientApi {
  constructor() { this.token = null; this.clientId = crypto.randomUUID(); }
  async connect() {
    const response = await fetch('/bootstrap', {cache:'no-store'});
    if (!response.ok) throw new Error('无法连接本地客户端');
    this.token = (await response.json()).token;
  }
  async request(path, method='GET', body, keepalive=false) {
    const response = await fetch('/api/v1' + path, {
      method, cache:'no-store', keepalive,
      headers:{'Authorization':'Bearer ' + this.token, 'Content-Type':'application/json', 'X-Client-Id':this.clientId},
      body:body === undefined ? undefined : JSON.stringify(body)
    });
    const data = await response.json();
    if (!response.ok) throw Object.assign(new Error(data.error?.message || '后台请求失败'), data.error || {});
    return data;
  }
  async stream(body, event, rejected) {
    let terminal = false;
    try {
      const response = await fetch('/api/v1/translate', {
        method:'POST', cache:'no-store',
        headers:{'Authorization':'Bearer ' + this.token, 'Content-Type':'application/json'},
        body:JSON.stringify(body)
      });
      if (!response.ok) {
        const data = await response.json();
        rejected(data.error);
        return;
      }
      const parser = new SseParser((name,data) => {
        if (['final','cancelled','error'].includes(name)) terminal = true;
        event(name,data);
      });
      const reader = response.body.getReader();
      try {
        while (true) {
          const chunk = await reader.read();
          if (chunk.done) break;
          parser.feed(chunk.value);
        }
        parser.end();
      } finally { reader.releaseLock(); }
      if (!terminal) throw new Error('连接中断');
    } catch (error) {
      if (!terminal) {
        // Inspect a known ID; never blindly resubmit an accepted inference.
        try {
          const state = await this.request('/requests/' + encodeURIComponent(body.request_id));
          if (['final','cancelled','error'].includes(state.status)) {
            event(state.status,state.result);
            return;
          }
          await this.request('/requests/' + encodeURIComponent(body.request_id),'DELETE');
        } catch (_) {}
        event('interrupted',{...body,code:'STREAM_INTERRUPTED',message:'连接中断，请检查后台状态后手动重试。'});
      }
    }
  }
}
