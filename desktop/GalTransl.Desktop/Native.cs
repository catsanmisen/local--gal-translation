using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

namespace GalTransl.Desktop;

public static class Native {
    [StructLayout(LayoutKind.Sequential)] public struct RECT {public int Left,Top,Right,Bottom;public readonly PixelRect Rect=>new(Left,Top,Right-Left,Bottom-Top);}
    [StructLayout(LayoutKind.Sequential)] public struct POINT {public int X,Y;}
    [StructLayout(LayoutKind.Sequential)] struct MONITORINFO {public uint Size;public RECT Monitor,Work;public uint Flags;}
    delegate bool EnumCallback(nint h,nint l);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumCallback callback,nint l);
    [DllImport("user32.dll")] public static extern bool IsWindow(nint h);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(nint h);
    [DllImport("user32.dll")] public static extern bool IsIconic(nint h);
    [DllImport("user32.dll")] static extern bool GetClientRect(nint h,out RECT r);
    [DllImport("user32.dll")] static extern bool GetWindowRect(nint h,out RECT r);
    [DllImport("dwmapi.dll")] static extern int DwmGetWindowAttribute(nint h,uint attribute,out RECT r,uint size);
    [DllImport("user32.dll")] static extern bool ClientToScreen(nint h,ref POINT p);
    [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetWindowText(nint h,StringBuilder b,int max);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(nint h,out uint pid);
    [DllImport("user32.dll")] public static extern nint GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(nint window);
    [DllImport("user32.dll")] static extern short GetAsyncKeyState(int key);
    [DllImport("user32.dll")] static extern bool GetCursorPos(out POINT point);
    public static bool ModifiersPressed()=>new[]{16,17,18,91,92}.Any(k=>(GetAsyncKeyState(k)&0x8000)!=0);
    public static bool KeyPressed(int key)=>(GetAsyncKeyState(key)&0x8000)!=0;
    public static bool CursorInside(PixelRect rect)=>GetCursorPos(out var point)&&point.X>=rect.X&&point.X<rect.Right&&point.Y>=rect.Y&&point.Y<rect.Bottom;
    [DllImport("user32.dll")] public static extern uint GetDpiForWindow(nint h);
    [DllImport("user32.dll")] static extern nint MonitorFromRect(ref RECT rect,uint flags);
    [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern bool GetMonitorInfo(nint monitor,ref MONITORINFO info);
    [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern uint RegisterWindowMessage(string name);
    [DllImport("user32.dll")] public static extern bool ChangeWindowMessageFilterEx(nint h,uint message,uint action,nint filter);
    [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern nint FindWindow(string cls,string? title);
    [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern nint GetProp(nint h,string name);
    [DllImport("user32.dll")] public static extern nint GetWindowLongPtr(nint h,int index);
    [DllImport("user32.dll")] public static extern nint SetWindowLongPtr(nint h,int index,nint value);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(nint h,nint after,int x,int y,int width,int height,uint flags);
    [DllImport("user32.dll")] public static extern bool SetWindowDisplayAffinity(nint h,uint affinity);
    [DllImport("user32.dll")] public static extern bool RegisterHotKey(nint h,int id,uint mods,uint key);
    [DllImport("user32.dll")] public static extern bool UnregisterHotKey(nint h,int id);
    [DllImport("kernel32.dll")] static extern nint OpenProcess(uint access,bool inherit,uint pid);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode)] static extern bool QueryFullProcessImageName(nint p,uint flags,StringBuilder b,ref uint size);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(nint p);
    [DllImport("kernel32.dll")] static extern bool IsWow64Process(nint p,out bool wow);
    public static PixelRect ClientRect(nint h){GetClientRect(h,out var r);var p=new POINT();ClientToScreen(h,ref p);return new(p.X,p.Y,r.Right-r.Left,r.Bottom-r.Top);}
    public static PixelRect WindowRect(nint h){if(DwmGetWindowAttribute(h,9,out var r,16)==0)return r.Rect;GetWindowRect(h,out r);return r.Rect;}
    public static PixelRect WorkArea(PixelRect bounds){
        var r=new RECT{Left=(int)bounds.X,Top=(int)bounds.Y,Right=(int)bounds.Right,Bottom=(int)bounds.Bottom};
        var info=new MONITORINFO{Size=(uint)Marshal.SizeOf<MONITORINFO>()};
        return GetMonitorInfo(MonitorFromRect(ref r,2),ref info)?info.Work.Rect:bounds;
    }
    public static string? Executable(uint pid){var h=OpenProcess(0x1000,false,pid);if(h==0)return null;try{var s=new StringBuilder(2048);uint n=2048;return QueryFullProcessImageName(h,0,s,ref n)?s.ToString():null;}finally{CloseHandle(h);}}
    public static bool Is32(int pid){var h=OpenProcess(0x1000,false,(uint)pid);if(h==0)throw new InvalidOperationException("无法读取游戏进程位数");try{return IsWow64Process(h,out var wow)&&wow;}finally{CloseHandle(h);}}
    public static List<GameWindow> Windows(){
        var result=new List<GameWindow>();
        EnumWindows((h,l)=>{
            if(!IsWindowVisible(h))return true;
            var title=new StringBuilder(512);GetWindowText(h,title,512);if(title.Length==0)return true;
            GetWindowThreadProcessId(h,out var pid);var exe=Executable(pid);var rect=ClientRect(h);
            if(exe!=null && rect.Width>150 && rect.Height>100 && pid!=Environment.ProcessId)result.Add(new(h,(int)pid,exe,title.ToString(),rect));
            return true;
        },0);return result;
    }
    public const string MagpieClass="Window_Magpie_967EB565-6F73-4E94-AE53-00CC42592A22";
    public sealed record Scaling(nint Window,nint Source,PixelRect Src,PixelRect Dest);
    public static Scaling? Magpie(nint source){
        var h=FindWindow(MagpieClass,null);if(h==0||!IsWindowVisible(h))return null;
        var src=GetProp(h,"Magpie.SrcHWND");if(src!=source)return null;
        int P(string key)=>unchecked((int)GetProp(h,"Magpie."+key));
        var sr=new PixelRect(P("SrcLeft"),P("SrcTop"),P("SrcRight")-P("SrcLeft"),P("SrcBottom")-P("SrcTop"));
        var dr=new PixelRect(P("DestLeft"),P("DestTop"),P("DestRight")-P("DestLeft"),P("DestBottom")-P("DestTop"));
        return sr.Width>0&&sr.Height>0&&dr.Width>0&&dr.Height>0?new(h,src,sr,dr):null;
    }
    public static PixelRect Map(PixelRect value,PixelRect source,PixelRect dest)=>new(
        dest.X+(value.X-source.X)*dest.Width/source.Width,dest.Y+(value.Y-source.Y)*dest.Height/source.Height,
        value.Width*dest.Width/source.Width,value.Height*dest.Height/source.Height);
    public static bool Focused(GameWindow w)=>!IsIconic(w.Handle) &&
        (GetForegroundWindow()==w.Handle || (Magpie(w.Handle) is Scaling m&&GetForegroundWindow()==m.Window));
}
