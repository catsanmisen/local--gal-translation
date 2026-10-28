using System.Text.Json;
using GalTransl.Desktop;
static class ReliabilityChecks {
    public static void Run(Action<bool,string> check){
        var hook=HookProtocol.Parse("[5:DFD0:8733368:1FB5E7B4:0:string:wstrcpy (char*,char*,int) [:HWFX4@8733368] 日本語の台詞");
        check(hook?.Name=="string:wstrcpy (char*,char*,int) ["&&hook.Code=="HWFX4@8733368"&&hook.Pid==57296,"actual Textractor colon/bracket hook name preserves the correct code and process");
        var module=HookProtocol.Parse("[2:DFD0:5EEBB450:5F85079F:0:mono_string_new_len:HSX65001#8@18B450:mono-2.0-bdwgc.dll] 「本文 ] 後半」");
        check(module?.Code=="HSX65001#8@18B450:mono-2.0-bdwgc.dll"&&module.Text=="「本文 ] 後半」","module colon and dialogue brackets never shift the header boundary");
        check(HookProtocol.Parse("[5:FFFFFFFF:1:0:0:Name:HQ@1] 台詞")==null,"invalid process value cannot fault the hook reader task");
        check(HookProtocol.Parse("[5:DFD0:1:0:0:Name:HQ@1] "+new string('文',2100))==null,"oversized hook memory dumps never reach the thread list or model");
        check(!HookProtocol.Readable("台詞\0binary")&&!HookProtocol.Readable("文\uFFFD\uFFFD\uFFFD\uFFFD\uFFFD"),"binary and replacement-character dumps are refused");
        check(HookProtocol.Readable("「%s\\N\\C[1]本文」\n次の行"),"literal engine controls, variables and real multi-line dialogue remain intact");
        check(HookProtocol.Append(module!,"次の行")?.Text.EndsWith("\n次の行")==true,"valid hook continuation preserves line boundaries");
        check(HookProtocol.Append(module!,"[B:broken header")==null,"a malformed new header cannot be appended into the previous dialogue");
        var embedded="memory[9:8B10:84A3368:1D2F5CFC:0:string:wstrcpy [:HWFX4@84A3368]本文";
        check(!HookProtocol.Readable(embedded)&&HookProtocol.Append(module!,embedded)==null,"observed nested Textractor headers cannot be accepted as dialogue continuations");
        check(HookProtocol.CanRestore(new(){Code="HSX65001#8@18B450:mono-2.0-bdwgc.dll",Context="0",Context2="FF"}),"module-relative hook with fixed contexts can be restored without process addresses");
        check(!HookProtocol.CanRestore(new(){Code="HWFX4@84A3368"})&&!HookProtocol.CanRestore(new(){Code="HQ@1000:game.exe",Context="1D2F5CFC"})&&!HookProtocol.CanRestore(new(){Code="detach -P1@1000:game.exe"}),"absolute JIT hook, dynamic context and CLI commands cannot become saved desktop threads or be reinserted on restart");
        var inbox=new HookInbox();
        for(int i=0;i<2000;i++)inbox.Put(module! with{Handle=i.ToString(),Text="扫描样本"+i});
        check(inbox.Drain().Count==128&&inbox.Drain().Count==0,"a hook scanner burst retains at most 128 latest threads and drains once");
        inbox.Put(module!);inbox.Put(module! with{Text="前半\n後半"});
        check(inbox.Drain().Single().Text=="前半\n後半","coalesced hook updates retain the complete latest multiline text");
        inbox.Put(module!,true);for(int i=0;i<2000;i++)inbox.Put(module! with{Handle="noise-"+i});
        check(inbox.Drain().Last()==module,"selected dialogue survives unrelated scanner thread churn");
        inbox.Put(module!,true);inbox.Clear();check(inbox.Drain().Count==0,"unbind discards pending selected and scanner hook text");
        var mutexName="Local\\GalTranslExitCheck-"+Guid.NewGuid().ToString("N");
        using(var owner=new Mutex(true,mutexName)){
            var timeout=Task.Run(()=>{using var peer=new Mutex(false,mutexName);return InstanceExit.Wait(peer,TimeSpan.FromMilliseconds(40));}).GetAwaiter().GetResult();
            check(!timeout,"shutdown wait reports a still-running instance instead of claiming completion");
            using var ready=new ManualResetEventSlim();
            var waiting=Task.Run(()=>{using var peer=new Mutex(false,mutexName);ready.Set();return InstanceExit.Wait(peer,TimeSpan.FromSeconds(2));});
            ready.Wait();check(!waiting.IsCompleted,"immediate restart waits while the previous instance owns the mutex");
            owner.ReleaseMutex();check(waiting.GetAwaiter().GetResult(),"shutdown wait completes after the former instance releases its lock");
        }
        using(var peer=new Mutex(false,"Local\\GalTranslAbandonedCheck-"+Guid.NewGuid().ToString("N"))){
            var ownerThread=new Thread(()=>{peer.WaitOne();});ownerThread.Start();ownerThread.Join();
            check(InstanceExit.Wait(peer,TimeSpan.FromSeconds(1)),"abandoned instance mutex is accepted as a completed exit");
        }
        var a=new Profile{Id="a",Game=new(){Executable="A.exe"}};var b=new Profile{Id="b",Game=new(){Executable="B.exe"}};
        check(ProfileDrafts.Selected(b,a)==b,"explicit saved profile wins over the active game");
        check(!ProfileDrafts.CanRebind(b,a,new(1,1,"A.exe","game",default)),"editing another profile cannot bind it to the current game window");
        check(ProfileDrafts.CanRebind(a,a,new(1,1,"a.exe","game",default)),"same profile can rebind only its matching executable");
        var drafts=new ProfileDrafts();drafts.Edit("a",new(){{"backlog","Ctrl+Alt+B"}});a.Game.Hotkeys["backlog"]="Ctrl+Shift+B";
        check(drafts.Read(a)["backlog"]=="Ctrl+Alt+B","profile polling preserves an unsaved shortcut draft");
        drafts.Read(b);check(drafts.Read(a)["backlog"]=="Ctrl+Alt+B","switching profiles preserves separate drafts");
        drafts.Saved("a");check(drafts.Read(a)["backlog"]=="Ctrl+Shift+B","successful save releases the draft for later external changes");
        using var valid=JsonDocument.Parse("{\"desktop_protocol\":2,\"api\":\"/api/v1\",\"token\":\"test\",\"backend_root\":\"E:/app\",\"database_path\":\"E:/app/data.db\",\"instance_id\":\"test-instance\"}");BackendProtocol.Verify(valid.RootElement);
        check(true,"compatible desktop protocol accepted before authentication");
        foreach(var json in new[]{"{}","{\"desktop_protocol\":\"1\"}","{\"desktop_protocol\":2,\"api\":\"/api/v1\",\"token\":\"test\"}"}){
            using var invalid=JsonDocument.Parse(json);var rejected=false;try{BackendProtocol.Verify(invalid.RootElement);}catch(BackendCompatibilityException){rejected=true;}
            check(rejected,"old or malformed backend cannot be silently attached");
        }
        BackendProtocol.VerifyLocation("E:/app/","E:/app/data.db","e:/APP","e:/app/data.db");
        check(true,"backend identity tolerates Windows path case and trailing separator");
        foreach(var pair in new[]{("E:/other","E:/app/data.db"),("E:/app","E:/other/data.db")}){
            var rejected=false;try{BackendProtocol.VerifyLocation(pair.Item1,pair.Item2,"E:/app","E:/app/data.db");}catch(BackendCompatibilityException){rejected=true;}
            check(rejected,"same protocol cannot attach another installation or database");
        }
        var budget=new BackendRecovery();
        check(!budget.Failed(0)&&!budget.Failed(30)&&budget.Failed(60),"live backend requires three failures across sixty seconds before recycle");budget.Restarted(60);
        budget.Failed(61);budget.Failed(91);check(budget.Failed(121),"a second bounded owned restart is permitted");budget.Restarted(121);
        budget.Failed(122);budget.Failed(152);check(!budget.Failed(182),"owned backend restart storm is limited to two in ten minutes");
        check(budget.Failed(661),"restart allowance returns only after its cooldown window");
        budget.Healthy();check(!budget.Failed(662),"healthy probe resets consecutive transport failures");
        JsonElement Snapshot(string id,int scope,int text,int sequence,string? request)=>JsonSerializer.SerializeToElement(new{game_session=new{game_session_id=id,epoch=scope},subtitle=new{epoch=text,sequence,request_id=request}});
        var shown=new Caption("","","final","r",2,10,null,null);
        check(!SnapshotGate.Accept(Snapshot("g",2,1,100,"old"),"g",true,2,shown),"current game metadata cannot legitimize a subtitle from an old epoch");
        check(!SnapshotGate.Accept(Snapshot("other",2,2,11,"new"),"g",true,2,shown),"foreign game snapshot cannot replace current subtitle");
        check(!SnapshotGate.Accept(Snapshot("g",2,2,9,"old"),"g",true,2,shown),"older sequence cannot replace current subtitle");
        check(!SnapshotGate.Accept(Snapshot("g",2,2,10,"different"),"g",true,2,shown),"same sequence with a different request identity is refused");
        check(SnapshotGate.Accept(Snapshot("g",3,3,0,null),"g",true,2,shown),"fresh reset epoch with no request clears old caption");
        check(!SnapshotGate.Accept(Snapshot("g",2,2,11,"new"),null,true,2,shown),"reconnect cannot display data before bound game identity is restored");
        var regions=new CaptureRegions();var primary=new Region(0,.7,1,.2);var special=new Region(.1,.1,.8,.8);
        var fullscreenCrop=CaptureRegions.WithMargin(new(.051,.761,.766,.181));
        check(fullscreenCrop.Y<.75&&fullscreenCrop.Width>.766&&fullscreenCrop.Height>.181,"bounded OCR margin retains glyph tops after the observed fullscreen letterbox shift");
        var edgeCrop=CaptureRegions.WithMargin(new(0,.9,1,.1));
        check(edgeCrop.X==0&&edgeCrop.Y>=0&&edgeCrop.Width==1&&edgeCrop.Y+edgeCrop.Height<=1,"OCR margin stays inside the bound game client at every edge");
        check(regions.Choose(primary,special,0).Region==primary,"regular capture region remains the default");
        regions.Observe(false,"旧正文",0,true);regions.Observe(false,"",100,true);
        check(!regions.Special,"one empty frame does not switch capture regions");
        var switchToSpecial=regions.Observe(false,"",550,true);check(!switchToSpecial.Switched&&!regions.Special,"confirmed empty regular region waits for fresh special text");
        check(regions.Choose(primary,special,600).IsSpecial,"fallback uses one region and one OCR task");
        check(!regions.Observe(true,"特殊正文",600,true).Process,"blank fallback requires a second observation before switching");
        regions.Choose(primary,special,800);regions.Observe(false,"",800,true);
        check(regions.Observe(true,"特殊正文",1200,true).Switched&&regions.Special,"fresh confirmed special text activates the fallback");
        regions.Choose(primary,special,1300);
        check(!regions.Choose(primary,special,2300).IsSpecial,"special capture periodically probes the regular region");
        check(!regions.Observe(false,"旧正文",1600,true).Process&&regions.Special,"an unchanged old primary page cannot replace special text");
        check(!regions.Observe(false,"新正文",2600,true).Switched&&regions.Special,"one new regular observation waits for confirmation");
        check(regions.Observe(false,"新正文",3600,true).Switched&&!regions.Special,"confirmed new regular text restores the main region");
        var sampling=new OcrSampling();sampling.Checked("text-1",1000);
        check(sampling.Skip("text-1",1200,true,false),"unchanged text pixels skip redundant OCR despite background change");
        check(!sampling.Skip("text-2",1200,true,false),"changed glyph pixels immediately require OCR");
        check(!sampling.Skip("text-1",1700,true,false),"periodic full OCR detects new rows outside the old mask");
        check(!sampling.Skip("text-1",1200,false,false)&&!sampling.Skip("text-1",1200,true,true),"unfinished text and resized geometry never use OCR sampling cache");
        var page=new PageText();var accepted=page.Read("そうなの？");page.Accept("そうなの？",accepted);
        check(!page.Read("そうなの！").Same,"real question versus exclamation changes are not discarded as OCR punctuation drift");
        check(page.Read("そうなの?").Same,"fullwidth question mark typography remains the same dialogue");
    }
}
