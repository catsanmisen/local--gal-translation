namespace GalTransl.Desktop;

// Pixel-only layout policy. All candidates are free rectangles outside the
// entire detected source block. WPF measures text at each candidate's width.
public static class CaptionLayout {
    public static readonly string[] Modes=["auto","above","below","left","right","outside"];
    public sealed record Slot(string Side,bool Outside,PixelRect Space,double Width,double X,double Y,bool InDialogue=false){
        public PixelRect Fit(double height,double dx,double dy){
            height=Math.Clamp(height,0,Space.Height);
            return new(Math.Clamp(X+dx,Space.X,Space.X+(Space.Width-Width)),
                Math.Clamp(Y+dy-(Side=="above"?height:0),Space.Y,Space.Y+(Space.Height-height)),Width,height);
        }
    }
    public static PixelRect Union(PixelRect a,PixelRect b)=>new(Math.Min(a.X,b.X),Math.Min(a.Y,b.Y),
        Math.Max(a.Right,b.Right)-Math.Min(a.X,b.X),Math.Max(a.Bottom,b.Bottom)-Math.Min(a.Y,b.Y));
    public static PixelRect Intersect(PixelRect a,PixelRect b)=>new(Math.Max(a.X,b.X),Math.Max(a.Y,b.Y),
        Math.Max(0,Math.Min(a.Right,b.Right)-Math.Max(a.X,b.X)),Math.Max(0,Math.Min(a.Bottom,b.Bottom)-Math.Max(a.Y,b.Y)));
    public static bool Overlaps(PixelRect a,PixelRect b)=>a.X<b.Right&&a.Right>b.X&&a.Y<b.Bottom&&a.Bottom>b.Y;
    static bool Valid(PixelRect r)=>double.IsFinite(r.X)&&double.IsFinite(r.Y)&&double.IsFinite(r.Width)&&double.IsFinite(r.Height)&&r.Width>0&&r.Height>0;
    public static List<Slot> Candidates(PixelRect game,PixelRect work,PixelRect source,PixelRect roi,
        string mode,double dpi,PixelRect? frame=null,bool controlsOnly=false,PixelRect? dialogue=null){
        var slots=new List<Slot>();
        if(!Valid(game)||!Valid(work)||!Valid(source)||!double.IsFinite(dpi)||dpi<=0)return slots;
        source=Intersect(source,game);var visible=Intersect(game,work);var gap=12*dpi;var margin=8*dpi;
        var minWidth=(controlsOnly?212:340)*dpi;var minHeight=(controlsOnly?32:92)*dpi;
        void Add(string side,bool outside,PixelRect free){
            free=Intersect(free,work);
            if(free.Width<minWidth||free.Height<minHeight)return;
            var width=Math.Min(free.Width,controlsOnly?minWidth:Math.Max(minWidth,roi.Width));
            var space=free with{Height=Math.Min(free.Height,(controlsOnly?32:300)*dpi)};
            // Above captions align to the bottom of their free band.
            if(side=="above")space=space with{Y=free.Bottom-space.Height};
            else if(side is "left" or "right")space=space with{Y=Math.Clamp(source.Y,free.Y,free.Y+(free.Height-space.Height))};
            var x=side=="left"?free.X+(free.Width-width):side=="right"?free.X:Math.Clamp(roi.X,free.X,free.X+(free.Width-width));
            var y=side=="above"?space.Bottom:side=="below"?space.Y:Math.Clamp(source.Y,space.Y,space.Y+(space.Height-minHeight));
            slots.Add(new(side,outside,space,width,x,y));
        }
        var inner=new PixelRect(visible.X+margin,visible.Y+margin,visible.Width-2*margin,visible.Height-2*margin);
        Add("above",false,new(inner.X,inner.Y,inner.Width,source.Y-gap-inner.Y));
        Add("below",false,new(inner.X,source.Bottom+gap,inner.Width,inner.Bottom-source.Bottom-gap));
        Add("left",false,new(inner.X,inner.Y,source.X-gap-inner.X,inner.Height));
        Add("right",false,new(source.Right+gap,inner.Y,inner.Right-source.Right-gap,inner.Height));
        var outer=frame??game;
        Add("above",true,new(work.X,work.Y,work.Width,outer.Y-gap-work.Y));
        Add("below",true,new(work.X,outer.Bottom+gap,work.Width,work.Bottom-outer.Bottom-gap));
        Add("right",true,new(outer.Right+gap,work.Y,work.Right-outer.Right-gap,work.Height));
        Add("left",true,new(work.X,work.Y,outer.X-gap-work.X,work.Height));
        var vertical=source.Height>=game.Height*.65&&source.Width<game.Width*.35;
        var order=vertical?new[]{"right","left","above","below"}:new[]{"above","below","right","left"};
        var ordered=slots.OrderBy(s=>mode=="outside"?(s.Outside?0:1):(!s.Outside&&s.Side==mode?0:1))
            .ThenBy(s=>s.Outside?1:0).ThenBy(s=>Array.IndexOf(order,s.Side)).ToList();
        if(dialogue is PixelRect box&&Valid(box)){
            box=Intersect(Intersect(box,game),work);
            // Text outside this box belongs to a special presentation. Do not
            // force it into the regular dialogue dock or pretend it is protected.
            if(Valid(box)&&source.X>=box.X&&source.Y>=box.Y&&source.Right<=box.Right&&source.Bottom<=box.Bottom){
                // A backup outside the configured dialogue must also avoid its
                // speaker/name area, which is deliberately excluded from OCR.
                ordered=Candidates(game,work,Union(source,box),roi,mode,dpi,frame,controlsOnly);
                if(mode!="outside"){
                    var inside=Candidates(box,box,source,box,mode,dpi,box,controlsOnly);
                    ordered.InsertRange(0,inside.Where(s=>!s.Outside).Select(s=>s with{InDialogue=true}));
                }
            }
        }
        return ordered;
    }
    public static string Label(string side,bool outside)=>(outside?"游戏外侧 · ":"")+
        (side switch{"above"=>"原文上方","below"=>"原文下方","left"=>"原文左侧","right"=>"原文右侧",_=>"自动避让"});
}
