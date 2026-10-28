using System.Windows;
using System.Windows.Controls;
namespace GalTransl.Desktop;

// Explicit snapshot of the current sentence. No history fetch or caption writer.
public sealed class CurrentTextWindow:Window {
    public CurrentTextWindow(Caption caption,Profile profile){
        Title="当前句全文 · "+profile.Name;Width=680;Height=520;MinWidth=360;MinHeight=280;VisualTheme.Apply(this);
        var body=new StackPanel{Margin=new Thickness(24)};Content=new ScrollViewer{Content=body,VerticalScrollBarVisibility=ScrollBarVisibility.Auto};
        body.Children.Add(new TextBlock{Text="当前句全文",FontSize=22,FontWeight=FontWeights.SemiBold});
        body.Children.Add(new TextBlock{Text="打开时的当前台词 · 关闭后回到最新字幕",Foreground=VisualTheme.Brush(VisualTheme.Ink,.72),Margin=new Thickness(0,8,0,20)});
        body.Children.Add(new TextBlock{Text=caption.Ja,TextWrapping=TextWrapping.Wrap,FontSize=18,Foreground=VisualTheme.Brush(VisualTheme.Ink,.72)});
        body.Children.Add(new TextBlock{Text=caption.State is "final" or "streaming"?caption.Zh:caption.Reason??"本条尚未产生完整译文，原文已保留。",TextWrapping=TextWrapping.Wrap,FontSize=profile.Font,Margin=new Thickness(0,16,0,0)});
        PreviewKeyDown+=(_,e)=>{if(e.Key==System.Windows.Input.Key.Escape){e.Handled=true;Close();}};
    }
}
