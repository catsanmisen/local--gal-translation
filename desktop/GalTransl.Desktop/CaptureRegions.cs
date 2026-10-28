namespace GalTransl.Desktop;

// One serial OCR stream: probe an idle alternate, then give the active region
// its next capture even when OCR itself takes longer than the probe interval.
public sealed class CaptureRegions {
    public static Region WithMargin(Region region){
        // Keep complete glyphs when a tightly selected edge shifts slightly
        // after resizing or a game's letterbox change. Layout still uses the
        // actual recognized bounds; player configuration is not rewritten.
        var px=Math.Min(.02,region.Width*.15);var py=Math.Min(.02,region.Height*.15);
        var left=Math.Max(0,region.X-px);var top=Math.Max(0,region.Y-py);
        return new(left,top,Math.Min(1,region.X+region.Width+px)-left,Math.Min(1,region.Y+region.Height+py)-top);
    }
    public bool Special {get;private set;}double? blankAt,changedAt;double nextProbe,probeAt;
    readonly string[] previous=["",""];string? probeText;bool activeNext;
    public void Reset(){Special=false;blankAt=changedAt=null;nextProbe=0;previous[0]=previous[1]="";probeText=null;activeNext=false;}
    public (Region Region,bool IsSpecial) Choose(Region primary,Region? special,double now,bool suspendProbes=false){
        if(special==null){Reset();return(primary,false);}
        if(suspendProbes)return Special?(special,true):(primary,false);
        if(activeNext)activeNext=false;
        else if(now>=nextProbe&&(Special||changedAt is double changed&&now-changed>=1000||blankAt is double blank&&now-blank>=400)){
            nextProbe=now+1000;activeNext=true;return Special?(primary,false):(special,true);
        }
        return Special?(special,true):(primary,false);
    }
    public (bool Process,bool Switched) Observe(bool isSpecial,string text,double now,bool hasFallback){
        if(!hasFallback)return(true,false);
        var index=isSpecial?1:0;
        if(Special!=isSpecial){
            if(string.IsNullOrWhiteSpace(text)||text==previous[index]||text==previous[1-index]){probeText=null;return(false,false);}
            if(probeText!=text){probeText=text;probeAt=now;return(false,false);}
            if(now-probeAt>=400){
                Special=isSpecial;previous[index]=text;blankAt=null;probeText=null;
                changedAt=now;nextProbe=now+1000;activeNext=true;return(true,true);
            }
            return(false,false);
        }
        if(string.IsNullOrWhiteSpace(text)){
            // Blankness only schedules a probe. Switching still requires fresh
            // alternate text, otherwise an unchanged old page would replay.
            blankAt??=now;
        }else {
            blankAt=null;
            if(previous[index]!=text){previous[index]=text;changedAt=now;probeText=null;}
        }
        return(true,false);
    }
}
