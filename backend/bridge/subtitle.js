/* Live subtitle view: production rendering is shared with the main window. */
(async()=>{
  const api=new ClientApi(),bar=document.querySelector('#bar'),ja=document.querySelector('#ja'),zh=document.querySelector('#zh'),status=document.querySelector('#status');
  let busy=false;
  document.addEventListener('keydown',e=>{
    if(e.ctrlKey && e.shiftKey && e.key.toLowerCase()==='h'){e.preventDefault();bar.hidden=!bar.hidden;}
  });
  try{await api.connect();}catch(e){status.textContent='无法连接，请重新打开主窗口。';return;}
  async function update(){
    if(busy)return;busy=true;
    try{
      const s=await api.request('/subtitle'),settings=await api.request('/settings');
      document.documentElement.dataset.theme=settings.theme==='system'?(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light'):settings.theme;
      const view=ConnectionPresentation.subtitle(s);
      ja.textContent=view.original;zh.textContent=view.translation || view.empty;status.textContent=view.label;
      ConnectionPresentation.prefs(bar,ja,zh,s.prefs);
    }catch(e){status.textContent='连接中断，请重新打开主窗口。';}
    finally{busy=false;}
  }
  await update();setInterval(update,500);
})();
