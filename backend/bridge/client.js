/* Backend connection controller over the unchanged frontend DOM. */
(function () {
  'use strict';
  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];
  const api = new ClientApi();
  const backlogAccess=new BacklogAccess();
  const notices = new ConnectionPresentation.Notices();
  const modelDraft=new ConnectionPresentation.ModelDraft();
  const state = {session:null,status:null,active:null,lastInput:null,sequence:0,profiles:[],entries:[],history:[],page:1,source:'manual',busy:false,connected:false};
  const labels = {stopped:'未启动',starting:'启动中',loading:'加载中',ready:'就绪',translating:'翻译中',paused:'已暂停（显存不足）',recovering:'恢复中',error:'错误',stopping:'停止中'};
  let polling = false, saving = Promise.resolve(), lastHistoryRequest = null;
  $('#mock-bar').hidden = true;
  $('#mode-badge').textContent = '本地模型';
  $('#mode-badge').classList.add('real');
  $('#stream-empty .empty-hint').textContent = '启动模型后输入日文，或打开剪贴板监听。原文始终保留。';
  $('#input-ja').maxLength = 2001;
  $('#input-speaker').placeholder = '留空即可';
  $('#btn-reset-session').title = '读档或切换场景后清空翻译上下文';
  $('#btn-to-subtitle').textContent = '打开字幕预览';
  $('#page-subtitle .page-head p').textContent = '浏览器字幕预览随当前台词更新。Windows 置顶、全局快捷键和整窗穿透尚未接入。';
  $('#page-glossary .page-head p').textContent = '按游戏保存人物名和术语。更新后清空翻译上下文，原文历史继续保留。';
  $('#page-history .page-head p').textContent = '仅在你主动打开时读取本游戏的历史。新台词不会打开或刷新本页，历史不会重播到实时字幕。';
  $('#btn-glossary-save').textContent = '保存术语表';
  $('#btn-history-clear').textContent = '重置翻译上下文';
  $('#page-settings .section:last-child .control-value').textContent = '本机已连接';
  const connectionRows = $$('#page-settings .section:last-child .control-row');
  connectionRows[0].querySelector('.desc').textContent = '只连接本机模型，连接凭据由启动器提供。';
  connectionRows[1].querySelector('.desc').textContent = '最后一个主窗口离开后停止本客户端模型；意外断开最长等待 90 秒。';
  connectionRows[1].querySelector('.tag').textContent = '已接入';
  const nativeSwitch = $('#sub-clickthrough');
  nativeSwitch.disabled = true;
  nativeSwitch.setAttribute('aria-label','鼠标穿透（尚未接入）');
  nativeSwitch.closest('.control-row').querySelector('.desc').textContent = '需要 Windows 原生窗口支持';
  $('#sub-font').setAttribute('aria-label','字幕字号');
  $('#sub-opacity').setAttribute('aria-label','字幕底衬不透明度');
  const hotkeyRow=$('#sub-font').closest('.control-list').querySelectorAll('.control-row')[4];
  hotkeyRow.querySelector('.control-value').textContent = 'Ctrl + Shift + H';
  hotkeyRow.querySelector('.desc').textContent = '字幕预览窗口内生效；全局热键尚未接入';
  $('#btn-open-subtitle').closest('.control-row').querySelector('.desc').textContent = '打开与主窗共享状态和样式的浏览器字幕预览';
  $('#settings-input-sources-title').nextElementSibling.querySelector('.control-row:nth-child(2) .desc').textContent = 'Windows 实际监听，默认关闭';
  $('#stream-status').setAttribute('role','status');
  const clipboardHint=$('#field-clipboard .switch-hint');
  if(clipboardHint)clipboardHint.textContent='默认关闭。开启后只读取新复制的完整台词，不回写剪贴板；占用时自动重试。';
  const clipboardNotice=document.createElement('div');
  clipboardNotice.className='input-notice';clipboardNotice.setAttribute('role','status');clipboardNotice.hidden=true;
  $('#field-clipboard').append(clipboardNotice);

  function error(e) {
    $('#banner-error').hidden = false;
    $('#banner-error-title').textContent = '操作未完成';
    $('#banner-error-desc').textContent = e.message || '后台连接失败，请重新打开客户端。';
  }
  const run = fn => async (...args) => { try { await fn(...args); } catch(e) { error(e); } };
  function tag(label,tone='') { $('#stream-tag').className = 'tag ' + tone; $('#stream-tag').textContent = label; }
  function theme(value) {
    const actual = value === 'system' ? (matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light') : value;
    document.documentElement.dataset.theme = actual;
    $('#theme-toggle').innerHTML = actual === 'dark' ? '<i class="ph ph-moon"></i>' : '<i class="ph ph-sun"></i>';
  }
  $('#theme-toggle').addEventListener('click',run(async()=>{
    const value = document.documentElement.dataset.theme === 'dark'?'light':'dark';
    theme(value);
    await api.request('/settings','PUT',{theme:value});
  }));
  $$('.rail-item').forEach(b=>b.addEventListener('click',run(async()=>{
    $$('.rail-item').forEach(n=>{n.classList.toggle('active',n===b);n.setAttribute('aria-current',n===b?'page':'false');});
    $$('.page').forEach(n=>n.classList.toggle('active',n.id==='page-'+b.dataset.page));
    if(b.dataset.page==='history') {backlogAccess.open(state.session?.profile_id);state.page=1;await history();}
    else backlogAccess.close();
  })));
  $('#btn-backlog').addEventListener('click',()=>$('.rail-item[data-page="history"]').click());
  $('#btn-backlog-close').addEventListener('click',()=>$('.rail-item[data-page="translate"]').click());
  $('#btn-history-refresh').addEventListener('click',run(history));
  function status(s) {
    state.status = s;
    modelDraft.read(s.model_preferences);renderModelSettings(s);
    const gameBound=s.game_session?.bound===true;
    $('#page-subtitle .page-head p').textContent=s.capabilities?.native_subtitle?'原生游戏字幕已连接，位置、穿透及全局快捷键由桌面托盘管理。本页保留浏览器预览。':'浏览器字幕预览随当前台词更新。启动桌面客户端后可使用原生置顶字幕。';
    nativeSwitch.setAttribute('aria-label',s.capabilities?.native_subtitle?'原生字幕默认鼠标穿透，由桌面托盘管理':'鼠标穿透（需启动桌面客户端）');
    nativeSwitch.closest('.control-row').querySelector('.desc').textContent=s.capabilities?.native_subtitle?'已在原生字幕启用；进入托盘位置编辑时暂时取消穿透':'浏览器预览不提供整窗穿透';
    $$('#source-kind button').forEach(b=>b.disabled=gameBound);
    $('#btn-retry').disabled=gameBound;
    if(s.session) {
      if(!state.session || s.session.session_id !== state.session.session_id || s.session.epoch !== state.session.epoch) {
        if(state.session?.profile_id!==s.session.profile_id){backlogAccess.close();if($('#page-history').classList.contains('active'))$('.rail-item[data-page="translate"]').click();}
        state.active=null;
        state.session=s.session;
        state.sequence=s.session.sequence;
      }
      state.sequence=Math.max(state.sequence,s.session.sequence);
    } else state.session=null;
    $('#state-text').textContent = labels[s.state] || s.state;
    $('#state-pill').dataset.tone = s.state==='ready'?'ok':s.state==='error'?'err':['starting','loading','translating','stopping','paused'].includes(s.state)?'busy':'';
    if(s.state==='loading') $('#state-text').textContent += ' · '+Math.floor(s.loading_elapsed_ms/1000)+'s';
    $('#vram-value').textContent = s.model?.execution_mode==='cpu'?'模型使用 CPU':s.gpu ? s.gpu.free_mib+' / '+s.gpu.reserve_mib+' MiB' : '采样不可用';
    $('#metric-vram').classList.toggle('warn',s.state==='paused');
    $('#model-value').textContent = 'GalTransl 4B · Q6_K · '+(s.model?.execution_mode==='cpu'?'CPU':s.model?.execution_mode==='hybrid'?'GPU + CPU':s.model?.execution_mode==='gpu'?'GPU':'未加载');
    $('#session-value').textContent = state.profiles.find(p=>p.id===state.session?.profile_id)?.name || '无会话';
    $('#glossary-version').textContent = state.session?'术语 v'+state.session.glossary_version:'术语未连接';
    $('#btn-start').disabled = state.busy || ['starting','loading','ready','translating','stopping'].includes(s.state);
    $('#btn-stop').disabled = state.busy || s.state==='stopped' || s.state==='stopping';
    $('#btn-translate').disabled = gameBound || state.busy || !state.session || !['ready','translating'].includes(s.state) || !$('#input-ja').value.trim() || $('#input-ja').value.length>2000 || state.source!=='manual';
    $('#btn-reset-session').disabled = state.busy || !state.session;
    $('#btn-glossary-save').disabled = state.busy || !state.session;
    $('#btn-cancel').disabled = !s.active_request_id && !state.active;
    $('#banner-vram').hidden = s.state!=='paused';
    if(s.state==='paused') $('#banner-vram-desc').textContent = s.last_error?.message || '可用显存不足，请关闭其他占用显存的程序后重新启动。';
    $('#clipboard-switch').classList.toggle('on',s.clipboard?.enabled===true);
    $('#clipboard-switch').setAttribute('aria-checked',String(s.clipboard?.enabled===true));
    const clipError=s.clipboard?.last_error;
    const quiet=clipError && (clipError.severity==='notice' || clipError.code==='CLIPBOARD_BUSY');
    clipboardNotice.hidden=!quiet;clipboardNotice.textContent=quiet?clipError.message:'';
    if(notices.changed('clipboard',clipError) && !quiet) error(clipError);
    if(notices.changed('engine',s.last_error) && s.state!=='paused') error(s.last_error);
  }
  function renderModelSettings(s=state.status||{}) {
    const unavailable=s.capabilities?.model_device_choice!==true;
    $$('#model-mode button').forEach(b=>{const selected=b.dataset.modelMode===modelDraft.value.model_mode;b.classList.toggle('on',selected);b.setAttribute('aria-pressed',String(selected));b.disabled=!!s.model_reloading||unavailable;});
    $('#model-reserve').value=String(modelDraft.value.gpu_reserve_mib);
    $('#model-reserve').disabled=s.model_reloading||unavailable||modelDraft.value.model_mode==='cpu';
    $('#wallpaper-relief').checked=modelDraft.value.wallpaper_relief;
    $('#wallpaper-relief').disabled=!!s.model_reloading||unavailable||s.capabilities?.wallpaper_control!==true;
    $('#wallpaper-runtime').textContent=ConnectionPresentation.wallpaper(s.wallpaper);
    $('#btn-model-save').disabled=!!s.model_reloading||unavailable;
    $('#model-runtime').textContent=unavailable?'当前后台未提供设备设置，请启动最新候选。':ConnectionPresentation.model(s);
  }
  $$('#model-mode button').forEach(b=>b.addEventListener('click',()=>{modelDraft.edit(b.dataset.modelMode,$('#model-reserve').value);renderModelSettings();}));
  $('#model-reserve').addEventListener('change',()=>{modelDraft.edit(modelDraft.value.model_mode,$('#model-reserve').value);renderModelSettings();});
  $('#wallpaper-relief').addEventListener('change',()=>{modelDraft.edit(modelDraft.value.model_mode,$('#model-reserve').value,$('#wallpaper-relief').checked);renderModelSettings();});
  $('#btn-model-save').addEventListener('click',run(()=>serialized(async()=>{
    const target={...modelDraft.value};if(state.status?.capabilities?.wallpaper_control!==true)delete target.wallpaper_relief;
    const saved=await api.request('/settings','PATCH',target);modelDraft.saved(saved);
    state.status={...(state.status||{}),model_preferences:modelDraft.value,model_reloading:saved.model_reloading};renderModelSettings();
  })));
  function input() {
    const n=$('#input-ja').value.length;
    $('#char-count').textContent=n+' / 2000';
    $('#field-manual').classList.toggle('invalid',n>2000);
    $('#input-error').textContent=n>2000?'原文超过 2000 字符，请拆分后重试。':'';
    if(state.status) status(state.status);
  }
  $('#input-ja').addEventListener('input',input);
  async function source(kind,persist=true) {
    state.source=kind;
    $$('#source-kind button').forEach(b=>b.classList.toggle('on',b.dataset.kind===kind));
    $('#field-manual').hidden=kind!=='manual';
    $('#field-clipboard').hidden=kind!=='clipboard';
    if(kind==='manual' && state.status?.clipboard?.enabled) await api.request('/clipboard','PUT',{enabled:false});
    if(persist && state.session) await prefs();
    if(state.status) status(state.status);
  }
  $$('#source-kind button').forEach(b=>b.addEventListener('click',run(()=>source(b.dataset.kind))));
  $('#clipboard-switch').addEventListener('click',run(async()=>{
    await api.request('/clipboard','PUT',{enabled:!state.status?.clipboard?.enabled});
    await poll();
  }));
  async function serialized(fn) {
    if(state.busy) return;
    state.busy=true;
    try { await fn(); } finally {state.busy=false; await poll();}
  }
  $('#btn-start').addEventListener('click',run(()=>serialized(async()=>{
    await api.request('/engine/start','POST',{});
    if(!state.session) await session(state.profiles[0]?.id || 'default');
  })));
  $('#btn-stop').addEventListener('click',run(()=>serialized(()=>api.request('/engine/stop','POST',{}))));
  $('#btn-vram-recheck').addEventListener('click',run(poll));
  $('#banner-error-close').addEventListener('click',()=>$('#banner-error').hidden=true);
  $('#btn-cancel').addEventListener('click',run(async()=>{
    const id=state.active?.request_id || state.status?.active_request_id;
    if(id) await api.request('/requests/'+encodeURIComponent(id),'DELETE');
  }));
  async function reset() {
    if(!state.session) return;
    state.session=await api.request('/sessions/'+state.session.session_id+'/reset','POST',{reason:'scene_change'});
    state.sequence=0; state.active=null;
    tag('待输入');
    $('#stream-original').textContent='';
    $('#stream-translation').textContent='';
    $('#stream-meta').textContent='已清空翻译上下文，历史仍保留';
    await history();
  }
  $('#btn-reset-session').addEventListener('click',run(()=>serialized(reset)));
  $('#btn-history-clear').addEventListener('click',run(()=>serialized(reset)));
  function same(d,req) {
    return state.session?.session_id===d.session_id && state.session.epoch===d.epoch &&
      state.active===req && ['request_id','session_id','epoch','sequence'].every(k=>req[k]===d[k]);
  }
  async function translate(text,kind='manual',speaker=null) {
    if(!state.session || !text.trim()) return;
    const req={request_id:crypto.randomUUID(),session_id:state.session.session_id,epoch:state.session.epoch,
      sequence:++state.sequence,source_text:text,source_kind:kind,speaker,captured_at:new Date().toISOString(),complete:true,stream:true};
    state.active=req; state.lastInput={text,kind,speaker};
    $('#stream-empty').hidden=true; $('#stream-content').hidden=false; $('#stream-skeleton').hidden=true;
    $('#stream-original').textContent=text; $('#stream-translation').textContent='';
    $('#stream-actions').hidden=true; $('#banner-error').hidden=true;
    $('#stream-meta').textContent='正在翻译当前台词';
    tag('翻译中','streaming');
    let buffer='';
    await api.stream(req,(event,d)=>{
      if(!same(d,req)) return;
      if(event==='meta'&&d.replace_buffer){buffer='';$('#stream-translation').textContent='';$('#stream-meta').textContent='正在自动修复本条译文';}
      if(event==='delta') {buffer+=d.text; $('#stream-translation').textContent=buffer;}
      if(['final','cancelled','error','interrupted'].includes(event)) {
        state.active=null;
        if(event==='final') {
          $('#stream-translation').textContent=d.translation;
          tag('已完成','final');
          $('#stream-meta').textContent='耗时 '+d.elapsed_ms+' ms'+(d.warnings?.length?' · 需复核：'+d.warnings.map(w=>w.message).join(' '):'');
        } else {
          $('#stream-translation').textContent='';
          tag(event==='cancelled'?'已取消':event==='interrupted'?'已中断':'未完成','broken');
          $('#stream-meta').textContent=(d.message || '本条台词已取消')+' · 原文已保留';
        }
        $('#stream-actions').hidden=false;
      }
    },e=>{
      if(!same(req,req)) return;
      state.active=null; tag('未完成','broken'); $('#stream-actions').hidden=false;
      $('#stream-meta').textContent=e.message+' · 原文已保留'; error(e);
    });
    await poll();
  }
  $('#btn-translate').addEventListener('click',run(()=>translate($('#input-ja').value,'manual',$('#input-speaker').value.trim()||null)));
  $('#btn-retry').addEventListener('click',run(()=>{
    if(state.lastInput) return translate(state.lastInput.text,state.lastInput.kind,state.lastInput.speaker);
  }));
  function subtitle(s) {
    const view=ConnectionPresentation.subtitle(s);
    $('#sub-prev-ja').textContent=view.original || '等待原文';
    $('#sub-prev-zh').textContent=view.translation || view.empty;
    const badge=$('#sub-state-badge');
    if(badge){badge.hidden=s.state==='idle';badge.className='tag '+view.tone;badge.textContent=view.label;}
    if(state.status?.game_session?.bound&&!s.ja){$('#stream-original').textContent='';$('#stream-translation').textContent='';$('#stream-empty').hidden=false;$('#stream-content').hidden=true;$('#stream-actions').hidden=true;tag('待输入');return;}
    if(!state.active && (state.source==='clipboard'||state.status?.game_session?.bound) && s.ja) {
      $('#stream-empty').hidden=true; $('#stream-content').hidden=false;
      $('#stream-original').textContent=s.ja;
      $('#stream-translation').textContent=['final','streaming'].includes(s.state)?s.zh:'';
      tag(s.state==='final'?'已完成':s.state==='streaming'?'翻译中':'未完成',s.state==='final'?'final':s.state==='streaming'?'streaming':'broken');
      $('#stream-meta').textContent=s.state==='final'?(s.source_kind==='hook'?'HOOK 台词已完成':s.source_kind==='ocr'?'OCR 台词已完成':'剪贴板台词已完成'):'原文已保留';
    }
  }
  function preview() {
    const mode=$('#sub-mode button.on')?.dataset.mode || 'both';
    ConnectionPresentation.prefs($('#subtitle-preview'),$('#sub-prev-ja'),$('#sub-prev-zh'),
      {font:$('#sub-font').value,opacity:$('#sub-opacity').value,mode});
    $('#sub-font-value').textContent=$('#sub-font').value+'px';
    $('#sub-opacity-value').textContent=$('#sub-opacity').value+'%';
  }
  async function prefs(delta) {
    const profile=state.profiles.find(p=>p.id===state.session?.profile_id);
    if(!profile) return;
    const body={id:profile.id,prefs:delta || {source_kind:state.source}};
    saving=saving.catch(()=>{}).then(async()=>{const p=await api.request('/profiles','PATCH',body); state.profiles=state.profiles.map(n=>n.id===p.id?p:n);});
    await saving;
  }
  let prefsTimer;
  let pendingPrefs={},pendingProfileId;
  for(const id of ['#sub-font','#sub-opacity']) $(id).addEventListener('input',()=>{preview();const profileId=state.session?.profile_id;if(pendingProfileId!==profileId){pendingPrefs={};pendingProfileId=profileId;}pendingPrefs[id==='#sub-font'?'font':'opacity']=Number($(id).value);clearTimeout(prefsTimer);
    prefsTimer=setTimeout(()=>{const delta=pendingPrefs;pendingPrefs={};if(state.session?.profile_id===profileId)prefs(delta).catch(error);},250);});
  $$('#sub-mode button').forEach(b=>b.addEventListener('click',run(async()=>{
    $$('#sub-mode button').forEach(n=>n.classList.toggle('on',n===b)); preview(); await prefs({mode:b.dataset.mode});
  })));
  const openSubtitle=()=>window.open('/subtitle/','galtransl-subtitle','width=800,height=260');
  $('#btn-open-subtitle').addEventListener('click',openSubtitle);
  $('#btn-to-subtitle').addEventListener('click',openSubtitle);
  function glossary() {
    const tbody=$('#glossary-body'); tbody.replaceChildren();
    state.entries.forEach((entry,i)=>{
      const row=document.createElement('tr');
      for(const key of ['source','target','note']) {
        const cell=document.createElement('td'),inp=document.createElement('input');
        inp.type='text';inp.value=entry[key] || '';inp.setAttribute('aria-label',({source:'日文词',target:'中文译名',note:'备注'})[key]+' '+(i+1));
        inp.addEventListener('input',()=>entry[key]=inp.value);cell.append(inp);row.append(cell);
      }
      const cell=document.createElement('td'),remove=document.createElement('button');
      remove.className='icon-btn';remove.textContent='×';remove.setAttribute('aria-label','删除词条 '+(i+1));
      remove.addEventListener('click',()=>{state.entries.splice(i,1);glossary();});cell.append(remove);row.append(cell);tbody.append(row);
    });
  }
  $('#btn-glossary-add').addEventListener('click',()=>{state.entries.push({source:'',target:'',note:''});glossary();$('#glossary-body tr:last-child input')?.focus();});
  $('#btn-glossary-save').addEventListener('click',run(async()=>{
    if(!state.session) return;
    try {
      state.session=await api.request('/sessions/'+state.session.session_id+'/glossary','PUT',{entries:state.entries});
      state.sequence=0;state.active=null;
      $('#banner-glossary').hidden=true;
      state.profiles=await api.request('/profiles'); await poll();
    } catch(e) {
      $('#banner-glossary').hidden=false;$('#banner-glossary-desc').textContent=e.message;
      $$('#glossary-body tr').forEach((r,i)=>r.classList.toggle('row-error',i===e.row));
    }
  }));
  $('#banner-glossary-close').addEventListener('click',()=>$('#banner-glossary').hidden=true);
  function download(data,name) {
    const a=document.createElement('a'),url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json;charset=utf-8'}));
    a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  $('#btn-glossary-export').addEventListener('click',()=>download(state.entries,'glossary-utf8.json'));
  $('#btn-glossary-import').addEventListener('click',()=>{
    const inp=document.createElement('input');inp.type='file';inp.accept='.json';
    inp.addEventListener('change',run(async()=>{
      if(!inp.files[0]) return;
      if(inp.files[0].size>128*1024) throw new Error('术语文件过大');
      const entries=JSON.parse((await inp.files[0].text()).replace(/^\uFEFF/,''));
      if(!Array.isArray(entries) || entries.length>100 || entries.some(e=>!e || typeof e.source!=='string' || typeof e.target!=='string' || (e.note!==undefined && typeof e.note!=='string'))) throw new Error('术语格式不正确');
      state.entries=entries.map(e=>({source:e.source,target:e.target,note:e.note||''}));glossary();
    }));inp.click();
  });
  async function history() {
    if(!state.session) return;
    const profileId=state.session.profile_id,token=backlogAccess.requestToken(profileId);
    if(!token)return;
    const data=await api.request('/history?profile_id='+encodeURIComponent(state.session.profile_id)+'&limit=5&offset='+((state.page-1)*5));
    if(!backlogAccess.accepts(token,state.session?.profile_id))return;
    state.history=data.items;
    $$('.history-item').forEach(n=>n.remove());$('#history-empty').hidden=data.items.length>0;
    for(const h of data.items) {
      const item=document.createElement('div');item.className='history-item';
      const meta=document.createElement('div');meta.className='history-meta';
      meta.textContent=({clipboard:'剪贴板',ocr:'OCR',hook:'HOOK'}[h.source_kind]||'手动')+' · '+(h.terminal==='final'?'完成 '+h.elapsed_ms+' ms':h.terminal==='cancelled'?'已取消':'未完成')+
        (h.speaker?' · '+h.speaker:'')+(h.warnings.length?' · 需复核：'+h.warnings.map(w=>w.message).join(' '):'');
      const ja=document.createElement('div'),zh=document.createElement('div');ja.className='history-ja';zh.className='history-zh';
      ja.textContent=h.source_text;zh.textContent=h.translation || '未产生完整译文：'+h.reason;
      item.append(meta,ja,zh);$('#history-list').append(item);
    }
    $('#history-pager').hidden=!data.has_more&&state.page===1;
    $('#pager-prev').disabled=state.page===1;$('#pager-next').disabled=!data.has_more;$('#pager-info').textContent='第 '+state.page+' 页';
  }
  $('#pager-prev').addEventListener('click',run(async()=>{if(state.page>1) state.page--;await history();}));
  $('#pager-next').addEventListener('click',run(async()=>{state.page++;await history();}));
  function confirmHistory(name) {
    return new Promise(resolve=>{
      const dialog=document.createElement('dialog');dialog.className='history-confirm';dialog.setAttribute('aria-label','删除本游戏历史');
      const title=document.createElement('h3'),message=document.createElement('p'),actions=document.createElement('div');
      title.textContent='删除本游戏历史？';message.textContent='永久删除“'+name+'”的原文对照记录，无法撤销。不影响其他游戏。';
      const cancel=document.createElement('button'),remove=document.createElement('button');
      cancel.className='btn';cancel.textContent='保留历史';remove.className='btn danger-ghost';remove.textContent='永久删除';
      cancel.addEventListener('click',()=>dialog.close('cancel'));
      remove.addEventListener('click',()=>dialog.close('delete'));
      actions.append(cancel,remove);dialog.append(title,message,actions);document.body.append(dialog);
      dialog.addEventListener('close',()=>{const approved=dialog.returnValue==='delete';dialog.remove();resolve(approved);},{once:true});
      dialog.showModal();cancel.focus();
    });
  }
  let historyDeletePending=false;
  $('#btn-history-delete')?.addEventListener('click',run(async()=>{
    if(!state.session || historyDeletePending) return;
    const profileId=state.session.profile_id;
    const name=state.profiles.find(p=>p.id===profileId)?.name || profileId;
    historyDeletePending=true;
    try {
      if(!await confirmHistory(name)) return;
      await api.request('/history?profile_id='+encodeURIComponent(profileId),'DELETE');
      state.page=1;await history();
    } finally {historyDeletePending=false;}
  }));
  $('#btn-history-export').addEventListener('click',run(async()=>{
    const items=[];
    for(let offset=0;offset<10000;offset+=200) {
      const data=await api.request('/history?profile_id='+encodeURIComponent(state.session.profile_id)+'&limit=200&offset='+offset);
      items.push(...data.items);if(!data.has_more) break;
    }
    download(items,'history-utf8.json');
  }));
  function profiles() {
    const grid=$('#profile-grid');grid.replaceChildren();
    for(const p of state.profiles) {
      const button=document.createElement('button');button.className='profile-card'+(p.id===state.session?.profile_id?' on':'');
      button.dataset.profile=p.id;
      const name=document.createElement('div'),desc=document.createElement('div');name.className='pc-name';desc.className='pc-desc';
      name.textContent=p.name;desc.textContent='字幕 '+(p.prefs.font||22)+'px · '+(p.prefs.source_kind==='clipboard'?'剪贴板':'手动输入');
      button.append(name,desc);button.addEventListener('click',run(()=>serialized(()=>session(p.id))));grid.append(button);
    }
  }
  async function session(id) {
    await saving;
    state.session=await api.request('/sessions','POST',{profile_id:id});
    state.sequence=0;state.active=null;state.page=1;state.lastInput=null;
    const p=state.profiles.find(p=>p.id===id), pref=p?.prefs || {};
    state.entries=structuredClone(p?.glossary || []);glossary();profiles();
    $('#sub-font').value=pref.font||22;$('#sub-opacity').value=pref.opacity||62;
    $$('#sub-mode button').forEach(b=>b.classList.toggle('on',b.dataset.mode===(pref.mode||'both')));
    preview();await source(pref.source_kind||'manual',false);await history();
    $('#stream-original').textContent='';$('#stream-translation').textContent='';tag('待输入');
  }
  async function poll() {
    if(polling || !state.connected) return;
    polling=true;
    try {
      const s=await api.request('/status');
      status(s);
      const sub=await api.request('/subtitle');
      subtitle(sub);
      if(['final','cancelled','error'].includes(sub.state) && sub.request_id!==lastHistoryRequest) {
        lastHistoryRequest=sub.request_id;
      }
      notices.changed('connection',null);
    } catch(e) {if(notices.changed('connection',{code:e.code||'DISCONNECTED',message:e.message}))error(e);$('#state-text').textContent='连接中断';$('#btn-translate').disabled=true;}
    finally {polling=false;}
  }
  window.addEventListener('pagehide',()=>{api.request('/lease','DELETE',undefined,true).catch(()=>{});});
  window.addEventListener('pageshow',()=>{if(state.connected) api.request('/lease','POST',{}).catch(error);});
  (async()=>{
    try {
      await api.connect();state.connected=true;
      theme((await api.request('/settings')).theme);
      state.profiles=await api.request('/profiles');profiles();
      const s=await api.request('/status');
      if(s.session) {
        state.session=s.session;state.sequence=s.session.sequence;
        const p=state.profiles.find(p=>p.id===s.session.profile_id);
        state.entries=structuredClone(p?.glossary||[]);
        $('#sub-font').value=p?.prefs.font||22;$('#sub-opacity').value=p?.prefs.opacity||62;
        $$('#sub-mode button').forEach(b=>b.classList.toggle('on',b.dataset.mode===(p?.prefs.mode||'both')));
        glossary();profiles();preview();await source(p?.prefs.source_kind||'manual',false);await history();
      }
      await api.request('/lease','POST',{});
      await poll();setInterval(poll,1000);
      setInterval(()=>api.request('/lease','POST',{}).catch(error),15000);
    } catch(e) {error(e);}
  })();
})();
