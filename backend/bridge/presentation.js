/* Single production subtitle/error presentation shared by both connected windows. */
(function(root) {
  'use strict';
  const reasons={user_cancelled:'用户取消',superseded:'被新台词取代',session_reset:'会话重置',engine_stopped:'模型已停止',client_disconnected:'连接断开'};
  const labels={idle:'等待输入',capturing:'读取台词',paused:'采集已暂停',streaming:'翻译中',final:'已完成',cancelled:'已取消',error:'翻译失败',interrupted:'已中断'};
  function subtitle(payload={}) {
    const state=payload.state || 'idle';
    const valid=state==='final' || state==='streaming';
    const reason=payload.diagnostic?.message || reasons[payload.reason] || payload.reason || '';
    return {original:payload.ja || '',translation:valid?(payload.zh || ''):'',label:(labels[state] || '未完成')+(reason?'：'+reason:''),
      tone:state==='final'?'final':state==='streaming'?'streaming':state==='idle'?'':'broken',
      empty:state==='idle'?'等待译文':state==='capturing'?'正在读取完整台词…':state==='paused'?'采集已暂停':state==='streaming'?'翻译中…':state==='final'?'':'本条未完成，原文已保留'};
  }
  function prefs(bar,ja,zh,value={}) {
    const font=Number.isFinite(Number(value.font))?Math.max(14,Math.min(40,Number(value.font))):22;
    const opacity=Number.isFinite(Number(value.opacity))?Math.max(20,Math.min(100,Number(value.opacity))):62;
    bar.style.fontSize=font+'px';bar.style.opacity='1';bar.style.setProperty('--subtitle-opacity',opacity/100);
    ja.hidden=value.mode==='zh';zh.hidden=value.mode==='ja';
  }
  class Notices {
    constructor(){this.last=new Map();}
    changed(channel,error) {
      if(!error){this.last.delete(channel);return false;}
      const key=JSON.stringify([error.revision,error.occurred_at,error.code,error.message,error.retryable,error.severity]);
      if(this.last.get(channel)===key)return false;
      this.last.set(channel,key);return true;
    }
  }
  class ModelDraft {
    constructor(){this.value={model_mode:'auto',gpu_reserve_mib:2048,wallpaper_relief:true};this.dirty=false;}
    read(value){if(!this.dirty)this.saved(value);}
    edit(mode,reserve,relief=this.value.wallpaper_relief){this.value={model_mode:mode,gpu_reserve_mib:Number(reserve),wallpaper_relief:relief};this.dirty=true;}
    saved(value={}){this.value={model_mode:value.model_mode||'auto',gpu_reserve_mib:value.gpu_reserve_mib||2048,wallpaper_relief:value.wallpaper_relief!==false};this.dirty=false;}
  }
  function model(status={}) {
    const label={auto:'自动',cpu:'CPU',gpu:'GPU'};
    const choice=status.model_preferences?.model_mode||status.model?.requested_mode||'auto';
    const runtime=status.model?.execution_mode;
    const actual=runtime==='cpu'?'CPU':runtime==='gpu'?'GPU':runtime==='hybrid'?'GPU + CPU（'+(status.model.gpu_layers||0)+' 层在 GPU）':'尚未加载';
    const state=status.model_reloading?'正在切换':status.state==='paused'&&choice==='gpu'?'显存不足，等待 GPU':
      ({stopped:'未运行',starting:'启动中',loading:'加载中',error:'启动失败',stopping:'停止中'}[status.state]||'');
    return '选择 '+(label[choice]||choice)+' · 实际 '+actual+(state?' · '+state:'');
  }
  function wallpaper(value={}) {
    return value.message || (value.available===false?'自动壁纸控制不可用，壁纸保持现状。':'占用显存过大的壁纸可能暂时关闭，翻译结束后自动恢复。');
  }
  const presentation={subtitle,prefs,Notices,ModelDraft,model,wallpaper};
  root.ConnectionPresentation=presentation;
  if(typeof module!=='undefined' && module.exports)module.exports=presentation;
})(globalThis);
