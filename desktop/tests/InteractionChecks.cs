using GalTransl.Desktop;

static class InteractionChecks {
    public static void Run(Action<bool,string> check){
        var gate=new SingleInputGate();gate.Configure("key:A");
        check(gate.Observe("key:A",true,true)&&!gate.Observe("key:A",true,true),"single key toggles once and ignores keyboard repeat");
        gate.Observe("key:A",false,false);check(gate.Observe("key:A",true,true),"release then press restores with the same single input");
        gate.Observe("key:A",false,true);check(!gate.Observe("key:A",true,false)&&!gate.Observe("key:A",true,true),"a held key from another app does not toggle when game regains focus");
        gate.Observe("key:A",false,true);check(!gate.Observe("key:A",true,true,modified:true),"modified keyboard chords do not act as a single input");
        gate.Configure("mouse_left");check(!gate.Observe("mouse_right",true,true),"unselected mouse button never changes subtitle visibility");
        check(!gate.Observe("mouse_left",true,true,overControls:true),"Backlog and position clicks do not trigger mouse hide");
        gate.Observe("mouse_left",false,true);check(gate.Observe("mouse_left",true,true),"a game click can hide while caption body remains pass-through");
        gate.Configure("none");check(!gate.Observe("mouse_left",true,true),"disabled single input stays inactive");
        check(SingleInputGate.Key(119)=="key:F8"&&SingleInputGate.Key(32)=="key:Space"&&SingleInputGate.Key(17)==null,"supported virtual keys map without accepting modifier-only shortcuts");

        var game=new PixelRect(100,100,1280,720);var work=new PixelRect(0,0,1920,1080);
        var source=new PixelRect(250,590,960,40);var container=new PixelRect(120,380,1240,410);
        var slots=CaptionLayout.Candidates(game,work,source,source,"auto",1,dialogue:container);
        check(slots[0].InDialogue&&slots[0].Fit(160,0,0).Y>=container.Y,"configured game dialogue box has first priority");
        var memory=new CaptionPlacement();
        List<(CaptionLayout.Slot Slot,double Height)> Measured(List<CaptionLayout.Slot> s,double h)=>s.Select(x=>(x,h)).ToList();
        var first=memory.Select(Measured(slots,100),game,1,"auto")!;
        var longText=memory.Select(Measured(slots,500),game,1,"auto")!;
        check(first.Rect==longText.Rect&&longText.Clipped,"translation length never moves a stable dock and long text is clipped");
        var jitter=CaptionLayout.Candidates(game,work,source with{Y=593},source,"auto",1,dialogue:container);
        check(memory.Select(Measured(jitter,120),game,1,"auto")!.Rect==first.Rect,"small OCR bounds jitter keeps the existing safe position");
        var complete=memory.Select(Measured(slots,220),game,1,"auto")!;
        check(!complete.Clipped&&!complete.Slot.InDialogue&&complete.Rect.Height>=220,"long current translation uses a full safe backup area before clipping");
        var retained=memory.Select(Measured(slots,100),game,1,"auto")!;
        check(retained.Rect==complete.Rect&&!retained.Slot.InDialogue,"short next sentence keeps the expanded reading dock instead of jumping back");
        memory.Reset();first=memory.Select(Measured(slots,100),game,1,"auto")!;
        var movedGame=game with{X=180,Y=160};var movedSource=source with{X=330,Y=650};var movedContainer=container with{X=200,Y=440};
        var moved=memory.Select(Measured(CaptionLayout.Candidates(movedGame,work,movedSource,movedSource,"auto",1,dialogue:movedContainer),110),movedGame,1,"auto")!;
        check(moved.Rect.X==first.Rect.X+80&&moved.Rect.Y==first.Rect.Y+60,"stable dock follows window movement without re-anchoring to text");
        memory.Reset();var below=CaptionLayout.Candidates(game,work,source,source,"below",1);
        var lower=memory.Select(Measured(below,100),game,1,"below")!;
        var auto=memory.Select(Measured(CaptionLayout.Candidates(game,work,source,source,"auto",1),120),game,1,"below")!;
        check(lower.Slot.Side=="below"&&auto.Slot.Side=="below","an available remembered side does not oscillate when candidate ordering changes");
        var changed=memory.Select(Measured(CaptionLayout.Candidates(game,work,source,source,"above",1),120),game,1,"above")!;
        check(changed.Slot.Side=="above","explicit player direction resets side preference");
        var full=new PixelRect(112,112,1256,696);
        var special=CaptionLayout.Candidates(game,work,full,full,"auto",1,dialogue:container);
        check(special.All(s=>!s.InDialogue),"special text outside the regular dialogue box uses safe fallback");
        var blocked=memory.Select(Measured(special,120),game,1,"above")!;
        check(!CaptionLayout.Overlaps(blocked.Rect,full),"a growing source invalidates an unsafe old dock");
        var outside=CaptionLayout.Candidates(game,work,source,source,"outside",1,dialogue:container);
        check(outside[0].Outside&&!outside.Any(s=>s.InDialogue),"explicit outside preference bypasses the regular dialogue box");
        check(slots.Where(s=>!s.InDialogue).All(s=>!CaptionLayout.Overlaps(s.Fit(220,100000,-100000),container)),"long-caption backup avoids the complete dialogue and speaker area");
        var compactGame=new PixelRect(0,0,960,540);var compactBox=new PixelRect(25,370,775,148);var wideSource=new PixelRect(70,442,700,65);
        var compact=CaptionLayout.Candidates(compactGame,compactGame,wideSource,wideSource,"outside",1,dialogue:compactBox);
        check(compact.Count>0&&compact.All(s=>!CaptionLayout.Overlaps(s.Fit(180,0,0),compactBox)),"outside fallback on a crowded screen still leaves the name box visible");
        check(memory.Select([],game,1,"auto")==null,"no safe space clears placement memory without showing history");
        memory.Reset();var offset=memory.Select(Measured(slots,120),game,1,"offset",100000,-100000)!;
        check(!CaptionLayout.Overlaps(offset.Rect,source)&&offset.Rect.X>=container.X&&offset.Rect.Right<=container.Right,"drag offsets remain clamped inside the game dialogue box");
        var resized=game with{Width=1400};var reset=memory.Select(Measured(slots,120),resized,1,"offset")!;
        check(reset.Rect!=offset.Rect,"resize recalculates rather than reusing obsolete pixel offsets");
    }
}
