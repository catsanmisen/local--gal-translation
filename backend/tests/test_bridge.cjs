/* Behavioral checks for shared live presentation and notification episodes. */
const assert=require('node:assert/strict');
const {subtitle,prefs,Notices}=require('../bridge/presentation.js');
const p=require('../bridge/presentation.js');
let checks=0;
function test(name,fn){fn();checks++;console.log('PASS '+name);}
test('failed fragments are never shown as translations',()=>{
  for(const state of ['error','cancelled','interrupted']) {
    const result=subtitle({state,ja:'元の文\n二行',zh:'partial text',reason:'client_disconnected'});
    assert.equal(result.translation,'');assert.equal(result.original,'元の文\n二行');assert.equal(result.tone,'broken');
  }
});
test('streaming is always marked',()=>{const result=subtitle({state:'streaming',ja:'文',zh:'译'});assert.equal(result.translation,'译');assert.equal(result.label,'翻译中');});
test('final translation remains intact',()=>{assert.equal(subtitle({state:'final',zh:'完整\n译文'}).translation,'完整\n译文');});
test('cancel timeout cause is explicit',()=>{assert.match(subtitle({state:'cancelled',reason:'user_cancelled',diagnostic:{message:'回收超时，模型已停止'}}).label,/回收超时/);});
test('opacity changes only the background',()=>{
  const bar={style:{setProperty(name,value){this[name]=value}}},ja={},zh={};
  prefs(bar,ja,zh,{font:26,opacity:20,mode:'ja'});
  assert.equal(bar.style.opacity,'1');assert.equal(bar.style['--subtitle-opacity'],.2);
  assert.equal(bar.style.fontSize,'26px');assert.equal(ja.hidden,false);assert.equal(zh.hidden,true);
});
test('same error is displayed once per incident',()=>{
  const tracker=new Notices(),incident={code:'CLIPBOARD_BUSY',message:'忙',revision:1};
  assert.equal(tracker.changed('clipboard',incident),true);
  assert.equal(tracker.changed('clipboard',{...incident}),false);
  tracker.changed('clipboard',null);
  assert.equal(tracker.changed('clipboard',{...incident,revision:2}),true);
});
test('dismissed engine error is not reopened by polling',()=>{
  const tracker=new Notices(),error={code:'CANCEL_TIMEOUT',message:'模型已停止'};
  assert.equal(tracker.changed('engine',error),true);
  for(let i=0;i<20;i++)assert.equal(tracker.changed('engine',error),false);
  tracker.changed('engine',null);
  assert.equal(tracker.changed('engine',error),true);
});
test('CPU actual mode remains distinct from a pending GPU preference',()=>{
  const view=p.model({model:{execution_mode:'cpu'},state:'ready',model_preferences:{model_mode:'gpu'},model_reloading:true});
  assert.match(view,/CPU/);assert.match(view,/GPU/);assert.match(view,/切换/);
});
test('GPU low VRAM presentation explains waiting without a CPU fallback claim',()=>{
  const view=p.model({model:{requested_mode:'gpu'},model_preferences:{model_mode:'gpu'},state:'paused'});
  assert.match(view,/GPU/);assert.match(view,/等待/);assert.doesNotMatch(view,/已.*CPU/);
});
test('runtime polling preserves an unsaved model draft',()=>{
  const draft=new p.ModelDraft();draft.read({model_mode:'cpu',gpu_reserve_mib:2048});draft.edit('gpu',1024);
  draft.read({model_mode:'auto',gpu_reserve_mib:1536});assert.deepEqual(draft.value,{model_mode:'gpu',gpu_reserve_mib:1024,wallpaper_relief:true});
  draft.saved({model_mode:'gpu',gpu_reserve_mib:1024});assert.equal(draft.dirty,false);
});
test('wallpaper status distinguishes stopped and failed restoration',()=>{
  assert.equal(typeof p.wallpaper,'function');
  assert.match(p.wallpaper({state:'stopped',held:true,message:'高占用壁纸已临时停止'}),/停止/);
  assert.match(p.wallpaper({state:'restore_failed',held:true,message:'恢复暂时失败'}),/失败/);
});
test('polling cannot overwrite an unsaved wallpaper opt-out',()=>{
  const draft=new p.ModelDraft();draft.edit('gpu',1536,false);
  draft.read({model_mode:'cpu',gpu_reserve_mib:2048,wallpaper_relief:true});assert.equal(draft.value.wallpaper_relief,false);
  draft.edit('cpu',1536);assert.equal(draft.value.wallpaper_relief,false);
});
test('missing wallpaper capability gives a useful state',()=>{
  assert.match(p.wallpaper({available:false}),/不可用|未启用/);
});
console.log(checks+' bridge checks passed');
