using GalTransl.Desktop;
static class PriorityChecks {
    public static void Run(Action<bool,string> check){
        var regions=new CaptureRegions();var primary=new Region(0,.7,1,.2);var special=new Region(.1,.1,.8,.5);
        check(!regions.Choose(primary,special,12345678).IsSpecial,"first capture reads primary even with an absolute Stopwatch timestamp");
        regions.Observe(false,"旧正文",0,true);
        check(regions.Choose(primary,special,1000).IsSpecial,"unchanged nonempty primary still probes configured special text");
        check(!regions.Observe(true,"特殊演出",1000,true).Process&&!regions.Special,"one alternate observation cannot switch the caption");
        check(!regions.Choose(primary,special,2500).IsSpecial,"slow probe leaves at least one active-region capture before the next probe");
        regions.Observe(false,"旧正文",2500,true);
        check(regions.Choose(primary,special,2700).IsSpecial,"the configured special region is probed again while old regular text remains");
        check(regions.Observe(true,"特殊演出",2700,true).Switched&&regions.Special,"stable new special text switches despite nonempty old primary");
        regions.Choose(primary,special,2800);regions.Observe(true,"特殊演出",2800,true);
        check(!regions.Observe(false,"旧正文",3800,true).Process&&regions.Special,"old primary never replays over the new special page");
        check(!regions.Observe(false,"新正文",4800,true).Process,"return to primary also requires repeated evidence");
        check(regions.Observe(false,"新正文",5800,true).Switched&&!regions.Special,"stable new primary restores normal capture");
        check(!regions.Observe(true,"特殊演出",6800,true).Process&&!regions.Special,"the old special page cannot bounce back after normal dialogue resumes");
        regions.Observe(false,"",7000,true);regions.Observe(false,"",7500,true);
        check(!regions.Observe(true,"特殊演出",7800,true).Process&&!regions.Special,"a blank active region cannot reactivate an old alternate page");
        regions.Reset();regions.Observe(false,"旧正文",0,true);regions.Observe(true,"特殊演出",1000,true);
        regions.Observe(false,"新正文",1200,true);
        check(!regions.Observe(true,"特殊演出",2200,true).Process,"changing normal dialogue invalidates a pending alternate probe");
        check(!regions.Choose(primary,null,5000).IsSpecial,"no alternate is probed without a player-configured region");
        regions.Reset();regions.Observe(false,"旧正文",0,true);
        var menuPage=new PageText();menuPage.Accept("旧正文",menuPage.Read("旧正文"));
        var menuSubmissions=0;var activeOnly=true;
        foreach(var at in new[]{1200,1400,2400}){
            var frame=regions.Choose(primary,special,at,suspendProbes:true);activeOnly&=!frame.IsSpecial;
            if(frame.IsSpecial){
                var route=regions.Observe(true,"存档预览",at,true);
                if(route.Switched)menuPage.Reset(true);
                if(route.Process)menuSubmissions++;
            }
        }
        check(activeOnly&&!regions.Special,"an active menu keeps all captures on the active region");
        check(menuSubmissions==0,"a partial menu preview cannot submit through an alternate probe");
        check(menuPage.Read("旧正文").Same,"menu suspension preserves accepted-page identity");
        regions.Observe(false,"旧正文",3000,true);
        check(regions.Choose(primary,special,3000).IsSpecial,"leaving a menu restores configured alternate probes");
        regions.Observe(true,"新的特殊演出",3000,true);
        regions.Choose(primary,special,3200);regions.Observe(false,"旧正文",3200,true);
        var resumed=regions.Choose(primary,special,4200);
        check(resumed.IsSpecial&&regions.Observe(true,"新的特殊演出",4200,true).Switched,"new special dialogue still switches after menu exit");
        check(regions.Choose(primary,special,4300,suspendProbes:true).IsSpecial,"a menu in the special region keeps that region active");
        double time=0;var events=new List<(string Phase,string Text,double At)>();
        var stable=new TextStabilizer(()=>time){Event=(_,phase,text,_)=>events.Add((phase,text,time))};
        var menuSource="「ようやく、気づいた。あたしもみんなと、同じ気持ちを持ってたんだ。\nしだって……したいんだ」";
        stable.Observe(menuSource,true);time=800;stable.Observe(menuSource,true);
        var beforeMenu=events.Count;
        stable.Suspend();time=10000;stable.Observe("しだってしたいんだ",true);
        time+=1000;stable.Observe(menuSource,true);time+=1000;stable.Observe(menuSource,true);
        check(events.Count==beforeMenu,"menu fade fragments cannot replace or resubmit the accepted source");
        stable.Suspend();time+=10000;stable.Observe("新しい台詞。",true);
        check(events.Count==beforeMenu,"a changed menu-return source first waits for confirmation");
        for(int i=0;i<4;i++){time+=800;stable.Observe("新しい台詞。",true);}
        check(events.Count(x=>x.Phase=="stable")==2&&events.Last().Text=="新しい台詞。","stable new dialogue after a menu still submits once");
        stable.Suspend();time+=10000;
        for(int i=0;i<4;i++){time+=800;stable.Observe("",true);}
        check(events.Last().Phase=="empty","a genuinely blank menu return still clears the old source");
        stable.Reset(true);events.Clear();stable.Observe(menuSource,true);time+=800;stable.Observe(menuSource,true);
        var menuTimeouts=0;stable.TimedOut=()=>menuTimeouts++;stable.Suspend();
        for(int i=0;i<12;i++){time+=800;stable.Observe("変化中"+i,true);}
        check(menuTimeouts==1&&events.Last().Phase=="empty","unstable menu-return text still times out once after eight seconds");
        stable.TimedOut=null;
        stable.Suspend();stable.Reset(true);events.Clear();time=0;
        var waves=new[]{"「はあっ……は〜〜、はっ、は～～～\nんっ」","[はあっ...は～～、はっ、は〜〜]\nんっ","「はあっ……は〜〜、はっ、は～～～\nんっ」"};
        foreach(var text in waves){stable.Observe(text,true);time+=800;}
        check(events.Any(x=>x.Phase=="stable"&&waves.Contains(x.Text)&&x.At<=1600),"decorative wave/ellipsis/quote drift stabilizes an observed source without inventing text");
        var count=events.Count;for(int i=0;i<12;i++){stable.Observe(waves[i%waves.Length],true);time+=800;}
        check(events.Count==count,"cosmetic performance drift cannot erase or retranslate a completed caption");
        stable.Reset(true);events.Clear();
        var recorded=new[]{"Гはあっ、はあっ、はあっ、はあっ、はあっは～、はっ、は〜～\n～。んつ]","[はあっ、はあっ、はあっ、はあっ、はあっ.は～、はっ、は〜〜～\nんう]","Гはあっ、はあっ、はあっ、はあっ、はあっは～、はっ、は〜〜～\n～。んつＪ"};
        foreach(var text in recorded){stable.Observe(text,true);time+=1600;}
        check(events.Any(x=>x.Phase=="stable"&&recorded.Contains(x.Text)),"the recorded Aokana wave drift sequence submits an intact observed source within three OCR samples");
        stable.Reset(true);events.Clear();
        var glyphs=new[]{"「はあっ、はあっ、は～\nんつ」","「はあっ、はあっ、は〜\nんう」","「はあっ、はあっ、は～\nんつ」"};
        foreach(var text in glyphs){stable.Observe(text,true);time+=800;}
        check(events.Any(x=>x.Phase=="stable"&&glyphs.Contains(x.Text)),"repeated whole-source support survives one intermittent kana error before the first caption");
        stable.Reset(true);events.Clear();var source="今日は海に行こう。";
        for(int i=1;i<source.Length;i++){time+=800;stable.Observe(source[..i],true);}
        check(!events.Any(x=>x.Phase=="stable"),"a slowly growing typewriter prefix is never voted into a premature final caption");
        time+=800;stable.Observe(source,true);time+=800;stable.Observe(source,true);check(events[^1].Phase=="stable"&&events[^1].Text==source,"the completed typewriter line remains eligible for normal exact stabilization");
        stable.Reset(true);events.Clear();
        for(int i=0;i<10;i++){time+=800;stable.Observe(i%2==0?"朝の海で会おう。":"夜の山で待とう。",true);}
        check(!events.Any(x=>x.Phase=="stable"),"alternating genuinely different dialogue cannot pass cosmetic agreement");
        stable.Reset(true);events.Clear();
        stable.Observe("……",true);time+=800;stable.Observe("……",true);
        stable.Observe("……\n……",true);time+=800;stable.Observe("……\n……",true);
        check(events.Count(x=>x.Phase=="stable")==2,"a new ellipsis-only row remains real dialogue rather than empty decoration");
        stable.Reset(true);events.Clear();
        foreach(var text in waves){stable.Observe(text,false);time+=800;}
        check(!events.Any(x=>x.Phase=="stable"),"HOOK/manual observations keep exact text stability semantics");
        stable.Reset(true);events.Clear();
        stable.Observe("「はあっ、は～\nんつ」",true);time+=800;stable.Observe("「はあっ、は～\nんつ」",true);
        var changed=new[]{"「はあっ、は～\nんう」","[はあっ、は〜〜\nんう]","「はあっ、は～～～\nんう」"};
        for(int i=0;i<9;i++){time+=800;stable.Observe(changed[i%changed.Length],true);}
        check(events.Any(x=>x.Phase=="stable"&&changed.Contains(x.Text)),"a persistent real kana change still advances dialogue when its decoration keeps fluctuating");
        stable.Reset(true);events.Clear();
        var complete="Гはあっ、はあっ、はあっ、はあっ、はあっ…は～、はっ、は〜～～\n〜。んつＪ";
        var missingRow="Гはあっ、はあっ、はあっ、はあっ、はあっ…は～、はっ、は～～～";
        stable.Observe(complete,true);time+=800;stable.Observe(complete,true);var completed=events.Count;
        foreach(var text in new[]{missingRow,complete,complete.Replace("Г","Ｅ"),complete,missingRow,complete}){time+=800;stable.Observe(text,true);}
        check(events.Count==completed,"live Aokana trailing-row misses and an intermittent extra quote glyph never clear a completed caption");
        for(int i=0;i<6;i++){time+=800;stable.Observe(missingRow,true);}
        check(events[^1].Phase=="stable"&&events[^1].Text==missingRow,"a genuinely persistent shortened line is eventually accepted rather than hidden forever");
        stable.Reset(true);events.Clear();
        foreach(var text in new[]{"「まだ","「まだ…","「まだ……","「まだ……行かないで」"}){time+=800;stable.Observe(text,true);}
        check(!events.Any(x=>x.Phase=="stable"),"monotonically growing ellipsis prefixes cannot manufacture whole-source agreement");
        time+=800;stable.Observe("「まだ……行かないで」",true);check(events[^1].Phase=="stable","the complete sentence after a growing ellipsis remains eligible for exact stabilization");
        stable.Reset(true);events.Clear();
        stable.Observe("「残高は1万円。」",true);time+=800;stable.Observe("「残高は1万円。」",true);
        for(int i=0;i<8;i++){time+=800;stable.Observe("「残高は-1万円。」",true);}
        check(events.Any(x=>x.Phase=="stable"&&x.Text=="「残高は-1万円。」"),"a persistent minus sign changes the actual dialogue rather than disappearing from the OCR key");
        stable.Reset(true);events.Clear();
        stable.Observe("「番号はJ」",true);time+=800;stable.Observe("「番号はJ」",true);
        for(int i=0;i<8;i++){time+=800;stable.Observe("「番号は」",true);}
        check(events.Any(x=>x.Phase=="stable"&&x.Text=="「番号は」"),"a real letter inside a closing quote cannot be stripped as a quote-shaped edge artifact");
        var pages=new PageText();var accepted="ｌはあっ、はあっ、はあっ、はあっ、はあっ…は～、はっ、は〜～～\n〜。んつ]";
        pages.Accept(accepted,pages.Read(accepted));
        check(pages.Read("Гはあっ、はあっ、はあっ、はあっ、はあっ…は～、はっ、は～～～\n〜。んつＪ").Same,
            "page delta selection cannot mistake an OCR closing-J artifact for a newly appended line");
        pages.Reset(true);pages.Accept("待って。",pages.Read("待って。"));
        check(!pages.Read("待って。\n……").Same,"shared decorative identity still preserves a genuinely appended ellipsis-only row");
        pages.Reset(true);pages.Accept(accepted,pages.Read(accepted));
        var extra=pages.Read(accepted+"\nもう大丈夫。");
        check(extra.Text=="もう大丈夫。"&&!extra.Same,"the performance identity does not drop actual appended Japanese dialogue");
        stable.Reset(true);events.Clear();stable.Observe("「今日は海へ行こう。」",true);time+=800;stable.Observe("「今日は海へ行こう。」",true);
        for(int i=0;i<6;i++){time+=800;stable.Observe("「今日は海へ行こう。」\n……",true);}
        check(events.Any(e=>e.Phase=="stable"&&e.Text.EndsWith("\n……")),"a stable body followed by a new ellipsis-only row reaches the capture event stream");
        pages.Reset(true);pages.Accept("「記号はこれです。」",pages.Read("「記号はこれです。」"));
        check(!pages.Read("「記号はこれです。」\nJ").Same,"an independent appended J row is real text rather than an outer closing-quote artifact");
        stable.Reset(true);events.Clear();stable.Observe(complete,true);time+=800;stable.Observe(complete,true);completed=events.Count;
        foreach(var text in new[]{complete.Replace("んつＪ","[ćＶ～"),complete,missingRow,complete.Replace("Г","Ｅ"),complete}){time+=800;stable.Observe(text,true);}
        check(events.Count==completed,"an intermittent tiny tail-row corruption retains the completed performance without inventing replacement words");
        pages.Reset(true);var body="「今日は海へ行こう。」";pages.Accept(body,pages.Read(body));
        var punctuation=pages.Read(body+"\n...");
        check(punctuation.Text=="..."&&punctuation.FirstLine==1&&!punctuation.Same,
            "an appended ASCII ellipsis row keeps its exact OCR text instead of disappearing as wrapping noise");
        pages.Accept(body+"\n...",punctuation);
        check(pages.Read(body+"\n...").Same,"the accepted ASCII ellipsis row is not submitted twice");
        pages.Reset(true);var question="待って。\nそうなの？";pages.Accept(question,pages.Read(question));
        var exclamation=pages.Read("待って。\nそうなの！");
        check(exclamation.Text=="待って。\nそうなの！"&&!exclamation.Same,
            "a multiline question changing to an exclamation keeps the changed source");
    }
}
