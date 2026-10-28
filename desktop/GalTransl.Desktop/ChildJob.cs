using System.Diagnostics;
using System.Runtime.InteropServices;

namespace GalTransl.Desktop;

// Kill only helper processes assigned by this client; never assign the game PID.
public sealed class ChildJob:IDisposable {
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern nint CreateJobObject(nint attrs,string? name);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool SetInformationJobObject(nint job,int cls,nint info,uint size);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool AssignProcessToJobObject(nint job,nint process);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(nint h);
    nint handle;
    public ChildJob(Process process){
        handle=CreateJobObject(0,null);if(handle==0)throw new System.ComponentModel.Win32Exception();
        var buffer=Marshal.AllocHGlobal(144);
        try{unsafe{new Span<byte>((void*)buffer,144).Clear();}Marshal.WriteInt32(buffer,16,0x2000);
            if(!SetInformationJobObject(handle,9,buffer,144)||!AssignProcessToJobObject(handle,process.Handle)){
                var error=Marshal.GetLastWin32Error();CloseHandle(handle);handle=0;throw new System.ComponentModel.Win32Exception(error);
            }
        }finally{Marshal.FreeHGlobal(buffer);}
    }
    public void Dispose(){if(handle!=0){CloseHandle(handle);handle=0;}}
}
