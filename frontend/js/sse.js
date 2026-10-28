/* SSE 增量解析器（接口契约：POST SSE）
 * 按 SSE 规则累积字节，正确解析跨块 UTF-8：
 * 不假设一次网络读取就是一个事件，支持中文等多字节字符在任意位置被切开。
 * 用法：
 *   const p = new SseParser((event, data) => { ... });
 *   p.feed(uint8ArrayChunk);   // 任意大小的网络块
 *   p.end();
 */
class SseParser {
  constructor(onEvent) {
    this.onEvent = onEvent;
    this.decoder = new TextDecoder("utf-8", { fatal: false });
    this.buffer = "";
  }

  feed(chunk) {
    // stream:true 保证多字节字符跨块时不被截断成乱码
    this.buffer += this.decoder.decode(chunk, { stream: true });
    this._drain(false);
  }

  end() {
    this.buffer += this.decoder.decode();
    this._drain(true);
  }

  _drain(flush) {
    // 事件以空行分隔；兼容 \n 与 \r\n
    let idx;
    while ((idx = this._findBoundary(this.buffer)) !== -1) {
      this._dispatch(idx.block);
      this.buffer = this.buffer.slice(idx.end);
    }
    if (flush && this.buffer.trim() !== "") {
      this._dispatch(this.buffer);
      this.buffer = "";
    }
  }

  _findBoundary(buf) {
    const nn = buf.indexOf("\n\n");
    const rn = buf.indexOf("\r\n\r\n");
    let end = -1;
    if (nn !== -1 && (rn === -1 || nn < rn)) end = nn + 2;
    else if (rn !== -1) end = rn + 4;
    if (end === -1) return -1;
    // 找到块起点：回溯到上一个边界之后（简化：块内无空行，直接取 [0,end)）
    return { end, block: buf.slice(0, end) };
  }

  _dispatch(block) {
    let event = "message";
    const dataLines = [];
    for (const line of block.split(/\r?\n/)) {
      if (line === "") continue;
      if (line.startsWith(":")) continue; // SSE 注释：idle 心跳，忽略
      if (line.startsWith("event:")) {
        event = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).replace(/^ /, ""));
      }
    }
    if (dataLines.length === 0) return;
    let data = null;
    try {
      data = JSON.parse(dataLines.join("\n"));
    } catch (e) {
      console.warn("[sse] data 不是合法 JSON，已忽略", e);
      return;
    }
    this.onEvent(event, data);
  }
}

/* 工具：把字符串切成任意小块（可切在多字节字符中间），
 * 用于 fixtures/README 要求的解析器健壮性验证。 */
function chunkString(text, mode = "random") {
  const bytes = new TextEncoder().encode(text);
  const chunks = [];
  let i = 0;
  while (i < bytes.length) {
    let n;
    if (mode === "byte") n = 1;                    // 最严苛：逐字节
    else if (mode === "fixed") n = 7;              // 固定小块，必切中文
    else n = 1 + Math.floor(Math.random() * 23);   // 随机 1-23 字节
    chunks.push(bytes.slice(i, i + n));
    i += n;
  }
  return chunks;
}
