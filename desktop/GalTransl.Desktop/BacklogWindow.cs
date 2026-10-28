using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace GalTransl.Desktop;

// This window is created only by a player action. It has no caption writer,
// timers or automatic opening/scrolling, and never replays history as subtitles.
public sealed class BacklogWindow:Window {
    readonly Api api;readonly string profileId;readonly CancellationTokenSource closing=new();
    readonly StackPanel rows=new();
    readonly TextBlock status=new(){Foreground=VisualTheme.Brush(VisualTheme.Ink,.72),TextWrapping=TextWrapping.Wrap};
    readonly Button previous=new(){Content="较新的记录",Padding=new Thickness(12,6,12,6)};
    readonly Button next=new(){Content="较早的记录",Padding=new Thickness(12,6,12,6),Margin=new Thickness(8,0,0,0)};
    readonly Button refresh=new(){Content="刷新当前页",Padding=new Thickness(12,6,12,6),Margin=new Thickness(8,0,0,0)};
    int offset,loadedOffset;bool busy,loaded,hasMore;
    public BacklogWindow(Api api,Profile profile){
        this.api=api;profileId=profile.Id;Title="Backlog · "+profile.Name;Width=760;Height=640;MinWidth=420;MinHeight=300;
        VisualTheme.Apply(this);
        FontFamily=new FontFamily("Microsoft YaHei UI");FontSize=15;
        var root=new DockPanel{Margin=new Thickness(24)};Content=root;
        var head=new StackPanel{Margin=new Thickness(0,0,0,16)};DockPanel.SetDock(head,Dock.Top);root.Children.Add(head);
        head.Children.Add(new TextBlock{Text="历史翻译 · "+profile.Name,FontSize=22,FontWeight=FontWeights.SemiBold});
        head.Children.Add(new TextBlock{Text="仅在你打开时显示。关闭后回到当前台词，不会重播历史字幕。",Foreground=VisualTheme.Brush(VisualTheme.Ink,.72),Margin=new Thickness(0,8,0,8),TextWrapping=TextWrapping.Wrap});head.Children.Add(status);
        var actions=new StackPanel{Orientation=Orientation.Horizontal,Margin=new Thickness(0,14,0,0)};
        DockPanel.SetDock(actions,Dock.Bottom);root.Children.Add(actions);actions.Children.Add(previous);actions.Children.Add(next);
        actions.Children.Add(refresh);
        foreach(var button in new[]{previous,next,refresh}){button.Background=VisualTheme.Brush(VisualTheme.Surface,.6);button.Foreground=VisualTheme.Brush(VisualTheme.Ink);button.BorderThickness=new Thickness(0);ButtonChrome.Apply(button);}
        previous.Click+=async(_,_)=>{if(busy)return;offset=Math.Max(0,offset-30);await Load();};
        next.Click+=async(_,_)=>{if(busy)return;offset+=30;await Load();};refresh.Click+=async(_,_)=>await Load();
        root.Children.Add(new ScrollViewer{Content=rows,VerticalScrollBarVisibility=ScrollBarVisibility.Auto});
        Loaded+=async(_,_)=>await Load();Closed+=(_,_)=>closing.Cancel();
        PreviewKeyDown+=(_,e)=>{if(e.Key==System.Windows.Input.Key.Escape){e.Handled=true;Close();}};
    }
    async Task Load(){
        if(busy||closing.IsCancellationRequested)return;busy=true;previous.IsEnabled=next.IsEnabled=refresh.IsEnabled=false;status.Text="读取本机记录…";
        try{
            var result=await api.Call("/history?profile_id="+Uri.EscapeDataString(profileId)+"&limit=30&offset="+offset,token:closing.Token);
            if(closing.IsCancellationRequested)return;rows.Children.Clear();
            foreach(var entry in result.GetProperty("items").EnumerateArray()){
                var row=new StackPanel{Margin=new Thickness(0,0,0,22)};
                var complete=entry.GetProperty("terminal").GetString()=="final";
                row.Children.Add(new TextBlock{Text=complete?"完成":"未完成 · 原文已保留",Foreground=VisualTheme.Brush(VisualTheme.Ink,.72),FontSize=12,Margin=new Thickness(0,0,0,5)});
                row.Children.Add(new TextBlock{Text=entry.GetProperty("source_text").GetString(),TextWrapping=TextWrapping.Wrap,Foreground=VisualTheme.Brush(VisualTheme.Ink,.72)});
                var reason=entry.GetProperty("reason").GetString();
                row.Children.Add(new TextBlock{Text=complete?entry.GetProperty("translation").GetString():Reason(reason),TextWrapping=TextWrapping.Wrap,Foreground=VisualTheme.Brush(VisualTheme.Ink),Margin=new Thickness(0,6,0,0)});rows.Children.Add(row);
            }
            status.Text=rows.Children.Count==0?"本页没有历史记录。":"第 "+(offset/30+1)+" 页 · 新记录不会打断阅读；点击刷新查看";
            loaded=true;loadedOffset=offset;hasMore=result.GetProperty("has_more").GetBoolean();
        }catch(OperationCanceledException) when(closing.IsCancellationRequested){}
        catch(Exception e){offset=loadedOffset;if(!closing.IsCancellationRequested)status.Text="读取失败，已显示的记录仍保留。"+e.Message;}
        finally{busy=false;if(!closing.IsCancellationRequested){refresh.IsEnabled=true;previous.IsEnabled=loaded&&loadedOffset>0;next.IsEnabled=loaded&&hasMore;}}
    }
    static string Reason(string? reason)=>reason switch{
        "superseded"=>"已推进到下一条台词","user_cancelled"=>"已取消","session_reset"=>"已读档或切换场景",
        "engine_stopped"=>"模型已停止","client_disconnected"=>"客户端连接中断",null or ""=>"本条未产生完整译文",_=>reason};
}
