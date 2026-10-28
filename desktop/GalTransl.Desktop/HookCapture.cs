using System.Diagnostics;
using System.Text;

namespace GalTransl.Desktop;

public sealed class HookCapture:IDisposable {
    readonly Process process;readonly CancellationTokenSource stop=new();readonly int gamePid;
    readonly ChildJob job;
    public Action<HookText>? Text {get;set;}
    public bool Running=>!process.HasExited;
    public static HookText? Parse(string line)=>HookProtocol.Parse(line);
    public HookCapture(string root,int pid,HookSelection? selection){
        gamePid=pid;
        if(!Assets.Validate(Path.Combine(root,"backend","vendor","textractor")))throw new InvalidOperationException("HOOK 组件校验失败，请重新构建。");
        var exe=Path.Combine(root,"backend","vendor","textractor",Native.Is32(pid)?"x86":"x64","TextractorCLI.exe");
        if(!File.Exists(exe))throw new FileNotFoundException("HOOK 组件未安装",exe);
        process=new Process{StartInfo=new ProcessStartInfo(exe){WorkingDirectory=Path.GetDirectoryName(exe),UseShellExecute=false,CreateNoWindow=true,
            RedirectStandardInput=true,RedirectStandardOutput=true,RedirectStandardError=true,StandardInputEncoding=new UnicodeEncoding(false,false),StandardOutputEncoding=Encoding.Unicode}};
        process.Start();try{job=new ChildJob(process);}catch{process.Kill(true);process.Dispose();throw;}
        process.StandardInput.AutoFlush=true;process.StandardInput.WriteLine("attach -P"+pid);
        if(selection!=null&&HookProtocol.CanRestore(selection)&&selection.Code is {Length:>0} code)process.StandardInput.WriteLine(code+" -P"+pid);
        _=Task.Run(async()=>{
            HookText? pending=null;
            try{
                while(!stop.IsCancellationRequested){
                    var line=await process.StandardOutput.ReadLineAsync(stop.Token);if(line==null)break;
                    var entry=Parse(line);
                    if(entry!=null){pending=entry;Text?.Invoke(entry);}
                    else if(HookProtocol.LooksLikeHeader(line))pending=null;
                    else if(pending!=null){pending=HookProtocol.Append(pending,line);if(pending!=null)Text?.Invoke(pending);}
                }
            }catch(OperationCanceledException){}catch(IOException){}
        });
        _=Task.Run(async()=>{try{while(await process.StandardError.ReadLineAsync(stop.Token)!=null){}}catch(OperationCanceledException){}});
    }
    public static bool Matches(HookText text,HookSelection selected)=>text.Name==selected.Name&&text.Code==selected.Code&&
        (selected.Context.Length==0||text.Context==selected.Context)&&(selected.Context2.Length==0||text.Context2==selected.Context2);
    public void Dispose(){stop.Cancel();try{if(!process.HasExited){process.StandardInput.WriteLine("detach -P"+gamePid);process.StandardInput.Close();if(!process.WaitForExit(1500))process.Kill(true);}}catch(InvalidOperationException){}catch(IOException){}job.Dispose();process.Dispose();stop.Dispose();}
}
