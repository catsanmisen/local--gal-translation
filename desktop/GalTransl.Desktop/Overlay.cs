using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Media;

namespace GalTransl.Desktop;

public sealed class Overlay:Window {
    readonly Border panel=new(){CornerRadius=new CornerRadius(14),Padding=new Thickness(16,10,16,10),BorderThickness=new Thickness(1),BorderBrush=VisualTheme.Brush(VisualTheme.Ink,.12)};
    readonly TextBlock text=new(){Foreground=VisualTheme.Brush(VisualTheme.Ink),TextWrapping=TextWrapping.Wrap,FontWeight=FontWeights.Medium,
        Effect=new System.Windows.Media.Effects.DropShadowEffect{Color=VisualTheme.Base,BlurRadius=4,ShadowDepth=1,Opacity=.75}};
    readonly TextBlock state=new(){Foreground=VisualTheme.Brush(VisualTheme.Ink,.72),FontSize=12,MinHeight=28,TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,0,216,5)};
    readonly TextBlock hint=new(){Foreground=VisualTheme.Brush(VisualTheme.Ink,.72),FontSize=12,Text="安全空间不足 · 可主动查看当前句全文",Visibility=Visibility.Collapsed};
    readonly CaptionPlacement placement=new();
    readonly SingleInputListener singleInput=new();
    readonly OverlayControls controls;
    readonly bool verificationMode;
    public nint Handle {get;private set;}
    public bool Editing {get;private set;}
    public Action<double,double>? Moved {get;set;}
    public Action<int>? Hotkey {get;set;}
    public Action? MagpieChanged {get;set;}
    public Action? BacklogRequested {get;set;}
    public Action? PositionRequested {get;set;}
    public Action? CurrentTextRequested {get;set;}
    public string? HotkeyNotice {get;private set;}
    public string? PlacementNotice {get;private set;}
    public string? PlacementDescription {get;private set;}
    public bool ControlsFocused=>controls.HasFocus;
    public string? InputNotice=>singleInput.Notice;
    public Func<bool>? InputEnabled {get=>singleInput.Enabled;set=>singleInput.Enabled=value;}
    public Action? SingleInputRequested {get=>singleInput.Toggle;set=>singleInput.Toggle=value;}
    public void ConfigureInput(string value)=>singleInput.Configure(Handle,value);
    public void ResetPlacement()=>placement.Reset();
    PixelRect? placed,controlRect;double dragX,dragY;
    string captionState="idle";
    readonly uint message=Native.RegisterWindowMessage("MagpieScalingChanged");
    public Overlay(bool verification=false){
        verificationMode=verification;
        Title="GalTransl 实时字幕";WindowStyle=WindowStyle.None;AllowsTransparency=true;Background=Brushes.Transparent;
        ShowInTaskbar=verification;ShowActivated=false;Topmost=true;ResizeMode=ResizeMode.NoResize;SizeToContent=SizeToContent.Manual;
        FontFamily=new FontFamily("Microsoft YaHei UI");
        controls=new OverlayControls(verification){BacklogRequested=()=>BacklogRequested?.Invoke(),PositionRequested=()=>PositionRequested?.Invoke(),CurrentTextRequested=()=>CurrentTextRequested?.Invoke()};
        singleInput.OverControls=()=>controls.CursorOver;
        var stack=new StackPanel();stack.Children.Add(state);
        stack.Children.Add(new Border{Height=1,Background=VisualTheme.Brush(VisualTheme.Ink,.1),Margin=new Thickness(0,0,0,7)});
        stack.Children.Add(text);stack.Children.Add(hint);panel.Child=stack;Content=panel;
        Closed+=(_,_)=>{singleInput.Dispose();controls.Close();};
        SourceInitialized+=(_,_)=>{
            Handle=new WindowInteropHelper(this).Handle;
            // Keep the button strip above its caption throughout a topmost refresh.
            new WindowInteropHelper(controls).Owner=Handle;
            Native.ChangeWindowMessageFilterEx(Handle,message,1,0);
            if(!verification)Native.SetWindowDisplayAffinity(Handle,0x11);SetPassThrough(true);
            HwndSource.FromHwnd(Handle)?.AddHook(WndProc);
        };
        MouseLeftButtonDown+=(_,e)=>{if(!Editing)return;dragX=Left;dragY=Top;try{DragMove();}catch(InvalidOperationException){}Moved?.Invoke(Left-dragX,Top-dragY);};
    }
    nint WndProc(nint h,int msg,nint wp,nint lp,ref bool handled){
        if(msg==0x00ff)singleInput.Read(lp); // Leave unhandled for DefWindowProc cleanup.
        if(msg==0x0312){Hotkey?.Invoke((int)wp);handled=true;}
        if(msg==message)MagpieChanged?.Invoke();return 0;
    }
    public void ConfigureHotkeys(Dictionary<string,string> config){
        HotkeyNotice=null;var names=new[]{"visibility","pause","reset","backlog"};
        for(var i=0;i<4;i++){
            Native.UnregisterHotKey(Handle,i+1);var value=config.GetValueOrDefault(names[i],new[]{"Ctrl+Shift+H","Ctrl+Shift+P","Ctrl+Shift+R","Ctrl+Shift+B"}[i]);
            var parts=value.Split('+');uint mods=0x4000;uint key=0;
            foreach(var p in parts.Select(p=>p.Trim().ToUpperInvariant())){
                if(p=="CTRL")mods|=2;else if(p=="SHIFT")mods|=4;else if(p=="ALT")mods|=1;else if(p=="WIN")mods|=8;
                else if(p.Length==1 && char.IsAsciiLetterOrDigit(p[0]))key=p[0];
                else if(p.StartsWith('F') && int.TryParse(p[1..],out var f)&&f is >=1 and <=12)key=(uint)(111+f);
            }
            if(key==0 || !Native.RegisterHotKey(Handle,i+1,mods,key))HotkeyNotice="快捷键冲突或无效："+value+"；可在游戏设置中修改。";
        }
    }
    public void SetPassThrough(bool on){
        if(Handle==0)return;var style=(long)Native.GetWindowLongPtr(Handle,-20);
        style|=0x08000000;style=verificationMode?style&~0x80:style|0x80;style=on?style|0x20:style&~0x20;
        Native.SetWindowLongPtr(Handle,-20,(nint)style);
    }
    public void Edit(bool on){Editing=on;SetPassThrough(!on);state.Text=on?"拖动调整位置 · 从托盘结束编辑":"";}
    public void Caption(Caption caption,Profile profile,string? notice){
        captionState=caption.State;
        text.FontSize=profile.Font;panel.Background=new LinearGradientBrush(VisualTheme.Brush(VisualTheme.Surface,profile.Opacity).Color,
            VisualTheme.Brush(VisualTheme.Base,profile.Opacity).Color,new Point(0,0),new Point(0,.28));
        text.Text=caption.State is "final" or "streaming"?caption.Zh:"";
        state.Text=Editing?"拖动调整位置 · 从托盘结束编辑":caption.State switch {
            "final"=>"实时翻译", "streaming"=>"翻译中…", "capturing"=>"正在读取台词…", "paused"=>"采集已暂停",
            "error"=>caption.Reason??"本条未完成，原文已保存", "cancelled"=>"",_=>notice??"等待台词"};
        if(!string.IsNullOrEmpty(notice)&&caption.State!="error"&&(caption.State!="streaming"||caption.Zh.Length==0))state.Text=notice;
    }
    public bool Place(GameWindow window,Profile profile,Region? recognized=null,Region? avoid=null){
        PlacementNotice=null;controlRect=null;
        if(Editing&&placed!=null){
            var current=Native.WindowRect(Handle);var scale=Math.Max(96,Native.GetDpiForWindow(Handle))/96.0;
            controlRect=new(current.Right-220*scale,current.Y+8*scale,212*scale,32*scale);return true;
        }
        if(profile.Game.Region is not Region roi){placed=null;return false;}
        var cr=Native.ClientRect(window.Handle);var box=cr.Region(roi);var textBox=recognized is null?box:cr.Region(recognized);var bounds=cr;
        PixelRect? dialogue=profile.Game.DialogueBox is Region container?cr.Region(container):null;
        PixelRect? protectedText=avoid is null?null:cr.Region(avoid);
        if(Native.Magpie(window.Handle) is Native.Scaling scaling){box=Native.Map(box,scaling.Src,scaling.Dest);textBox=Native.Map(textBox,scaling.Src,scaling.Dest);bounds=scaling.Dest;if(protectedText is PixelRect protectedBox)protectedText=Native.Map(protectedBox,scaling.Src,scaling.Dest);if(dialogue is PixelRect d)dialogue=Native.Map(d,scaling.Src,scaling.Dest);}
        // Old games can be DPI-unaware and always report 96. Use the native
        // caption's DPI; WPF updates it when this window follows another screen.
        var dpi=Math.Max(96,Native.GetDpiForWindow(Handle))/96.0;
        var source=protectedText is PixelRect all?CaptionLayout.Union(textBox,all):textBox;
        var work=Native.WorkArea(bounds);var frame=Native.Magpie(window.Handle)?.Dest??Native.WindowRect(window.Handle);
        var slots=CaptionLayout.Candidates(bounds,work,source,box,profile.Game.SubtitlePlacement,dpi,frame,dialogue:dialogue);
        if(slots.Count==0){
            placed=null;placement.Reset();PlacementDescription=null;PlacementNotice="当前文字演出没有安全字幕空间；可用托盘查看当前句全文或调整位置。";
            var dock=CaptionLayout.Candidates(bounds,work,source,box,profile.Game.SubtitlePlacement,dpi,frame,controlsOnly:true,dialogue:dialogue).FirstOrDefault();
            if(dock!=null)controlRect=dock.Fit(32*dpi,0,0);return false;
        }
        panel.MaxHeight=text.MaxHeight=double.PositiveInfinity;hint.Visibility=Visibility.Collapsed;
        double Measure(CaptionLayout.Slot slot){panel.Measure(new Size(slot.Width/dpi,double.PositiveInfinity));return Math.Max(92*dpi,panel.DesiredSize.Height*dpi);}
        var measured=slots.Select(s=>(Slot:s,Height:Measure(s))).ToList();
        var policy=profile.Id+"/"+profile.Game.SubtitlePlacement+"/"+profile.Game.DialogueBox+"/"+profile.Game.Anchor.Dx+"/"+profile.Game.Anchor.Dy;
        var chosen=placement.Select(measured,bounds,dpi,policy,profile.Game.Anchor.Dx*bounds.Width,profile.Game.Anchor.Dy*bounds.Height)!;Measure(chosen.Slot);
        var clipped=chosen.Clipped;
        hint.Visibility=clipped&&captionState=="final"?Visibility.Visible:Visibility.Collapsed;
        var rect=chosen.Rect;
        Width=rect.Width/dpi;MaxHeight=rect.Height/dpi;Height=rect.Height/dpi;
        panel.MaxHeight=Height;panel.ClipToBounds=true;
        text.MaxHeight=Math.Max(0,Height-30-state.DesiredSize.Height-state.Margin.Top-state.Margin.Bottom-(hint.Visibility==Visibility.Visible?20:0));text.ClipToBounds=true;
        PlacementDescription=(chosen.Slot.InDialogue?"对话框内 · ":"")+CaptionLayout.Label(chosen.Slot.Side,chosen.Slot.Outside);placed=rect;
        controlRect=new(rect.Right-220*dpi,rect.Y+8*dpi,212*dpi,32*dpi);
        Native.SetWindowPos(Handle,-1,(int)Math.Round(rect.X),(int)Math.Round(rect.Y),(int)Math.Ceiling(rect.Width),(int)Math.Ceiling(rect.Height),0x10);return true;
    }
    public void Present(bool body){
        if(body){if(!IsVisible)Show();}else Hide();
        if(controlRect is PixelRect dock)controls.Place(dock);else controls.Hide();
    }
    public void HideAll(){Hide();controls.Hide();}
    public void DisposeHotkeys(){singleInput.Dispose();for(int i=1;i<=4;i++)Native.UnregisterHotKey(Handle,i);controls.Close();}
}
