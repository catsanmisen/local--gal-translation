using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using GalTransl.Desktop;

static class Program {
    [DllImport("user32.dll")] static extern nint GetWindow(nint window,uint command);
    static bool Above(nint upper,nint lower){
        for(var h=GetWindow(lower,3);h!=0;h=GetWindow(h,3))if(h==upper)return true;
        return false;
    }
    [STAThread] static int Main(){
        var app=new Application{ShutdownMode=ShutdownMode.OnExplicitShutdown};
        var foreground=Native.GetForegroundWindow();var checks=0;var failed=0;
        void Check(bool ok,string label){checks++;if(!ok)failed++;Console.WriteLine($"{(ok?"PASS":"FAIL")} {label}");}
        // Exercise real HWND ordering without displaying UI or taking focus.
        var game=new Window{Left=80,Top=80,Width=1280,Height=720,Opacity=0,ShowActivated=false,ShowInTaskbar=false,WindowStyle=WindowStyle.None};
        var overlay=new Overlay{Opacity=0};
        var controls=app.Windows.OfType<OverlayControls>().Single();controls.Opacity=0;
        try{
            game.Show();overlay.Show();
            var hwnd=new WindowInteropHelper(game).Handle;
            var buttons=new WindowInteropHelper(controls);
            var window=new GameWindow(hwnd,Environment.ProcessId,"test.exe","test",Native.ClientRect(hwnd));
            var profile=new Profile{Id="test",Game=new(){Region=new(.1,.7,.8,.18)}};
            var caption=new Caption("テスト","测试字幕","final","test",1,1,null,null);
            bool Place(){overlay.Caption(caption,profile,null);return overlay.Place(window,profile);}
            overlay.Present(Place());
            Check(overlay.IsVisible&&controls.IsVisible&&Above(buttons.Handle,overlay.Handle),"buttons initially appear above the caption");
            var occluded=0;
            for(var i=0;i<25;i++){
                var body=Place();
                if(!Above(buttons.Handle,overlay.Handle))occluded++;
                overlay.Present(body);
            }
            Console.WriteLine($"caption-over-button intervals: {occluded}/25");
            Check(occluded==0,"polling never raises the caption over visible buttons, even between Place and Present");
            Check(Above(buttons.Handle,overlay.Handle),"buttons stay above the caption after refresh");
            overlay.Present(false);
            Check(!overlay.IsVisible&&controls.IsVisible,"button-only fallback remains available");
            overlay.Present(Place());
            Check(overlay.IsVisible&&Above(buttons.Handle,overlay.Handle),"restoring the caption keeps visible fallback buttons above it");
            overlay.HideAll();overlay.Present(Place());
            Check(overlay.IsVisible&&controls.IsVisible&&Above(buttons.Handle,overlay.Handle),"hide and restore preserve button stacking");
            Check(((long)Native.GetWindowLongPtr(overlay.Handle,-20)&0x20)!=0&&((long)Native.GetWindowLongPtr(buttons.Handle,-20)&0x20)==0,"caption retains its pass-through style; buttons do not acquire that style");
            Check(((long)Native.GetWindowLongPtr(overlay.Handle,-20)&8)!=0&&((long)Native.GetWindowLongPtr(buttons.Handle,-20)&8)!=0,"both windows remain topmost");
            Check(Native.GetForegroundWindow()==foreground,"window refresh does not take foreground focus");
        }finally{overlay.Close();game.Close();app.Shutdown();}
        Console.WriteLine($"{checks} window checks, {failed} failed");return failed==0?0:1;
    }
}
