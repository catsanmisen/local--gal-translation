using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace GalTransl.Desktop;

// Explicit settings surface, never created by OCR or incoming translations.
public sealed class PositionWindow:Window {
    public PositionWindow(Coordinator host,Profile profile){
        Title="字幕摆放 · "+profile.Name;Width=560;SizeToContent=SizeToContent.Height;MaxHeight=Math.Max(400,Math.Min(860,SystemParameters.WorkArea.Height-80));ResizeMode=ResizeMode.NoResize;
        VisualTheme.Apply(this);FontSize=14;
        var root=new StackPanel{Margin=new Thickness(24)};Content=new ScrollViewer{Content=root,VerticalScrollBarVisibility=ScrollBarVisibility.Auto};
        root.Children.Add(new TextBlock{Text="给原文留出空间",FontSize=23,FontWeight=FontWeights.SemiBold});
        root.Children.Add(new TextBlock{Text="保留仍然安全的位置，减少台词切换时的上下跳动。可以框选整个游戏内对话框，优先在其空白处放译文；原文没有空隙时再向外避让。",TextWrapping=TextWrapping.Wrap,Foreground=VisualTheme.Brush(VisualTheme.Ink,.72),Margin=new Thickness(0,10,0,16)});
        var labels=new[]{"自动避让","优先原文上方","优先原文下方","优先原文左侧","优先原文右侧","优先游戏外侧"};
        var choices=new ComboBox{ItemsSource=labels,SelectedIndex=Math.Max(0,Array.IndexOf(CaptionLayout.Modes,profile.Game.SubtitlePlacement)),Padding=new Thickness(8)};
        System.Windows.Automation.AutomationProperties.SetName(choices,"字幕摆放方向");root.Children.Add(choices);
        var message=new TextBlock{Foreground=VisualTheme.Brush(VisualTheme.Ink,.72),TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,12,0,0)};root.Children.Add(message);
        void Button(string label,Func<Task> action){
            var b=new Button{Content=label,Padding=new Thickness(12,7,12,7),HorizontalAlignment=HorizontalAlignment.Left,Margin=new Thickness(0,10,0,0),
                BorderThickness=new Thickness(1)};
            ButtonChrome.Apply(b);
            b.Click+=async(_,_)=>{b.IsEnabled=false;try{await action();}catch(Exception e){message.Text=e.Message;}finally{b.IsEnabled=true;}};root.Children.Add(b);
        }
        Button("保存摆放方向",async()=>{await host.SetPlacement(profile,CaptionLayout.Modes[choices.SelectedIndex]);message.Text="已按此游戏保存。安全空间不足时会改选其他方向；所有方向都不足则收起正文。";});
        Button(host.Overlay.Editing?"结束拖动调整":"拖动调整位置",()=>{if(host.CurrentProfile?.Id!=profile.Id)throw new InvalidOperationException("请回到该游戏后调整位置。");
            host.Overlay.Edit(!host.Overlay.Editing);host.RefreshOverlay();Close();return Task.CompletedTask;});
        Button("恢复自动位置",async()=>{await host.SetPlacement(profile,"auto",resetOffset:true);choices.SelectedIndex=0;message.Text="已恢复自动避让，并清除拖动偏移。";});
        Button("框选游戏内整个对话框",async()=>{
            if(host.CurrentProfile?.Id!=profile.Id||host.Current is not GameWindow game)throw new InvalidOperationException("请回到该游戏后框选对话框。");
            var picked=RegionPicker.Pick(game,true);if(picked!=null){await host.SetDialogueBox(profile,picked);message.Text="已记住整个对话框。译文优先放在框内安全空隙，不会盖住原文；取词区域保持不变。";}
        });
        Button("清除固定对话框",async()=>{await host.SetDialogueBox(profile,null);message.Text="已取消对话框范围，继续使用稳定避让。";});
        Button("框选特殊文字备用取词区域",async()=>{
            if(host.CurrentProfile?.Id!=profile.Id||host.Current is not GameWindow game)throw new InvalidOperationException("请先连接此游戏。");
            var picked=RegionPicker.Pick(game);if(picked!=null){await host.SetSpecialRegion(profile,picked);message.Text="备用区域已保存；常规区域持续为空时自动切换，不同时提交两条翻译。";}
        });
        Button("清除备用取词区域",async()=>{await host.SetSpecialRegion(profile,null);message.Text="已恢复单区域取词。";});
        Button("查看当前句全文",()=>{host.ShowCurrentText();return Task.CompletedTask;});
        root.Children.Add(new TextBlock{Text="单次输入 · 隐藏 / 恢复",FontSize=17,FontWeight=FontWeights.SemiBold,Margin=new Thickness(0,22,0,8)});
        var input=new ComboBox{ItemsSource=SingleInputGate.Choices,DisplayMemberPath="Label",SelectedValuePath="Value",SelectedValue=profile.Game.HideInput};
        System.Windows.Automation.AutomationProperties.SetName(input,"单键隐藏输入");root.Children.Add(input);
        root.Children.Add(new TextBlock{Text="仅在此游戏前台时生效。按一次隐藏，再按一次恢复；按键或点击仍交给游戏，可能同时推进台词或打开游戏菜单。点击 Backlog / 位置不会触发隐藏。",TextWrapping=TextWrapping.Wrap,Foreground=VisualTheme.Brush(VisualTheme.Ink,.72),Margin=new Thickness(0,8,0,0)});
        Button("保存单键隐藏",async()=>{await host.SetHideInput(profile,input.SelectedValue as string??"none");message.Text=host.Overlay.InputNotice??"单键设置已按游戏保存。";});
        root.Children.Add(new TextBlock{Text="底衬不透明度 · 文字保持清晰",FontSize=17,FontWeight=FontWeights.SemiBold,Margin=new Thickness(0,22,0,8)});
        var opacity=new TextBox{Text=Math.Round(profile.Opacity*100).ToString(),MaxLength=3,Width=100,Padding=new Thickness(8),HorizontalAlignment=HorizontalAlignment.Left};
        System.Windows.Automation.AutomationProperties.SetName(opacity,"字幕底衬不透明度，20至100百分比");root.Children.Add(opacity);
        root.Children.Add(new TextBlock{Text="20–100%，数字越小，底衬越透明。",Foreground=VisualTheme.Brush(VisualTheme.Ink,.72),Margin=new Thickness(0,6,0,0)});
        Button("保存透明度",async()=>{if(!int.TryParse(opacity.Text,out var alpha)||alpha<20||alpha>100)throw new InvalidOperationException("请输入20至100之间的整数百分比。");await host.SetOpacity(profile,alpha);message.Text="底衬已更新，文字不透明度保持不变。";});
        Button("暂时隐藏字幕",()=>{host.HideOverlay();Close();return Task.CompletedTask;});
        PreviewKeyDown+=(_,e)=>{if(e.Key==System.Windows.Input.Key.Escape){e.Handled=true;Close();}};
    }
}
