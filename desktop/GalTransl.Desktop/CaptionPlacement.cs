namespace GalTransl.Desktop;

// Keep the same safe dock across sentences and changes in translated length.
// Coordinates follow the game; resize, DPI or explicit preferences reset it.
public sealed class CaptionPlacement {
    public sealed record Result(CaptionLayout.Slot Slot,PixelRect Rect,bool Clipped);
    Result? previous;PixelRect previousGame;double previousDpi;string? previousPolicy;bool expanded;
    public void Reset(){previous=null;expanded=false;}
    public Result? Select(List<(CaptionLayout.Slot Slot,double Height)> measured,PixelRect game,double dpi,string policy,double dx=0,double dy=0){
        if(measured.Count==0){Reset();return null;}
        var same=previous!=null&&previousPolicy==policy&&Math.Abs(previousDpi-dpi)<.01&&
            Math.Abs(previousGame.Width-game.Width)<1&&Math.Abs(previousGame.Height-game.Height)<1;
        if(!same)expanded=false;
        var full=measured.Where(x=>x.Height<=x.Slot.Space.Height).ToList();
        var within=full.Where(x=>x.Slot.InDialogue).ToList();
        if(!expanded&&within.Count>0)measured=within;
        else if(full.Count>0){var backup=full.Where(x=>!x.Slot.InDialogue).ToList();measured=backup.Count>0?backup:full;}
        var chosen=measured[0];
        if(same){var keep=measured.FirstOrDefault(x=>x.Slot.Side==previous!.Slot.Side&&x.Slot.Outside==previous.Slot.Outside&&x.Slot.InDialogue==previous.Slot.InDialogue);
            if(keep.Slot!=null)chosen=keep;}
        var height=Math.Min(chosen.Height<=chosen.Slot.Space.Height?Math.Max(160*dpi,chosen.Height):160*dpi,chosen.Slot.Space.Height);
        var rect=chosen.Slot.Fit(height,dx,dy);
        if(same&&previous!.Slot.Side==chosen.Slot.Side&&previous.Slot.Outside==chosen.Slot.Outside&&previous.Slot.InDialogue==chosen.Slot.InDialogue){
            var moved=previous.Rect with{X=previous.Rect.X+game.X-previousGame.X,Y=previous.Rect.Y+game.Y-previousGame.Y};
            var space=chosen.Slot.Space;
            if(moved.Height>=chosen.Height&&Math.Abs(moved.Width-chosen.Slot.Width)<1&&moved.X>=space.X&&moved.Y>=space.Y&&moved.Right<=space.Right&&moved.Bottom<=space.Bottom)rect=moved;
        }
        if(rect.Height>160*dpi||(!chosen.Slot.InDialogue&&within.Count==0&&measured.Any(x=>x.Slot.InDialogue)==false))expanded=true;
        previous=new(chosen.Slot,rect,chosen.Height>rect.Height);previousGame=game;previousDpi=dpi;previousPolicy=policy;
        return previous;
    }
}
