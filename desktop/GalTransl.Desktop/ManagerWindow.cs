using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace GalTransl.Desktop;

public sealed class ManagerWindow:Window {
    readonly Coordinator host;
    readonly ComboBox windows=new(){MinWidth=470,DisplayMemberPath="Title",Margin=new Thickness(0,8,0,0)};
    readonly TextBox name=new(){Margin=new Thickness(0,8,0,0),Padding=new Thickness(8),MaxLength=80};
    readonly TextBlock status=new(){TextWrapping=TextWrapping.Wrap,Foreground=VisualTheme.Brush(VisualTheme.Ink,.72),Margin=new Thickness(0,16,0,12)};
    readonly ListBox threads=new(){Height=150,DisplayMemberPath="Text",Margin=new Thickness(0,8,0,0)};
    readonly ComboBox profiles=new(){DisplayMemberPath="Name",Margin=new Thickness(0,8,0,0)};
    readonly CheckBox autoRecovery=new(){Content="显存恢复后自动降层恢复翻译",Foreground=VisualTheme.Brush(VisualTheme.Ink,.72),IsChecked=true,Margin=new Thickness(0,12,0,0)};
    readonly Dictionary<string,TextBox> hotkeys=new();
    readonly ProfileDrafts drafts=new();bool fillingKeys,refreshingProfiles;string? editingId;
    readonly ComboBox modelMode=new(){Margin=new Thickness(0,8,0,0),DisplayMemberPath="Value",SelectedValuePath="Key"};
    readonly ComboBox modelReserve=new(){Margin=new Thickness(0,8,0,0),ItemsSource=new[]{2048,1536,1024}};
    readonly TextBlock modelStatus=new(){TextWrapping=TextWrapping.Wrap,Foreground=VisualTheme.Brush(VisualTheme.Ink,.72),Margin=new Thickness(0,12,0,4)};
    readonly CheckBox wallpaperRelief=new(){Content="自动临时停止高占用壁纸",Foreground=VisualTheme.Brush(VisualTheme.Ink,.72),IsChecked=true,Margin=new Thickness(0,12,0,4)};
    readonly TextBlock wallpaperStatus=new(){TextWrapping=TextWrapping.Wrap,Foreground=VisualTheme.Brush(VisualTheme.Ink,.62),Margin=new Thickness(0,4,0,4)};
    System.Windows.Controls.Button modelSave=null!;bool modelDirty,fillingModel;
    Region? region;
    public bool AllowClose {get;set;}
    public ManagerWindow(Coordinator host){
        this.host=host;Title="GalTransl · 游戏旁实时翻译";Width=740;Height=820;MinWidth=600;MinHeight=560;
        VisualTheme.Apply(this);FontSize=14;
        var stack=new StackPanel{Margin=new Thickness(28)};Content=new ScrollViewer{Content=stack,VerticalScrollBarVisibility=ScrollBarVisibility.Auto};
        stack.Children.Add(new TextBlock{Text="在游戏旁读懂台词",FontSize=25,FontWeight=FontWeights.SemiBold});
        stack.Children.Add(new TextBlock{Text="首次选一次区域或取词线程，之后自动跟随。关闭此窗口仍会在托盘运行。",Foreground=VisualTheme.Brush(VisualTheme.Ink,.72),TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,10,0,12)});
        stack.Children.Add(status);
        Section(stack,"模型运行设备 · 全局设置");
        modelMode.ItemsSource=new Dictionary<string,string>{{"auto","自动 · 沿用现有策略"},{"cpu","CPU · 使用处理器"},{"gpu","GPU · 显存不足时等待，不退回 CPU"}};
        stack.Children.Add(modelMode);stack.Children.Add(new TextBlock{Text="GPU 显存预留（MiB）",Margin=new Thickness(0,12,0,0)});stack.Children.Add(modelReserve);
        stack.Children.Add(modelStatus);
        stack.Children.Add(new TextBlock{Text="较低预留可加载更多 GPU 层，也会减少留给游戏的显存。设备选择按客户端保存，运行中切换会安全重载。",TextWrapping=TextWrapping.Wrap,Foreground=VisualTheme.Brush(VisualTheme.Ink,.72),Margin=new Thickness(0,4,0,0)});
        modelMode.SelectionChanged+=(_,_)=>{if(!fillingModel){modelDirty=true;UpdateModel();}};
        modelReserve.SelectionChanged+=(_,_)=>{if(!fillingModel)modelDirty=true;};
        wallpaperRelief.Checked+=(_,_)=>{if(!fillingModel)modelDirty=true;};wallpaperRelief.Unchecked+=(_,_)=>{if(!fillingModel)modelDirty=true;};
        stack.Children.Add(wallpaperRelief);stack.Children.Add(wallpaperStatus);
        modelSave=Button(stack,"保存并应用设备设置",async()=>{
            await host.SaveModelSettings(modelMode.SelectedValue as string??"auto",modelReserve.SelectedItem is int r?r:2048,wallpaperRelief.IsChecked==true);
            modelDirty=false;UpdateModel();
        });UpdateModel();
        Section(stack,"1 · 选择正在运行的游戏");stack.Children.Add(windows);
        windows.SelectionChanged+=(_,_)=>{if(windows.SelectedItem is GameWindow w){var saved=host.Profiles.FirstOrDefault(p=>string.Equals(p.Game.Executable,w.Executable,StringComparison.OrdinalIgnoreCase));
            name.Text=saved?.Name??(w.Title.Length>80?w.Title[..80]:w.Title);region=saved?.Game.Region;autoRecovery.IsChecked=saved?.Game.AutoRecovery??true;}};
        Button(stack,"刷新游戏窗口",()=>{RefreshWindows();return Task.CompletedTask;});
        stack.Children.Add(name);
        Button(stack,"2 · 框选日文台词区域",()=>{if(windows.SelectedItem is not GameWindow w)throw new InvalidOperationException("请先选择游戏窗口。");
            var picked=RegionPicker.Pick(w);if(picked!=null){region=picked;status.Text="台词区域已选定，点击保存后回到游戏即可自动翻译。";}return Task.CompletedTask;});
        stack.Children.Add(autoRecovery);
        Button(stack,"保存游戏 · 自动开始",async()=>{
            if(windows.SelectedItem is not GameWindow w||region==null)throw new InvalidOperationException("请先选择游戏并框选台词区域。");
            var id="game-"+Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(w.Executable.ToLowerInvariant())))[..16].ToLowerInvariant();
            var p=host.Profiles.FirstOrDefault(p=>p.Id==id)??new Profile{Id=id,Name=name.Text.Trim()};
            p.Name=string.IsNullOrWhiteSpace(name.Text)?w.Title:name.Text.Trim();p.Game.Executable=w.Executable;p.Game.Region=region;p.Game.AutoRecovery=autoRecovery.IsChecked==true;p.Game.Enabled=true;
            await host.Save(p);await host.Bind(w,p);RefreshProfiles();status.Text="已保存。回到游戏后会自动取词、加载模型并显示字幕。";
        },true);
        Section(stack,"已保存的游戏");stack.Children.Add(profiles);
        profiles.SelectionChanged+=(_,_)=>{if(!refreshingProfiles)LoadKeys();};
        Button(stack,"使用 OCR 取词",async()=>{var p=Selected();var rebind=ProfileDrafts.CanRebind(p,host.CurrentProfile,host.Current);await host.PatchGame(p,new{input_mode="ocr"});if(rebind&&host.Current is GameWindow w)await host.Bind(w,host.Profiles.First(x=>x.Id==p.Id));});
        Section(stack,"3 · 老游戏建议使用 HOOK");
        stack.Children.Add(new TextBlock{Text="扫描后正常推进一两句台词，选择正确的日文线程。选定后下次自动连接；连接失败自动回到 OCR。",Foreground=VisualTheme.Brush(VisualTheme.Ink,.72),TextWrapping=TextWrapping.Wrap});
        Button(stack,"扫描 HOOK 线程",()=>{if(!ProfileDrafts.CanRebind(Selected(),host.CurrentProfile,host.Current))throw new InvalidOperationException("请先连接所选游戏，再扫描线程。");host.StartHook();return Task.CompletedTask;});
        stack.Children.Add(threads);
        Button(stack,"记住选中的日文线程",async()=>{if(!ProfileDrafts.CanRebind(Selected(),host.CurrentProfile,host.Current)||threads.SelectedItem is not HookText t)throw new InvalidOperationException("请连接所选游戏并选择其线程。");await host.SelectHook(t);status.Text="HOOK 线程已保存，下次自动恢复。";});
        Section(stack,"全局快捷键");
        foreach(var pair in new[]{("visibility","显示 / 隐藏","Ctrl+Shift+H"),("pause","暂停 / 恢复","Ctrl+Shift+P"),("reset","读档重置","Ctrl+Shift+R"),("backlog","查看 / 关闭历史","Ctrl+Shift+B")}){
            var row=new DockPanel{Margin=new Thickness(0,5,0,0)};row.Children.Add(new TextBlock{Text=pair.Item2,Width=140,VerticalAlignment=VerticalAlignment.Center});
            var box=new TextBox{Text=pair.Item3,Padding=new Thickness(6)};hotkeys[pair.Item1]=box;row.Children.Add(box);stack.Children.Add(row);
            box.TextChanged+=(_,_)=>{if(!fillingKeys&&editingId!=null)drafts.Edit(editingId,hotkeys.ToDictionary(x=>x.Key,x=>x.Value.Text));};
        }
        Button(stack,"保存快捷键",async()=>{var p=Selected();var keys=hotkeys.ToDictionary(x=>x.Key,x=>x.Value.Text);await host.PatchGame(p,new{hotkeys=keys});drafts.Saved(p.Id);
            if(host.CurrentProfile?.Id==p.Id)host.Overlay.ConfigureHotkeys(keys);status.Text="所选游戏的快捷键已更新。";LoadKeys();});
        Button(stack,"调整字幕位置 / 结束调整",()=>{host.Overlay.Edit(!host.Overlay.Editing);host.RefreshOverlay();return Task.CompletedTask;});
        Button(stack,"字幕摆放与特殊文字演出",()=>{host.ShowPosition();return Task.CompletedTask;});
        Button(stack,"暂停 / 恢复采集",()=>host.Pause(!host.Paused));
        Button(stack,"查看 / 关闭历史翻译（Backlog）",()=>{host.ToggleBacklog();return Task.CompletedTask;});
        Button(stack,"术语、历史与浏览器设置",()=>{Process.Start(new ProcessStartInfo(host.Api.Base+"/app/"){UseShellExecute=true});return Task.CompletedTask;});
        Closing+=(_,e)=>{if(!AllowClose){e.Cancel=true;Hide();}};
        host.Changed+=Update;RefreshWindows();RefreshProfiles();
    }
    Profile Selected()=>ProfileDrafts.Selected(profiles.SelectedItem as Profile,host.CurrentProfile)??throw new InvalidOperationException("请先选择保存的游戏。");
    void LoadKeys(){var p=profiles.SelectedItem as Profile??host.CurrentProfile;if(p==null)return;editingId=p.Id;var keys=drafts.Read(p);fillingKeys=true;
        try{var defaults=new GameConfig().Hotkeys;foreach(var key in hotkeys.Keys)hotkeys[key].Text=keys.GetValueOrDefault(key,defaults[key]);}finally{fillingKeys=false;}}
    void Section(Panel p,string text)=>p.Children.Add(new TextBlock{Text=text,FontSize=17,FontWeight=FontWeights.SemiBold,Margin=new Thickness(0,24,0,4)});
    System.Windows.Controls.Button Button(Panel p,string text,Func<Task> action,bool primary=false){
        var b=new System.Windows.Controls.Button{Content=text,Padding=new Thickness(12,8,12,8),Margin=new Thickness(0,8,0,0),HorizontalAlignment=HorizontalAlignment.Left,
            FontWeight=primary?FontWeights.SemiBold:FontWeights.Normal};
        ButtonChrome.Apply(b);
        b.Click+=async(_,_)=>{b.IsEnabled=false;try{await action();}catch(Exception e){status.Text=e.Message;}finally{b.IsEnabled=true;if(ReferenceEquals(b,modelSave))UpdateModel();}};p.Children.Add(b);return b;
    }
    void UpdateModel(){
        if(!modelDirty){fillingModel=true;try{modelMode.SelectedValue=host.ModelSettings.Mode;modelReserve.SelectedItem=host.ModelSettings.Reserve;wallpaperRelief.IsChecked=host.ModelSettings.WallpaperRelief;}finally{fillingModel=false;}}
        modelStatus.Text=host.ModelSettingsAvailable?host.ModelDescription:"当前后台不提供设备设置，请启动最新候选。";
        modelMode.IsEnabled=host.ModelSettingsAvailable&&!host.ModelReloading;
        modelReserve.IsEnabled=modelMode.IsEnabled&&modelMode.SelectedValue as string!="cpu";
        modelSave.IsEnabled=host.ModelSettingsAvailable&&!host.ModelReloading;
        wallpaperRelief.IsEnabled=host.ModelSettingsAvailable&&host.WallpaperSettingsAvailable&&!host.ModelReloading;wallpaperStatus.Text=host.WallpaperDescription;
    }
    void RefreshWindows()=>windows.ItemsSource=Native.Windows().OrderByDescending(Native.Focused).ToList();
    void RefreshProfiles(){var id=(profiles.SelectedItem as Profile)?.Id??host.CurrentProfile?.Id;refreshingProfiles=true;
        try{profiles.ItemsSource=host.Profiles.Where(p=>p.Game.Executable!=null).ToList();profiles.SelectedItem=host.Profiles.FirstOrDefault(p=>p.Id==id);}finally{refreshingProfiles=false;}LoadKeys();}
    void Update(){
        if(!Dispatcher.CheckAccess()){Dispatcher.InvokeAsync(Update);return;}
        status.Text=host.Overlay.InputNotice??host.Overlay.PlacementNotice??host.Notice??(host.Current is null?"等待已配置的游戏启动。":host.Paused?"采集已暂停。":$"已连接 {host.CurrentProfile?.Name} · 回到游戏自动显示翻译");
        UpdateModel();
        var selected=(threads.SelectedItem as HookText)?.Handle;threads.ItemsSource=host.Threads.Values.ToList();threads.SelectedItem=host.Threads.Values.FirstOrDefault(t=>t.Handle==selected);
        RefreshProfiles();
    }
}
