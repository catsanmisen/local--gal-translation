using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;

namespace GalTransl.Desktop;

public sealed class RegionPicker:Window {
    public static Region? Pick(GameWindow game,bool dialogueBox=false){
        var settings=Application.Current.Windows.Cast<Window>().Where(w=>w.IsVisible&&w is ManagerWindow or PositionWindow).ToArray();
        foreach(var window in settings)window.Hide();
        try{
            Native.SetForegroundWindow(game.Handle);
            var picker=new RegionPicker(game,dialogueBox);
            return picker.ShowDialog()==true?picker.Selected:null;
        }finally{
            foreach(var window in settings)window.Show();
            settings.LastOrDefault()?.Activate();
        }
    }
    readonly Canvas canvas=new();readonly Rectangle selection=new(){Stroke=VisualTheme.Brush(VisualTheme.Ink),StrokeThickness=2,Fill=VisualTheme.Brush(VisualTheme.Surface,.22),RadiusX=8,RadiusY=8};
    Point start;bool dragging;readonly GameWindow game;
    public Region? Selected {get;private set;}
    public RegionPicker(GameWindow game,bool dialogueBox=false){
        this.game=game;Title=dialogueBox?"框选游戏内整个对话框":"框选游戏台词区域";WindowStyle=WindowStyle.None;AllowsTransparency=true;
        Background=VisualTheme.Brush(VisualTheme.Base,.14);Topmost=true;ShowInTaskbar=true;Cursor=System.Windows.Input.Cursors.Cross;
        var rect=Native.ClientRect(game.Handle);var dpi=Math.Max(96,Native.GetDpiForWindow(game.Handle))/96.0;
        Left=rect.X/dpi;Top=rect.Y/dpi;Width=rect.Width/dpi;Height=rect.Height/dpi;Content=canvas;
        SourceInitialized+=(_,_)=>Native.SetWindowPos(new System.Windows.Interop.WindowInteropHelper(this).Handle,-1,(int)rect.X,(int)rect.Y,(int)rect.Width,(int)rect.Height,0);
        canvas.Children.Add(new TextBlock{Text=dialogueBox?"框选整个游戏内对话框，包含空白摆放空间 · Esc 取消":"拖动框选日文台词区域（不含名字框） · Esc 取消",Foreground=VisualTheme.Brush(VisualTheme.Ink),Background=VisualTheme.Brush(VisualTheme.Base,.9),Padding=new Thickness(12)});canvas.Children.Add(selection);
        MouseLeftButtonDown+=(_,e)=>{start=e.GetPosition(canvas);dragging=true;CaptureMouse();};
        MouseMove+=(_,e)=>{if(!dragging)return;var p=e.GetPosition(canvas);Canvas.SetLeft(selection,Math.Min(start.X,p.X));Canvas.SetTop(selection,Math.Min(start.Y,p.Y));selection.Width=Math.Abs(p.X-start.X);selection.Height=Math.Abs(p.Y-start.Y);};
        MouseLeftButtonUp+=(_,e)=>{if(!dragging)return;ReleaseMouseCapture();dragging=false;if(selection.Width<20||selection.Height<15)return;
            Selected=new(Canvas.GetLeft(selection)/ActualWidth,Canvas.GetTop(selection)/ActualHeight,selection.Width/ActualWidth,selection.Height/ActualHeight);DialogResult=true;};
        KeyDown+=(_,e)=>{if(e.Key==Key.Escape)DialogResult=false;};
    }
}
