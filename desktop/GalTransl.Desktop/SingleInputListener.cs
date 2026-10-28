using System.Runtime.InteropServices;

namespace GalTransl.Desktop;

// RIDEV_INPUTSINK observes input without RIDEV_NOLEGACY: the game receives
// its normal click/key. Registers only the chosen device class while bound.
public sealed class SingleInputListener:IDisposable {
    [StructLayout(LayoutKind.Sequential)] struct Device {public ushort Page,Usage;public uint Flags;public nint Window;}
    [StructLayout(LayoutKind.Sequential)] struct Header {public uint Type,Size;public nint Device,Param;}
    [DllImport("user32.dll",SetLastError=true)] static extern bool RegisterRawInputDevices([In] Device[] devices,uint count,uint size);
    [DllImport("user32.dll")] static extern uint GetRawInputData(nint handle,uint command,nint data,ref uint size,uint headerSize);
    readonly SingleInputGate gate=new();ushort usage;string value="none";
    public Func<bool>? Enabled {get;set;}
    public Func<bool>? OverControls {get;set;}
    public Action? Toggle {get;set;}
    public string? Notice {get;private set;}
    public void Configure(nint window,string choice){
        if(value==choice)return;Unregister();Notice=null;value=choice;gate.Configure(choice);
        if(choice=="none")return;
        var key=choice switch{"mouse_left"=>1,"mouse_right"=>2,"mouse_middle"=>4,_=>Enumerable.Range(0,256).FirstOrDefault(k=>SingleInputGate.Key(k)==choice)};
        if(key!=0&&Native.KeyPressed(key))gate.Observe(choice,true,false); // Ignore an already-held input until release.
        var next=(ushort)(choice.StartsWith("mouse_",StringComparison.Ordinal)?2:6);
        if(!RegisterRawInputDevices([new(){Page=1,Usage=next,Flags=0x100,Window=window}],1,(uint)Marshal.SizeOf<Device>())){
            Notice="单键隐藏暂不可用，可继续使用托盘或显示快捷键。";return;
        }
        usage=next;
    }
    public void Read(nint input){
        if(usage==0)return;uint size=0;var headerSize=(uint)Marshal.SizeOf<Header>();
        if(GetRawInputData(input,0x10000003,0,ref size,headerSize)==uint.MaxValue||size<headerSize||size>4096)return;
        var data=Marshal.AllocHGlobal((int)size);
        try{
            if(GetRawInputData(input,0x10000003,data,ref size,headerSize)!=size)return;
            var header=Marshal.PtrToStructure<Header>(data);var body=data+(int)headerSize;
            bool Observe(string? token,bool pressed,bool mouse=false)=>token!=null&&gate.Observe(token,pressed,Enabled?.Invoke()==true,
                Native.ModifiersPressed(),mouse&&OverControls?.Invoke()==true);
            var toggle=false;
            if(header.Type==0&&usage==2&&size>=headerSize+24){
                var flags=(ushort)Marshal.ReadInt16(body,4);
                foreach(var (name,down,up) in new[]{("mouse_left",1,2),("mouse_right",4,8),("mouse_middle",16,32)}){
                    if((flags&down)!=0)toggle|=Observe(name,true,true);if((flags&up)!=0)Observe(name,false,true);
                }
            }else if(header.Type==1&&usage==6&&size>=headerSize+16){
                var flags=(ushort)Marshal.ReadInt16(body,2);var key=(ushort)Marshal.ReadInt16(body,6);
                toggle=Observe(SingleInputGate.Key(key),(flags&1)==0);
            }
            if(toggle)Toggle?.Invoke();
        }finally{Marshal.FreeHGlobal(data);}
    }
    void Unregister(){if(usage!=0){RegisterRawInputDevices([new(){Page=1,Usage=usage,Flags=1,Window=0}],1,(uint)Marshal.SizeOf<Device>());usage=0;}}
    public void Dispose(){Unregister();value="none";gate.Configure("none");}
}
