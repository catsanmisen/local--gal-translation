using System.Diagnostics;
using System.IO.Pipes;
using System.Text;
using System.Windows;

namespace GalTransl.Desktop;

public static class Program {
    [STAThread] public static void Main(string[] args){
        var port=18039;var root=FindRoot();string? database=null;
        for(int i=0;i<args.Length;i++)if(args[i]=="--port")port=int.Parse(args[++i]);else if(args[i]=="--root")root=Path.GetFullPath(args[++i]);else if(args[i]=="--database")database=Path.GetFullPath(args[++i]);
        if(port is <1 or >65535)throw new ArgumentException("客户端端口无效");
        using var mutex=new Mutex(true,"Local\\GalTranslDesktop-"+port,out var first);
        if(args.Contains("--shutdown")||!first){
            try{using var pipe=new NamedPipeClientStream(".","GalTranslDesktop-"+port,PipeDirection.Out,PipeOptions.CurrentUserOnly);pipe.Connect(1000);using var writer=new StreamWriter(pipe,Encoding.UTF8){AutoFlush=true};writer.WriteLine(args.Contains("--shutdown")?"exit":"show");}
            catch(IOException){if(args.Contains("--shutdown")){using var api=new Api(port);try{api.Connect().GetAwaiter().GetResult();api.Call("/shutdown","POST",new{}).GetAwaiter().GetResult();}catch(System.Net.Http.HttpRequestException){}catch(TaskCanceledException){}}}
            catch(TimeoutException){if(args.Contains("--shutdown")){using var api=new Api(port);try{api.Connect().GetAwaiter().GetResult();api.Call("/shutdown","POST",new{}).GetAwaiter().GetResult();}catch(System.Net.Http.HttpRequestException){}catch(TaskCanceledException){}}}
            if(args.Contains("--shutdown")&&!first&&!InstanceExit.Wait(mutex,TimeSpan.FromSeconds(20)))Environment.ExitCode=1;
            return;
        }
        var app=new Application{ShutdownMode=ShutdownMode.OnExplicitShutdown};var apiClient=new Api(port);var backend=new OwnedBackend(root,port,database);Coordinator? host=null;ManagerWindow? manager=null;
        var stop=new CancellationTokenSource();System.Windows.Forms.NotifyIcon? tray=null;
        bool exiting=false;
        void Trace(string message){try{Directory.CreateDirectory(Path.Combine(root,"logs"));File.AppendAllText(Path.Combine(root,"logs","desktop.log"),DateTimeOffset.Now.ToString("O")+" "+message+Environment.NewLine);}catch(IOException){}}
        Trace("host starting, port="+port);
        app.Startup+=async(_,_)=>{
            Trace("application startup");
            try{
                await backend.Connect(apiClient);Trace(backend.Owns?"owned backend connected":"compatible backend connected");
                Trace("creating overlay");var verification=args.Contains("--verification");var overlay=new Overlay(verification);host=new Coordinator(root,apiClient,overlay,verification||args.Contains("--diagnostics")){Reconnect=()=>backend.Recover(apiClient)};await host.Start();Trace("coordinator ready");manager=new ManagerWindow(host);
                if(!host.Profiles.Any(p=>p.Game.Enabled&&p.Game.Executable!=null&&p.Game.Region!=null)){manager.Show();Trace("first configuration shown");}
                else Trace("saved configuration restored; settings remain in tray");
                tray=new System.Windows.Forms.NotifyIcon{Icon=System.Drawing.SystemIcons.Application,Text="GalTransl · 游戏旁实时翻译",Visible=true};
                var menu=new System.Windows.Forms.ContextMenuStrip();menu.Items.Add("游戏设置",null,(_,_)=>{manager.Show();manager.Activate();});
                menu.Items.Add("显示 / 隐藏字幕",null,(_,_)=>overlay.Hotkey?.Invoke(1));menu.Items.Add("暂停 / 恢复采集",null,(_,_)=>overlay.Hotkey?.Invoke(2));
                menu.Items.Add("查看 / 关闭历史翻译（Backlog）",null,(_,_)=>host.ToggleBacklog());
                menu.Items.Add("查看当前句全文",null,(_,_)=>host.ShowCurrentText());
                menu.Items.Add("调整字幕位置 / 结束调整",null,(_,_)=>{overlay.Edit(!overlay.Editing);host.RefreshOverlay();});
                menu.Items.Add("字幕摆放与特殊文字演出",null,(_,_)=>host.ShowPosition());
                menu.Items.Add("退出客户端",null,async(_,_)=>await Exit());tray.ContextMenuStrip=menu;tray.DoubleClick+=(_,_)=>{manager.Show();manager.Activate();};
                _=Task.Run(async()=>{while(!stop.IsCancellationRequested){
                    try{using var pipe=new NamedPipeServerStream("GalTranslDesktop-"+port,PipeDirection.In,1,PipeTransmissionMode.Byte,PipeOptions.Asynchronous|PipeOptions.CurrentUserOnly);await pipe.WaitForConnectionAsync(stop.Token);
                        using var reader=new StreamReader(pipe,Encoding.UTF8);var command=await reader.ReadLineAsync(stop.Token);
                        _=app.Dispatcher.InvokeAsync(async()=>{if(command=="exit")await Exit();else {manager.Show();manager.Activate();}});
                    }catch(OperationCanceledException){break;}
                }});
            }catch(Exception e){Trace(e.ToString());System.Windows.MessageBox.Show(e.Message,"GalTransl 启动未完成");app.Shutdown();}
        };
        async Task Exit(){
            if(exiting)return;exiting=true;
            try{if(host!=null)await host.Unbind();if(backend.Owns)await backend.Shutdown(apiClient);else await apiClient.Call("/lease","DELETE");}
            catch(Exception){}finally{stop.Cancel();host?.Dispose();tray?.Dispose();if(manager!=null)manager.AllowClose=true;app.Shutdown();}
        }
        app.Exit+=(_,_)=>{stop.Cancel();host?.Dispose();tray?.Dispose();apiClient.Dispose();backend.Dispose();};app.Run();
    }
    static string FindRoot(){for(var d=new DirectoryInfo(AppContext.BaseDirectory);d!=null;d=d.Parent)if(File.Exists(Path.Combine(d.FullName,"backend","src","server.py")))return d.FullName;return Environment.CurrentDirectory;}
}
