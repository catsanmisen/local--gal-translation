namespace GalTransl.Desktop;

public static class InstanceExit {
    // A shutdown command is complete only when the former host releases its
    // instance mutex. A dying owner abandons the mutex; that still means exit.
    public static bool Wait(Mutex instance,TimeSpan timeout){
        bool acquired;
        try{acquired=instance.WaitOne(timeout);}catch(AbandonedMutexException){acquired=true;}
        if(acquired)instance.ReleaseMutex();
        return acquired;
    }
}
