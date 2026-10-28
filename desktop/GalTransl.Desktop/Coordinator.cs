using System.Diagnostics;
using System.Text.Json;
using System.Windows;

namespace GalTransl.Desktop;

public sealed class Coordinator:IDisposable {
    public Api Api {get;} public string Root {get;}public Overlay Overlay {get;}
    public List<Profile> Profiles {get;private set;}=[];
    public GameWindow? Current {get;private set;}public Profile? CurrentProfile {get;private set;}
    public string? Notice {get;private set;}
    public bool Paused {get;private set;} public bool Hidden {get;private set;}
    public ModelPreferences ModelSettings {get;private set;}=new();
    public bool ModelSettingsAvailable {get;private set;} public bool ModelReloading {get;private set;}
    public string ModelDescription {get;private set;}="模型尚未运行";
    public string WallpaperDescription {get;private set;}="占用显存过大的壁纸可能暂时关闭，翻译结束后自动恢复。";
    public bool WallpaperSettingsAvailable {get;private set;}
    public Func<Task<bool>>? Reconnect {get;set;}
    DateTime reconnectAfter=DateTime.MinValue;
    public event Action? Changed;
    public readonly Dictionary<string,HookText> Threads=new();
    readonly HookInbox hookInbox=new();
    readonly CancellationTokenSource lifetime=new();
    WindowCapture? capture;HookCapture? hook;TextStabilizer stable=new();
    string? gameId;int epoch;bool tickBusy,ocrBusy;int revision;string mode="ocr";
    long boundAt,lastHookAt;DateTime lastLease=DateTime.MinValue,lastProfiles=DateTime.MinValue;
    readonly bool ocrAvailable;
    readonly string? verificationLog;
    Caption caption=new("","","idle",null,0,0,null,null);
    readonly System.Windows.Threading.DispatcherTimer timer=new(){Interval=TimeSpan.FromMilliseconds(200)};
    readonly SemaphoreSlim events=new(1,1);readonly Queue<(int Line,string Phase,string Text,double Wait,int Revision,Dictionary<string,double> Timings)> eventQueue=new();
    bool eventSending,disposed;Dictionary<string,double> timings=new(),candidateTimings=new();int candidateTimingLine=-1;
    string? loggedFinal;
    string? diagnosticText;
    string? ocrNotice;
    string? recoveryNotice;
    bool captureTimedOut,captureMenu;
    Region? textRegion;
    Region? frameTextRegion;bool layoutChanged;
    BacklogWindow? backlog;
    PositionWindow? position;
    CurrentTextWindow? currentText;
    string? lastProfileId;
    byte[]? acceptedFrame;
    readonly PageText pageText=new();
    readonly CaptureRegions captureRegions=new();bool acceptedSpecial;
    readonly OcrSampling sampling=new();
    List<Region> frameLines=[];Region? avoidRegion;
    public Coordinator(string root,Api api,Overlay overlay,bool verification=false){
        if(verification){Directory.CreateDirectory(Path.Combine(root,"work"));verificationLog=Path.Combine(root,"work","native-verification.jsonl");}
        ocrAvailable=Assets.Validate(Path.Combine(root,"backend","vendor","ocr"))&&WindowCapture.Supported;
        Root=root;Api=api;Overlay=overlay;stable.Event=QueueEvent;
        stable.TimedOut=()=>{captureTimedOut=true;ocrNotice="文字演出仍在变化，已跳过未稳定文本；下一条稳定台词会自动继续。";Notice=ocrNotice;Changed?.Invoke();};
        overlay.Hotkey=id=>{if(id==1){Hidden=!Hidden;RefreshOverlay();}else if(id==2)_=Pause(!Paused);else if(id==3)_=Reset();else if(id==4)ToggleBacklog();};
        overlay.MagpieChanged=RefreshOverlay;
        overlay.BacklogRequested=ToggleBacklog;overlay.PositionRequested=ShowPosition;
        overlay.CurrentTextRequested=ShowCurrentText;
        overlay.InputEnabled=()=>Current!=null&&Native.Focused(Current)&&!Overlay.Editing;
        overlay.SingleInputRequested=()=>{
            var handle=Current?.Handle;var profileId=CurrentProfile?.Id;var input=CurrentProfile?.Game.HideInput;
            Application.Current.Dispatcher.InvokeAsync(()=>{
                if(disposed||Current==null||CurrentProfile==null||Current.Handle!=handle||CurrentProfile.Id!=profileId||CurrentProfile.Game.HideInput!=input||!Native.Focused(Current)||Overlay.Editing)return;
                Hidden=!Hidden;RefreshOverlay();Changed?.Invoke();
            });
        };
        overlay.Moved=(dx,dy)=>{if(Current is null||CurrentProfile is null)return;var bounds=Native.Magpie(Current.Handle)?.Dest??Native.ClientRect(Current.Handle);
            var dpi=Math.Max(96,Native.GetDpiForWindow(overlay.Handle))/96.0;
            CurrentProfile.Game.Anchor.Dx=Math.Clamp(CurrentProfile.Game.Anchor.Dx+dx*dpi/bounds.Width,-2,2);
            CurrentProfile.Game.Anchor.Dy=Math.Clamp(CurrentProfile.Game.Anchor.Dy+dy*dpi/bounds.Height,-2,2);_ = SavePosition(CurrentProfile);};
        timer.Tick+=async(_,_)=>await Tick();
    }
    public async Task Start(){await Reload();var prefs=await Api.Call("/settings");ReadModelSettings(prefs);Overlay.Show();Overlay.Hide();_ = Api.Subscribe(OnSnapshot,lifetime.Token);timer.Start();await Tick();}
    void ReadModelSettings(JsonElement value){ModelSettingsAvailable=value.TryGetProperty("model_mode",out _);if(ModelSettingsAvailable)ModelSettings=JsonSerializer.Deserialize<ModelPreferences>(value.GetRawText(),JsonConfig.Options)??new();}
    public async Task SaveModelSettings(string mode,int reserve,bool wallpaperRelief){
        var body=new Dictionary<string,object>{{"model_mode",mode},{"gpu_reserve_mib",reserve}};
        if(WallpaperSettingsAvailable)body["wallpaper_relief"]=wallpaperRelief;
        var value=await Api.Call("/settings","PATCH",body);ReadModelSettings(value);
        ModelReloading=value.TryGetProperty("model_reloading",out var reloading)&&reloading.GetBoolean();Changed?.Invoke();
    }
    public async Task Reload(){var p=await Api.Call("/profiles");Profiles=JsonSerializer.Deserialize<List<Profile>>(p.GetRawText(),JsonConfig.Options)??[];lastProfiles=DateTime.UtcNow;Changed?.Invoke();}
    public async Task Save(Profile p){
        if(Profiles.Any(x=>x.Id==p.Id))await Api.Call("/profiles","PATCH",new{id=p.Id,name=p.Name,game=new{executable=p.Game.Executable,region=p.Game.Region,auto_recovery=p.Game.AutoRecovery,enabled=p.Game.Enabled}});
        else await Api.Call("/profiles","PUT",new{id=p.Id,name=p.Name,game=p.Game});await Reload();
    }
    void OnSnapshot(JsonElement snapshot){
        Application.Current.Dispatcher.InvokeAsync(()=>{
            WallpaperSettingsAvailable=snapshot.TryGetProperty("wallpaper",out var wp)&&wp.TryGetProperty("available",out var wpAvailable)&&wpAvailable.ValueKind==JsonValueKind.True;
            if(wp.ValueKind==JsonValueKind.Object&&wp.TryGetProperty("message",out var wpMessage)&&wpMessage.ValueKind==JsonValueKind.String)WallpaperDescription=wpMessage.GetString()??"";
            if(snapshot.TryGetProperty("model_preferences",out var modelPrefs))ReadModelSettings(modelPrefs);
            ModelReloading=snapshot.TryGetProperty("model_reloading",out var loading)&&loading.GetBoolean();
            if(snapshot.TryGetProperty("model",out var model)){
                var actual=model.TryGetProperty("execution_mode",out var run)?run.GetString():null;
                var layers=model.TryGetProperty("gpu_layers",out var l)&&l.ValueKind==JsonValueKind.Number?l.GetInt32():0;
                var state=snapshot.TryGetProperty("engine_state",out var st)?st.GetString():null;
                var choice=ModelSettings.Mode=="cpu"?"CPU":ModelSettings.Mode=="gpu"?"GPU":"自动";
                var running=actual=="cpu"?"CPU":actual=="gpu"?"GPU":actual=="hybrid"?$"GPU + CPU（{layers} 层在 GPU）":"尚未加载";
                ModelDescription=$"选择 {choice} · 实际 {running}"+(ModelReloading?" · 正在切换":state=="paused"&&ModelSettings.Mode=="gpu"?" · 显存不足，等待 GPU":state=="stopped"?" · 未运行":state is "starting" or "loading"?" · 加载中":state=="error"?" · 启动失败":"");
            }
            Changed?.Invoke();
            if(!snapshot.TryGetProperty("subtitle",out var s))return;
            if(!SnapshotGate.Accept(snapshot,gameId,Current!=null,epoch,caption))return;
            caption=new(s.GetProperty("ja").GetString()??"",s.GetProperty("zh").GetString()??"",s.GetProperty("state").GetString()??"idle",
                s.TryGetProperty("request_id",out var r)&&r.ValueKind==JsonValueKind.String?r.GetString():null,
                s.TryGetProperty("epoch",out var e)&&e.ValueKind==JsonValueKind.Number?e.GetInt32():0,
                s.TryGetProperty("sequence",out var q)&&q.ValueKind==JsonValueKind.Number?q.GetInt32():0,
                s.TryGetProperty("diagnostic",out var diagnostic)&&diagnostic.ValueKind==JsonValueKind.Object&&diagnostic.TryGetProperty("message",out var message)&&message.ValueKind==JsonValueKind.String?message.GetString():
                    s.TryGetProperty("reason",out var reason)&&reason.ValueKind==JsonValueKind.String?reason.GetString():null,
                s.TryGetProperty("elapsed_ms",out var ms)&&ms.ValueKind==JsonValueKind.Number?ms.GetDouble():null);
            if(verificationLog!=null&&caption.State=="final"&&caption.RequestId!=loggedFinal){
                loggedFinal=caption.RequestId;
                File.AppendAllText(verificationLog,JsonSerializer.Serialize(new{at=DateTimeOffset.UtcNow,kind="display",request_id=caption.RequestId,epoch=caption.Epoch,sequence=caption.Sequence,elapsed_ms=caption.ElapsedMs})+Environment.NewLine);
            }
            if(snapshot.TryGetProperty("game_session",out var g)&&g.TryGetProperty("epoch",out var ge)&&ge.ValueKind==JsonValueKind.Number){
                var next=ge.GetInt32();if(next!=epoch){epoch=next;Invalidate(true);}
                var paused=g.GetProperty("paused").GetBoolean();if(paused!=Paused)Invalidate();Paused=paused;
                var recovery=g.GetProperty("recovery").GetString();
                if(recovery is "waiting_vram" or "waiting_stable_vram" or "loading")Notice="显存不足或模型正在恢复，最新台词已保留。";
                else if(recovery=="waiting_owned_stop")Notice=recoveryNotice="游戏窗口已变化，正在等待所属模型退出后重新连接。";
                else if(recovery=="blocked"&&g.TryGetProperty("recovery_error",out var startupError)&&startupError.ValueKind==JsonValueKind.Object&&startupError.TryGetProperty("message",out var startupMessage))Notice=recoveryNotice=startupMessage.GetString();
                else if(recovery=="retry_limit")Notice="恢复尝试已暂停，可从托盘恢复。";
                else if(recovery=="ready"&&Notice=="显存不足或模型正在恢复，最新台词已保留。")Notice=null;
                else if(recovery=="ready"&&Notice==recoveryNotice){Notice=null;recoveryNotice=null;}
                if(Notice is "CPU 兼容模式 · 显存留给游戏，翻译会稍慢" or "CPU 模式 · 使用处理器翻译")Notice=null;
                if(recovery=="ready"&&g.TryGetProperty("execution_mode",out var execution)&&execution.GetString()=="cpu"&&Notice==null)Notice=ModelSettings.Mode=="cpu"?"CPU 模式 · 使用处理器翻译":"CPU 兼容模式 · 显存留给游戏，翻译会稍慢";
            }
            RefreshOverlay();
        });
    }
    public void RefreshOverlay(){
        if(Current==null||CurrentProfile==null||Hidden||captureMenu||(!Overlay.Editing&&!GameFocused())){Overlay.HideAll();return;}
        if(!Overlay.Editing&&!caption.HasSource){Overlay.HideAll();return;}
        Overlay.Caption(caption,CurrentProfile,Notice);
        var visible=Overlay.Place(Current,CurrentProfile,textRegion,avoidRegion);Overlay.Present(visible);
    }
    bool GameFocused()=>Current!=null&&!Native.IsIconic(Current.Handle)&&(Native.Focused(Current)||Overlay.ControlsFocused);
    void Invalidate(bool newIdentity=false){revision++;stable.Reset(newIdentity);pageText.Reset(newIdentity);eventQueue.Clear();textRegion=null;frameTextRegion=null;avoidRegion=null;frameLines=[];acceptedFrame=null;sampling.Reset();captureTimedOut=captureMenu=false;if(newIdentity)captureRegions.Reset();}
    async Task Tick(){
        if(tickBusy)return;tickBusy=true;
        try{
            if(DateTime.UtcNow-lastLease>TimeSpan.FromSeconds(15)){await Api.Call("/lease","POST",new{});lastLease=DateTime.UtcNow;}
            if(DateTime.UtcNow-lastProfiles>TimeSpan.FromSeconds(3))await Reload();
            var windows=Native.Windows();
            if(Current!=null && (!Native.IsWindow(Current.Handle)||!windows.Any(w=>w.Handle==Current.Handle&&w.Pid==Current.Pid&&string.Equals(w.Executable,Current.Executable,StringComparison.OrdinalIgnoreCase))))await Unbind();
            if(Current==null){
                var pair=(from p in Profiles where p.Game.Enabled&&p.Game.Region!=null&&p.Game.Executable!=null
                    from w in windows where string.Equals(w.Executable,p.Game.Executable,StringComparison.OrdinalIgnoreCase)
                    orderby Native.Focused(w) descending select (p,w)).FirstOrDefault();
                if(pair.p!=null)await Bind(pair.w,pair.p);
            }
            if(Current==null)return;
            var hookUpdates=hookInbox.Drain();
            foreach(var entry in hookUpdates){
                if(entry.Pid!=Current.Pid)continue;
                if(!Threads.ContainsKey(entry.Handle)&&Threads.Count>=128){
                    var remove=Threads.Values.FirstOrDefault(t=>!Matches(t,CurrentProfile?.Game.Hook));
                    if(remove!=null)Threads.Remove(remove.Handle);
                }
                Threads[entry.Handle]=entry;
                if(CurrentProfile!=null&&CurrentProfile.Game.InputMode=="hook"&&Matches(entry,CurrentProfile.Game.Hook)&&GameFocused()&&!Paused){
                    if(mode!="hook"){mode="hook";Invalidate();capture?.Dispose();capture=null;Notice=null;}
                    timings=new(){{"capture_ms",0},{"ocr_ms",0}};stable.Observe(entry.Text);lastHookAt=Stopwatch.GetTimestamp();
                }
            }
            if(hookUpdates.Count>0)Changed?.Invoke();
            var clientRect=Native.ClientRect(Current.Handle);if(clientRect.Width!=Current.Client.Width||clientRect.Height!=Current.Client.Height)layoutChanged=true;
            Current=Current with{Client=clientRect};
            var refreshed=Profiles.FirstOrDefault(p=>p.Id==CurrentProfile?.Id);if(refreshed!=null)CurrentProfile=refreshed;
            if(CurrentProfile!=null)Overlay.ConfigureInput(CurrentProfile.Game.HideInput);
            var focused=GameFocused();
            var status=await Api.Call("/game-session","PUT",new{action="heartbeat",foreground=focused,native_subtitle=true,
                ocr_available=ocrAvailable,hook_available=hook?.Running??false,notice=Notice});
            if(!status.GetProperty("bound").GetBoolean()){await Bind(Current,CurrentProfile!);return;}
            var next=status.GetProperty("epoch").GetInt32();if(next!=epoch){epoch=next;Invalidate(true);}
            Paused=status.GetProperty("paused").GetBoolean();RefreshOverlay();
            if(!focused||Paused||CurrentProfile==null)return;
            if(mode=="hook"){
                if(hook?.Running!=true || (!Threads.Values.Any(t=>Matches(t,CurrentProfile.Game.Hook))&&Stopwatch.GetElapsedTime(boundAt).TotalSeconds>8)){
                    mode="ocr";Notice="HOOK 无法恢复，已切换到保存的 OCR 区域。";Invalidate();StartCapture();
                }else stable.Tick();
            }
            if(mode=="ocr"&&!ocrBusy&&CurrentProfile.Game.Region!=null){var selected=captureRegions.Choose(CurrentProfile.Game.Region,CurrentProfile.Game.SpecialRegion,Stopwatch.GetTimestamp()*1000.0/Stopwatch.Frequency,captureMenu);_ = ReadOcr(selected.Region,revision,selected.IsSpecial);}
        }catch(ApiError e){
            Notice=e.Message;
            if(e.DataJson.TryGetProperty("error",out var error)&&error.GetProperty("code").GetString()=="UNAUTHORIZED"){
                try{await Api.Connect();gameId=null;Invalidate(true);}catch(Exception){}
            }Changed?.Invoke();
        }catch(Exception e){Notice=e.Message;Changed?.Invoke();
            if((e is System.Net.Http.HttpRequestException or TaskCanceledException or IOException)&&Reconnect!=null&&DateTime.UtcNow>=reconnectAfter){
                reconnectAfter=DateTime.UtcNow.AddSeconds(30);var previous=Current;var profile=CurrentProfile;var wasPaused=Paused;var wasHidden=Hidden;
                gameId=null;Invalidate(true);Overlay.HideAll();caption=new("","","idle",null,0,0,null,null);
                try{if(await Reconnect()&&!disposed){
                    lastLease=DateTime.MinValue;await Reload();
                    if(previous!=null&&profile!=null&&Native.IsWindow(previous.Handle)){
                        await Bind(previous,Profiles.FirstOrDefault(p=>p.Id==profile.Id)??profile,wasPaused);Hidden=wasHidden;RefreshOverlay();
                    }Notice="后台连接已恢复。";
                }}catch(Exception recovery){Notice=recovery.Message;}Changed?.Invoke();
            }
        }
        finally{tickBusy=false;}
    }
    public async Task Bind(GameWindow game,Profile profile,bool restorePaused=false){
        if(Current!=null)await Unbind();Notice=null;Threads.Clear();Invalidate(true);
        caption=new("","","idle",null,0,0,null,null);
        var data=await Api.Call("/game-session","PUT",new{action="bind",profile_id=profile.Id,pid=game.Pid,hwnd=(long)game.Handle,foreground=!restorePaused&&Native.Focused(game),native_subtitle=true,ocr_available=ocrAvailable,hook_available=false});
        Current=game;CurrentProfile=profile;
        lastProfileId=profile.Id;
        gameId=data.GetProperty("game_session_id").GetString();epoch=data.GetProperty("epoch").GetInt32();mode=profile.Game.InputMode;boundAt=Stopwatch.GetTimestamp();
        if(mode=="hook"&&profile.Game.Hook is HookSelection saved&&!HookProtocol.CanRestore(saved)){
            mode="ocr";Notice="保存的 HOOK 依赖动态地址，已使用 OCR；请选择可恢复线程。";
        }
        Overlay.ConfigureHotkeys(profile.Game.Hotkeys);if(Overlay.HotkeyNotice!=null)Notice=Overlay.HotkeyNotice;
        Overlay.ResetPlacement();Overlay.ConfigureInput(profile.Game.HideInput);Hidden=false;
        if(mode=="hook")StartHook();else StartCapture();Changed?.Invoke();
        if(restorePaused)await Pause(true);
    }
    public async Task Unbind(){
        backlog?.Close();backlog=null;position?.Close();position=null;currentText?.Close();currentText=null;Overlay.Edit(false);Overlay.ConfigureInput("none");Overlay.ResetPlacement();
        Invalidate();capture?.Dispose();capture=null;hook?.Dispose();hook=null;hookInbox.Clear();
        try{if(gameId!=null)await Api.Call("/game-session","PUT",new{action="unbind"});}
        finally{gameId=null;Current=null;CurrentProfile=null;Overlay.HideAll();Changed?.Invoke();}
    }
    void StartCapture(){
        if(capture!=null||Current==null)return;
        try{capture=new WindowCapture(Current.Handle);}catch(Exception e){Notice="无法抓取游戏窗口："+e.Message;}
    }
    public void StartHook(){
        hook?.Dispose();hook=null;hookInbox.Clear();Threads.Clear();boundAt=Stopwatch.GetTimestamp();if(Current==null)return;
        try{
            hook=new HookCapture(Root,Current.Pid,CurrentProfile?.Game.Hook);
            var activeHook=hook;var selection=CurrentProfile?.Game.Hook;
            hook.Text=entry=>{if(ReferenceEquals(activeHook,hook))hookInbox.Put(entry,Matches(entry,selection));};
        }catch(Exception e){Notice=e.Message;mode="ocr";StartCapture();}
    }
    static bool Matches(HookText entry,HookSelection? selected)=>selected!=null&&HookCapture.Matches(entry,selected);
    public async Task SelectHook(HookText entry){
        if(CurrentProfile==null)return;var selected=new HookSelection{Name=entry.Name,Code=entry.Code,Context=entry.Context,Context2=entry.Context2};
        if(!HookProtocol.CanRestore(selected))throw new InvalidOperationException("此线程包含会随重启变化的地址，当前候选无法恢复。请使用 OCR，或选择模块相对地址、固定上下文的线程。");
        await PatchGame(CurrentProfile,new{hook=selected,input_mode="hook"});mode="hook";Invalidate();StartHook();
    }
    async Task ReadOcr(Region region,int scope,bool isSpecial=false){
        ocrBusy=true;
        try{
            StartCapture();if(capture==null||gameId==null)return;
            var cropRegion=CaptureRegions.WithMargin(region);
            var start=Stopwatch.GetTimestamp();var png=await capture.Crop(cropRegion,lifetime.Token,isSpecial==captureRegions.Special?frameTextRegion:null);var captureMs=Stopwatch.GetElapsedTime(start).TotalMilliseconds;
            if(png==null||scope!=revision||Current==null||!GameFocused())return;
            // Only reuse an identical frame whose text was accepted and has a
            // final caption. New/partial/unstable frames still require real OCR.
            if(caption.State=="final"&&isSpecial==captureRegions.Special&&isSpecial==acceptedSpecial&&acceptedFrame!=null&&png.AsSpan().SequenceEqual(acceptedFrame)){stable.Tick();return;}
            if(isSpecial==captureRegions.Special&&sampling.Skip(capture.TextSignature,Stopwatch.GetTimestamp()*1000.0/Stopwatch.Frequency,caption.State=="final",layoutChanged)){if(!captureMenu)stable.Tick();return;}
            var result=await Api.Ocr(png,gameId,epoch,lifetime.Token);
            if(scope!=revision||Current==null||!GameFocused()||Paused)return;
            if(!captureTimedOut){if(Notice==ocrNotice)Notice=null;ocrNotice=null;}
            var observed=CaptureTextFilter.Dialogue(result.GetProperty("text").GetString()??"");
            if(verificationLog!=null&&diagnosticText!=observed){
                diagnosticText=observed;var folder=Path.GetDirectoryName(verificationLog)!;
                File.WriteAllBytes(Path.Combine(folder,"native-ocr-latest.png"),png);
                File.WriteAllText(Path.Combine(folder,"native-ocr-latest.json"),JsonSerializer.Serialize(new{at=DateTimeOffset.UtcNow,profile_id=CurrentProfile?.Id,region=cropRegion,configured_region=region,client=Native.ClientRect(Current.Handle),window=Native.WindowRect(Current.Handle),result}));
            }
            // A menu suspends capture without becoming an empty page: returning
            // to the same dialogue restores its caption instead of translating it again.
            if(result.TryGetProperty("is_menu",out var menu)&&menu.ValueKind==JsonValueKind.True){
                if(isSpecial==captureRegions.Special){captureMenu=true;stable.Suspend();acceptedFrame=null;sampling.Checked(capture.TextSignature,Stopwatch.GetTimestamp()*1000.0/Stopwatch.Frequency);RefreshOverlay();}
                return;
            }
            if(isSpecial==captureRegions.Special)captureMenu=false;
            var route=captureRegions.Observe(isSpecial,observed,Stopwatch.GetTimestamp()*1000.0/Stopwatch.Frequency,CurrentProfile?.Game.SpecialRegion!=null);
            if(verificationLog!=null)File.AppendAllText(verificationLog,JsonSerializer.Serialize(new{at=DateTimeOffset.UtcNow,kind="ocr_route",isSpecial,activeSpecial=captureRegions.Special,process=route.Process,switched=route.Switched,text=observed,region=cropRegion,ocr_ms=result.GetProperty("ocr_ms").GetDouble()})+Environment.NewLine);
            if(route.Switched){Invalidate();pageText.Reset(true);Overlay.ResetPlacement();}
            if(!route.Process){if(route.Switched)stable.Observe("",true);return;}
            sampling.Checked(capture.TextSignature,Stopwatch.GetTimestamp()*1000.0/Stopwatch.Frequency);
            timings=new(){{"capture_ms",captureMs},{"ocr_ms",result.GetProperty("ocr_ms").GetDouble()}};
            if(result.TryGetProperty("text_bounds",out var bounds)){
                var recognized=JsonSerializer.Deserialize<Region>(bounds.GetRawText(),JsonConfig.Options);
                if(recognized!=null)frameTextRegion=new(cropRegion.X+recognized.X*cropRegion.Width,cropRegion.Y+recognized.Y*cropRegion.Height,recognized.Width*cropRegion.Width,recognized.Height*cropRegion.Height);
            }else frameTextRegion=null;
            frameLines=[];
            if(result.TryGetProperty("text_regions",out var rows))foreach(var row in rows.EnumerateArray()){
                var r=JsonSerializer.Deserialize<Region>(row.GetRawText(),JsonConfig.Options);
                if(r!=null)frameLines.Add(new(cropRegion.X+r.X*cropRegion.Width,cropRegion.Y+r.Y*cropRegion.Height,r.Width*cropRegion.Width,r.Height*cropRegion.Height));
            }
            if(layoutChanged&&frameTextRegion!=null){textRegion=frameTextRegion;layoutChanged=false;}
            var samePage=pageText.Read(observed).Same;
            acceptedFrame=caption.State=="final"&&samePage?png:null;
            acceptedSpecial=isSpecial;
            if(samePage&&caption.State=="final"){
                // Confirm returning whole-page evidence even on the no-inference
                // path, so an intermittent OCR variant cannot age across it.
                stable.Observe(observed,tolerateOcrNoise:true);
                // The same words may move during a special text performance.
                // Follow their current full bounds without clearing/replaying
                // the completed translation or resetting its request identity.
                textRegion=frameTextRegion;avoidRegion=frameTextRegion;RefreshOverlay();return;
            }
            stable.Observe(observed,tolerateOcrNoise:true);
        }catch(OperationCanceledException){}catch(Exception e){if(scope==revision&&Current!=null){ocrNotice=e.Message;Notice=ocrNotice;Changed?.Invoke();}}
        finally{ocrBusy=false;}
    }
    void QueueEvent(int line,string phase,string text,double wait){
        if(phase=="stable"&&captureTimedOut){captureTimedOut=false;if(Notice==ocrNotice)Notice=null;ocrNotice=null;}
        if(mode=="ocr"){
            if(phase=="empty"){pageText.Reset(!captureTimedOut);if(!captureTimedOut){avoidRegion=null;Overlay.ResetPlacement();}}
            else {
                var selected=pageText.Read(text);
                if(selected.Same){
                    // A rejected OCR variant may have already cleared the server caption.
                    // Restabilizing the accepted page must restore its latest delta instead
                    // of leaving the caption permanently in the capturing state.
                    if(phase!="stable"||caption.State is "final" or "streaming")return;
                }
                var page=text;text=selected.Text;
                textRegion=frameTextRegion;
                if(selected.FirstLine>0&&selected.FirstLine<frameLines.Count){
                    var rows=frameLines.Skip(selected.FirstLine).ToList();
                    var top=rows.Min(r=>r.Y);var bottom=rows.Max(r=>r.Y+r.Height);
                    textRegion=new(rows.Min(r=>r.X),top,rows.Max(r=>r.X+r.Width)-rows.Min(r=>r.X),bottom-top);avoidRegion=frameTextRegion;
                }else avoidRegion=null;
                if(phase=="stable")pageText.Accept(page,selected);
            }
        }
        else textRegion=frameTextRegion;
        if(phase=="empty")textRegion=null;
        if(phase=="preview"){candidateTimings=new(timings);candidateTimingLine=line;}
        var frameTimings=phase=="stable"&&candidateTimingLine==line?candidateTimings:timings;
        if(verificationLog!=null)File.AppendAllText(verificationLog,JsonSerializer.Serialize(new{at=DateTimeOffset.UtcNow,kind="capture",line,phase,text,wait,revision,mode,timings=frameTimings})+Environment.NewLine);
        // A slow connection must not turn fast-forward into a backlog of old lines.
        if(eventQueue.Count>0&&eventQueue.Peek().Line!=line)eventQueue.Clear();
        eventQueue.Enqueue((line,phase,text,wait,revision,new(frameTimings)));if(!eventSending)_=SendEvents();
    }
    async Task SendEvents(){
        eventSending=true;
        try{while(eventQueue.Count>0){
            var ev=eventQueue.Dequeue();if(ev.Revision!=revision||gameId==null||Current==null||!GameFocused()||Paused)continue;
            var t=ev.Timings;t["stable_wait_ms"]=ev.Wait;
            var body=new{game_session_id=gameId,epoch,line_id=ev.Line,event_id=Guid.NewGuid().ToString(),phase=ev.Phase,source_kind=mode,source_text=ev.Text,speaker=(string?)null,captured_at=DateTimeOffset.UtcNow.ToString("O"),timings=t};
            try{await Api.Call("/text-events","POST",body);}catch(ApiError e){
                if(ev.Revision!=revision)continue;
                if(e.DataJson.TryGetProperty("error",out var error)&&error.TryGetProperty("code",out var code)&&code.GetString()=="CAPTURE_PAUSED"){
                    // Focus may change between capture and delivery. Replay the
                    // current delta on return instead of marking a rejected page
                    // as accepted or leaving a permanent pause warning.
                    Invalidate();Notice=null;
                }else Notice=e.Message;
            }
            catch(Exception){
                // One retry of the identical identity is safe; never invent a replacement ID after a transport failure.
                try{await Api.Call("/text-events","POST",body);}catch(Exception e){Notice=e.Message;Invalidate();}
            }
        }}finally{eventSending=false;}
    }
    public async Task Pause(bool pause){Paused=pause;Invalidate();await Api.Call("/game-session","PUT",new{action=pause?"pause":"resume"});Changed?.Invoke();}
    public async Task Reset(){Invalidate();await Api.Call("/game-session","PUT",new{action="reset"});Changed?.Invoke();}
    public void ToggleBacklog(){
        if(backlog!=null){backlog.Close();return;}
        var readerProfile=CurrentProfile??Profiles.FirstOrDefault(p=>p.Id==lastProfileId)??Profiles.FirstOrDefault(p=>p.Game.Executable!=null);
        if(readerProfile==null){Notice="请先保存游戏配置，再主动打开历史记录。";Changed?.Invoke();return;}
        backlog=new BacklogWindow(Api,readerProfile);backlog.Closed+=(_,_)=>backlog=null;backlog.Show();backlog.Activate();
    }
    public void ShowPosition(){
        if(position!=null){position.Activate();return;}
        if(CurrentProfile==null){Notice="请先连接游戏，再调整字幕摆放。";Changed?.Invoke();return;}
        position=new PositionWindow(this,CurrentProfile);position.Closed+=(_,_)=>position=null;position.Show();position.Activate();
    }
    public void HideOverlay(){Hidden=true;Overlay.Edit(false);RefreshOverlay();Changed?.Invoke();}
    public void ShowCurrentText(){
        if(currentText!=null){currentText.Activate();return;}if(CurrentProfile==null)return;
        currentText=new CurrentTextWindow(caption,CurrentProfile);currentText.Closed+=(_,_)=>currentText=null;currentText.Show();currentText.Activate();
    }
    async Task SaveGame(Profile profile,GameConfig game){
        await Api.Call("/profiles","PUT",new{id=profile.Id,name=profile.Name,game});await Reload();
    }
    public async Task PatchGame(Profile profile,object game){
        await Api.Call("/profiles","PATCH",new{id=profile.Id,game});await Reload();
        if(CurrentProfile?.Id==profile.Id)CurrentProfile=Profiles.First(p=>p.Id==profile.Id);
    }
    async Task SavePosition(Profile profile){try{await PatchGame(profile,new{anchor=profile.Game.Anchor});RefreshOverlay();}catch(Exception e){Notice="位置未保存："+e.Message;Changed?.Invoke();}}
    public async Task SetPlacement(Profile profile,string placement,bool resetOffset=false){
        // Save only game settings. Omitted prefs are preserved atomically by
        // the backend, including concurrent browser font/opacity changes.
        var current=Profiles.FirstOrDefault(p=>p.Id==profile.Id)??profile;
        var game=JsonSerializer.Deserialize<GameConfig>(JsonSerializer.Serialize(current.Game,JsonConfig.Options),JsonConfig.Options)!;
        game.SubtitlePlacement=placement;if(resetOffset)game.Anchor=new();
        if(resetOffset)await PatchGame(current,new{subtitle_placement=placement,anchor=new Anchor()});else await PatchGame(current,new{subtitle_placement=placement});
        Hidden=false;Overlay.Edit(false);Overlay.ResetPlacement();RefreshOverlay();Changed?.Invoke();
    }
    public async Task SetDialogueBox(Profile profile,Region? region){
        var current=Profiles.FirstOrDefault(p=>p.Id==profile.Id)??profile;
        var game=JsonSerializer.Deserialize<GameConfig>(JsonSerializer.Serialize(current.Game,JsonConfig.Options),JsonConfig.Options)!;
        await PatchGame(current,new Dictionary<string,object?>{{"dialogue_box",region}});
        if(CurrentProfile?.Id==current.Id)CurrentProfile=Profiles.First(p=>p.Id==current.Id);
        Overlay.ResetPlacement();RefreshOverlay();Changed?.Invoke();
    }
    public async Task SetHideInput(Profile profile,string input){
        var current=Profiles.FirstOrDefault(p=>p.Id==profile.Id)??profile;
        var game=JsonSerializer.Deserialize<GameConfig>(JsonSerializer.Serialize(current.Game,JsonConfig.Options),JsonConfig.Options)!;
        await PatchGame(current,new{hide_input=input});
        if(CurrentProfile?.Id==current.Id){CurrentProfile=Profiles.First(p=>p.Id==current.Id);Overlay.ConfigureInput(input);}
        Changed?.Invoke();
    }
    public async Task SetSpecialRegion(Profile profile,Region? region){await PatchGame(profile,new Dictionary<string,object?>{{"special_region",region}});captureRegions.Reset();Invalidate();pageText.Reset(true);}
    public async Task SetOpacity(Profile profile,int opacity){
        await Reload();var current=Profiles.FirstOrDefault(p=>p.Id==profile.Id)??profile;
        var prefs=new Dictionary<string,JsonElement>(current.Prefs){["opacity"]=JsonSerializer.SerializeToElement(opacity)};
        await Api.Call("/profiles","PATCH",new{id=current.Id,prefs=new{opacity}});await Reload();
        if(CurrentProfile?.Id==current.Id)CurrentProfile=Profiles.First(p=>p.Id==current.Id);
        RefreshOverlay();Changed?.Invoke();
    }
    public void Dispose(){if(disposed)return;disposed=true;timer.Stop();lifetime.Cancel();backlog?.Close();position?.Close();currentText?.Close();capture?.Dispose();hook?.Dispose();Overlay.DisposeHotkeys();lifetime.Dispose();}
}
