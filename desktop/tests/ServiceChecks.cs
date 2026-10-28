using System.Net;
using System.Net.Sockets;
using GalTransl.Desktop;
static class ServiceChecks {
    public static async Task Run(Action<bool,string> check,string root){
        var reservation=new TcpListener(IPAddress.Loopback,0);reservation.Start();var port=((IPEndPoint)reservation.LocalEndpoint).Port;reservation.Stop();
        var folder=Path.Combine(root,"work","service-check-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(folder);
        double clock=0;using var api=new Api(port);var owned=new OwnedBackend(root,port,Path.Combine(folder,"client.sqlite3"),()=>clock,TimeSpan.FromMilliseconds(300));
        try{
            await owned.Connect(api);check(owned.Owns,"headless host owns only its newly created backend");
            var firstInstance=api.InstanceId;
            using(var otherApi=new Api(port))using(var wrongData=new OwnedBackend(root,port,Path.Combine(folder,"other.sqlite3"))){
                var refused=false;try{await wrongData.Connect(otherApi);}catch(BackendCompatibilityException){refused=true;}
                check(refused&&!wrongData.Owns,"same protocol with another database is refused without owning or killing it");
            }
            check((await api.Call("/status")).GetProperty("state").GetString()=="stopped","identity refusal leaves the original service and data alive");
            var status=await api.Call("/status");check(status.GetProperty("state").GetString()=="stopped","isolated backend smoke never starts the model or games");
            await api.Call("/shutdown","POST",new{});
            for(int i=0;i<40;i++){await Task.Delay(100);try{await api.Call("/status");}catch(HttpRequestException){break;}}
            check(await owned.Recover(api),"owned backend reconnects after termination with a new token");
            check(api.InstanceId!=firstInstance,"restarted backend exposes a different lifetime identity");
            status=await api.Call("/status");check(status.GetProperty("state").GetString()=="stopped","recovered backend stays idle until an explicit game bind");
            var hung=owned.OwnedProcessId!.Value;var healthyInstance=api.InstanceId;
            OwnedProcessFault.Suspend(hung);
            try{
                for(int i=0;i<2;i++){
                    clock=i*30;var pending=false;try{await owned.Recover(api);}catch(IOException){pending=true;}
                    check(pending&&owned.OwnedProcessId==hung,"transient live timeout retains the original owned process");
                }
                clock=60;check(await owned.Recover(api)&&owned.OwnedProcessId!=hung,"three prolonged timeouts recycle only the suspended owned backend");
                check(api.InstanceId!=healthyInstance&&(await api.Call("/status")).GetProperty("state").GetString()=="stopped","recycled live backend exposes a fresh identity and stays idle");
            }finally{OwnedProcessFault.Resume(hung);}
            using var exiting=System.Diagnostics.Process.GetProcessById(owned.OwnedProcessId!.Value);
            await owned.Shutdown(api);
            check(exiting.HasExited,"normal shutdown waits for backend cleanup before its job is closed");
        }finally{owned.Dispose();owned.Dispose();}
        await Task.Delay(200);var gone=false;try{await api.Call("/status");}catch(HttpRequestException){gone=true;}
        check(gone,"idempotent owned disposal releases the isolated backend port");
    }
}
