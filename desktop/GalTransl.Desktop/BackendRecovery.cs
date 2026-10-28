namespace GalTransl.Desktop;

// A transport timeout never authorizes killing an unrelated process.
// Owned backends require three consecutive failures over at least one minute.
public sealed class BackendRecovery {
    int failures;double? firstFailure;readonly Queue<double> restarts=new();
    public void Healthy(){failures=0;firstFailure=null;}
    public bool Failed(double now){
        firstFailure??=now;failures++;
        while(restarts.Count>0&&now-restarts.Peek()>=600)restarts.Dequeue();
        return failures>=3&&now-firstFailure.Value>=60&&restarts.Count<2;
    }
    public void Restarted(double now){restarts.Enqueue(now);Healthy();}
}
