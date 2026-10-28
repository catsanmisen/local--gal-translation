using GalTransl.Desktop;

static class LayoutChecks {
    public static void Run(Action<bool,string> check){
        var fractional=new CaptionLayout.Slot("below",false,new(883.139998846054,883.139998846054,340,92),340,883.139998846054,883.139998846054);
        var exact=fractional.Fit(92,100,-100);
        check(exact.X==883.139998846054&&exact.Y==883.139998846054&&exact.Width==340&&exact.Height==92,"full-size caption fits a fractional free band without inverted clamp bounds");
        var fractionalSource=new PixelRect(800,8,71.139998846054,1064);
        var fractionalSlots=CaptionLayout.Candidates(new(0,0,1920,1080),new(0,0,1920,1080),fractionalSource,new(0,0,1920,1080),"auto",1);
        check(fractionalSlots.Count>0&&fractionalSlots.All(s=>!CaptionLayout.Overlaps(s.Fit(s.Space.Height,0,0),fractionalSource)),"fractional OCR bounds generate and fit safe full-width caption candidates");
        var game=new PixelRect(100,100,1280,720);var work=new PixelRect(0,0,1920,1080);
        var source=new PixelRect(240,650,1000,130);
        var slots=CaptionLayout.Candidates(game,work,source,source,"auto",1);
        var normal=slots[0].Fit(140,0,0);
        check(slots[0].Side=="above"&&!slots[0].Outside&&!CaptionLayout.Overlaps(normal,source),"ordinary dialogue defaults above its complete source block");
        var moving=source with{Y=500};var followed=CaptionLayout.Candidates(game,work,moving,moving,"auto",1)[0].Fit(140,0,0);
        check(CaptionLayout.Overlaps(normal,moving)&&!CaptionLayout.Overlaps(followed,moving),"moving original text requires a new safe caption position even when words are unchanged");
        check(slots.All(s=>!CaptionLayout.Overlaps(s.Fit(200,100000,-100000),source)),"extreme drag offsets clamp into free bands without covering source");
        var below=CaptionLayout.Candidates(game,work,source,source,"below",1);
        check(below[0].Side=="above","unavailable preferred direction safely falls back");
        var center=new PixelRect(220,320,1060,230);
        var preferred=CaptionLayout.Candidates(game,work,center,center,"below",1);
        check(preferred[0].Side=="below"&&!CaptionLayout.Overlaps(preferred[0].Fit(180,0,0),center),"centered performance can use a saved below preference");
        var vertical=new PixelRect(850,115,200,690);
        var verticalSlots=CaptionLayout.Candidates(game,work,vertical,vertical,"auto",1);
        check(verticalSlots[0].Side is "left" or "right","tall vertical source prefers a side band");
        var nvl=new PixelRect(112,112,1256,696);
        var outer=new PixelRect(90,65,1300,765);
        var external=CaptionLayout.Candidates(game,work,nvl,nvl,"auto",1,outer);
        check(external.Count>0&&external.All(s=>s.Outside&&!CaptionLayout.Overlaps(s.Fit(200,0,0),outer)),"full-page NVL uses available space outside the actual window frame");
        var fullscreen=new PixelRect(0,0,1920,1080);
        check(CaptionLayout.Candidates(fullscreen,work,fullscreen,fullscreen,"auto",1).Count==0,"full-screen source with no free band hides caption instead of covering text");
        var narrow=new PixelRect(100,150,1280,630);
        var docks=CaptionLayout.Candidates(game,work,narrow,narrow,"auto",1,outer,controlsOnly:true);
        check(docks.Count>0&&docks.All(s=>!CaptionLayout.Overlaps(s.Fit(32,0,0),narrow)),"a small controls-only dock can remain when caption height does not fit");
        var negative=new PixelRect(-1800,100,1280,720);var otherScreen=new PixelRect(-1920,0,1920,1080);
        var otherText=new PixelRect(-1690,650,1060,140);
        var cross=CaptionLayout.Candidates(negative,otherScreen,otherText,otherText,"auto",1)[0].Fit(150,-1000,1000);
        check(cross.X>=otherScreen.X&&cross.Right<=otherScreen.Right&&!CaptionLayout.Overlaps(cross,otherText),"negative monitor origins are preserved and bounded");
        var large=new PixelRect(0,0,3840,2160);var largeSource=new PixelRect(240,1640,3000,360);
        var dpi=CaptionLayout.Candidates(large,large,largeSource,largeSource,"auto",2)[0].Fit(280,0,0);
        check(dpi.Height==280&&dpi.Bottom<=largeSource.Y-24,"200 percent DPI scales the source safety gap");
        var edgeGame=new PixelRect(-80,-50,1100,800);var edgeText=new PixelRect(-20,550,980,170);
        var edge=CaptionLayout.Candidates(edgeGame,work,edgeText,edgeText,"auto",1)[0].Fit(150,0,0);
        check(edge.X>=0&&edge.Y>=0&&edge.Right<=work.Right&&edge.Bottom<=work.Bottom,"partly offscreen game still produces an onscreen caption");
        check(CaptionLayout.Candidates(game,work,source with{Width=double.NaN},source,"auto",1).Count==0,"invalid capture geometry cannot position a native window");
    }
}
