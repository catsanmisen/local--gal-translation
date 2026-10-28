using System.Diagnostics;
using System.Net.NetworkInformation;
using System.Net.Http;
using System.Text.Json;
namespace GalTransl.Desktop;

public sealed class OwnedBackend(string root,int port,string? database,Func<double>? clock=null,TimeSpan? probeTimeout=null):IDisposable {
    Process? process;ChildJob? job;bool disposed;
    readonly SemaphoreSlim operation=new(1,1);readonly BackendRecovery recovery=new();
    string ExpectedDatabase=>database??Path.Combine(root,"data/client.sqlite3");
    void Verify(Api api)=>BackendProtocol.VerifyLocation(api.BackendRoot,api.DatabasePath,root,ExpectedDatabase);
    double Now=>clock?.Invoke()??Stopwatch.GetTimestamp()/(double)Stopwatch.Frequency;
    public bool Owns=>process!=null;
    public int? OwnedProcessId=>process?.Id;
    public async Task Connect(Api api){
        if(disposed)throw new ObjectDisposedException(nameof(OwnedBackend));
        try{await api.Connect();Verify(api);return;}catch(JsonException){throw new BackendCompatibilityException("此端口未返回兼容后台协议，不会接管其他服务。");}
        catch(Exception e) when(e is HttpRequestException or TaskCanceledException){}
        if(process!=null&&!process.HasExited)throw new IOException("后台暂时未响应，保留现有进程等待重连。");
        job?.Dispose();job=null;process?.Dispose();process=null;
        if(IPGlobalProperties.GetIPGlobalProperties().GetActiveTcpListeners().Any(p=>p.Port==port))
            throw new BackendCompatibilityException("端口已有服务，请退出旧客户端或改用空闲端口。不会结束其他进程。");
        var python=Path.Combine(root,"backend/runtime/python/python.exe");if(!File.Exists(python))python=Path.Combine(root,".venv-ocr/Scripts/python.exe");
        if(!File.Exists(python))throw new FileNotFoundException("Python 运行时未安装。",python);
        var info=new ProcessStartInfo(python){WorkingDirectory=root,UseShellExecute=false,CreateNoWindow=true};
        foreach(var arg in new[]{"-B",Path.Combine(root,"backend/src/server.py"),"--port",port.ToString()})info.ArgumentList.Add(arg);
        if(database!=null){info.ArgumentList.Add("--database");info.ArgumentList.Add(database);}
        process=Process.Start(info)??throw new IOException("后台进程未启动。");
        try{job=new ChildJob(process);}catch{try{process.Kill(true);}finally{process.Dispose();process=null;}throw;}
        try{for(int i=0;i<40;i++){
            await Task.Delay(250);if(disposed)throw new ObjectDisposedException(nameof(OwnedBackend));try{await api.Connect();Verify(api);return;}catch(Exception e) when(e is HttpRequestException or TaskCanceledException){if(process.HasExited)break;}
        }throw new IOException("后台启动超时，请检查日志。");}catch{job.Dispose();job=null;process.Dispose();process=null;throw;}
    }
    public async Task<bool> Recover(Api api){
        if(disposed)throw new ObjectDisposedException(nameof(OwnedBackend));
        await operation.WaitAsync();
        try{
            if(disposed)throw new ObjectDisposedException(nameof(OwnedBackend));
            // A shared, compatible backend may reconnect, but is never recycled here.
            if(!Owns){await api.Connect();Verify(api);await api.Call("/status");return true;}
            if(process!.HasExited){await Connect(api);recovery.Healthy();return true;}
            try{
                using var timeout=new CancellationTokenSource(probeTimeout??TimeSpan.FromSeconds(3));
                await api.Connect(timeout.Token);Verify(api);await api.Call("/status",token:timeout.Token);
                recovery.Healthy();return true;
            }catch(Exception e) when(e is HttpRequestException or TaskCanceledException or IOException){
                if(disposed)throw new ObjectDisposedException(nameof(OwnedBackend));
                if(!recovery.Failed(Now))throw new IOException("后台暂未响应，等待有限重连；未结束其他服务。",e);
                // This handle/job was created by this host, never inferred from a port/PID.
                job?.Dispose();job=null;
                if(!process.WaitForExit(3000)){
                    try{process.Kill(true);}catch(InvalidOperationException) when(process.HasExited){}
                    if(!process.WaitForExit(3000))throw new IOException("所属后台仍未退出，停止自动重启以避免重复服务。");
                }
                process.Dispose();process=null;recovery.Restarted(Now);
                await Connect(api);return true;
            }
        }finally{operation.Release();}
    }
    public async Task Shutdown(Api api){
        var owned=process;if(owned==null)return;
        await api.Call("/shutdown","POST",new{});
        // Acceptance precedes model/wallpaper cleanup. Keep the owned job alive
        // until that cleanup finishes; Dispose remains the bounded fallback.
        try{await owned.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(10));}catch(TimeoutException){}
    }
    public void Dispose(){if(disposed)return;disposed=true;job?.Dispose();process?.Dispose();job=null;process=null;}
}
