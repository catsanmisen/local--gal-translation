using System.Diagnostics;
using System.Runtime.InteropServices;
static class OwnedProcessFault {
    [DllImport("kernel32.dll",SetLastError=true)] static extern nint OpenThread(uint access,bool inherit,uint id);
    [DllImport("kernel32.dll")] static extern uint SuspendThread(nint handle);
    [DllImport("kernel32.dll")] static extern uint ResumeThread(nint handle);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(nint handle);
    // Caller supplies only the PID returned by the isolated OwnedBackend fixture.
    public static void Suspend(int pid){using var process=Process.GetProcessById(pid);foreach(ProcessThread thread in process.Threads){
        var handle=OpenThread(2,false,(uint)thread.Id);if(handle==0)throw new System.ComponentModel.Win32Exception();
        try{if(SuspendThread(handle)==uint.MaxValue)throw new System.ComponentModel.Win32Exception();}finally{CloseHandle(handle);}
    }}
    public static void Resume(int pid){try{using var process=Process.GetProcessById(pid);foreach(ProcessThread thread in process.Threads){
        var handle=OpenThread(2,false,(uint)thread.Id);if(handle==0)continue;try{ResumeThread(handle);}finally{CloseHandle(handle);}
    }}catch(ArgumentException){}}
}
