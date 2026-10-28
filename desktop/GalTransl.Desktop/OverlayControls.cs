using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Media;

namespace GalTransl.Desktop;

// Only this 156 x 32 DIP companion receives clicks. The caption body retains
// WS_EX_TRANSPARENT; MA_NOACTIVATE keeps a normal button click in the game.
public sealed class OverlayControls:Window {
    nint handle;
    readonly bool verification;
    public Action? BacklogRequested {get;set;}
    public Action? PositionRequested {get;set;}
    public Action? CurrentTextRequested {get;set;}
    public bool HasFocus=>handle!=0&&IsVisible&&Native.GetForegroundWindow()==handle;
    public bool CursorOver=>handle!=0&&IsVisible&&Native.CursorInside(Native.WindowRect(handle));
    public OverlayControls(bool verification){
        this.verification=verification;
        Title="GalTransl 字幕操作";Width=212;Height=32;WindowStyle=WindowStyle.None;
        AllowsTransparency=true;Background=Brushes.Transparent;ShowInTaskbar=verification;ShowActivated=false;
        Topmost=true;ResizeMode=ResizeMode.NoResize;FontFamily=new FontFamily("Microsoft YaHei UI");
        var row=new Grid();row.ColumnDefinitions.Add(new(){Width=new GridLength(88)});row.ColumnDefinitions.Add(new(){Width=new GridLength(60)});row.ColumnDefinitions.Add(new(){Width=new GridLength(64)});
        var history=Make("Backlog","主动查看历史翻译，关闭后返回当前台词",()=>BacklogRequested?.Invoke());
        var position=Make("位置","选择摆放方向、拖动或隐藏字幕",()=>PositionRequested?.Invoke());
        row.Children.Add(history);Grid.SetColumn(position,1);row.Children.Add(position);Content=row;
        var full=Make("全文","只查看当前台词全文，不打开历史",()=>CurrentTextRequested?.Invoke());Grid.SetColumn(full,2);row.Children.Add(full);
        SourceInitialized+=(_,_)=>{
            handle=new WindowInteropHelper(this).Handle;
            var style=(long)Native.GetWindowLongPtr(handle,-20)|0x08000000;
            style=this.verification?style&~0x80:style|0x80;Native.SetWindowLongPtr(handle,-20,(nint)style);
            if(!this.verification)Native.SetWindowDisplayAffinity(handle,0x11);
            HwndSource.FromHwnd(handle)?.AddHook((nint h,int msg,nint wp,nint lp,ref bool handled)=>{
                if(msg==0x0021){handled=true;return 3;}return 0;
            });
        };
    }
    static Button Make(string label,string help,Action action){
        var b=new Button{Content=label,FontSize=12,Focusable=false,Padding=new Thickness(6,2,6,2),
            Background=VisualTheme.Brush(VisualTheme.Surface,.6),Foreground=VisualTheme.Brush(VisualTheme.Ink),
            BorderBrush=VisualTheme.Brush(VisualTheme.Surface),BorderThickness=new Thickness(1)};
        System.Windows.Automation.AutomationProperties.SetName(b,label=="Backlog"?"打开历史翻译 Backlog":label=="全文"?"当前句全文":"调整字幕位置");
        System.Windows.Automation.AutomationProperties.SetHelpText(b,help);
        ButtonChrome.Apply(b);
        b.Click+=(_,_)=>action();return b;
    }
    public void Place(PixelRect pixels){
        if(handle==0){Show();Hide();}
        // A popup button strip follows the physical caption rectangle even
        // across monitors; dimensions use the caption's current DPI scale.
        if(!IsVisible)Show();
        Native.SetWindowPos(handle,-1,(int)Math.Round(pixels.X),(int)Math.Round(pixels.Y),
            (int)Math.Ceiling(pixels.Width),(int)Math.Ceiling(pixels.Height),0x10);
    }
}
