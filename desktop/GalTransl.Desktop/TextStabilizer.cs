using System.Diagnostics;

namespace GalTransl.Desktop;

public sealed class TextStabilizer {
    string? candidate;double changed;bool emitted;int samples;int line;
    string? variation;double variationAt;int variationSamples;
    double? unsettledAt,emptyAt;bool recovering,menu;
    readonly Queue<(string Text,string Key,double At)> observations=new();
    readonly Func<double> now;
    public TextStabilizer(Func<double>? clock=null){now=clock??(()=>Stopwatch.GetTimestamp()*1000.0/Stopwatch.Frequency);}
    public Action<int,string,string,double>? Event {get;set;}
    public Action? TimedOut {get;set;}
    public void Suspend(){menu=true;variation=null;emptyAt=unsettledAt=null;observations.Clear();}
    public void Reset(bool newIdentity=false){candidate=null;emitted=false;samples=0;variation=null;unsettledAt=emptyAt=null;recovering=menu=false;observations.Clear();if(newIdentity)line=0;}
    public void Observe(string raw,bool tolerateOcrNoise=false){
        var at=now();
        if(tolerateOcrNoise&&menu){
            // A menu fade can expose one partial row. Keep the accepted source
            // until it returns, or a different whole observation repeats.
            if(emitted&&candidate!=null&&EquivalentPerformance(candidate,raw))unsettledAt=null;
            else {
                unsettledAt??=at;
                if(at-unsettledAt>=8000)emitted=false;
                else {
                    if(variation!=raw){variation=raw;variationAt=at;variationSamples=1;return;}
                    if(++variationSamples<2||at-variationAt<400)return;
                }
            }
            menu=false;variation=null;
        }
        if(tolerateOcrNoise){
            var key=PerformanceKey(raw);
            if(emitted&&candidate!=null&&EquivalentPerformance(candidate,raw)){emptyAt=null;variation=null;return;}
            if(string.IsNullOrWhiteSpace(raw))observations.Clear();
            else if(!emitted){
                // Require repeated whole-source support, not a one-glyph growing
                // prefix. Decoration can vary; the submitted source is always
                // one complete OCR observation, never a synthesized consensus.
                if(observations.Count>0){
                    var last=observations.Last();
                    if(raw.Length>last.Text.Length&&raw.StartsWith(last.Text,StringComparison.Ordinal)
                        ||last.Key!=key&&!Substitution(last.Key,key))observations.Clear();
                }
                observations.Enqueue((raw,key,at));
                while(observations.Count>5||observations.Count>0&&at-observations.Peek().At>4000)observations.Dequeue();
                var support=observations.Where(x=>x.Key==key||Substitution(x.Key,key)).ToList();
                if(support.Count>=3&&support.Count(x=>x.Key==key)>=2&&at-support[0].At>=600){
                    if(raw!=candidate){candidate=raw;line++;if(!recovering)Event?.Invoke(line,"preview",raw,0);}
                    changed=support[0].At;samples=support.Count;emitted=true;recovering=false;unsettledAt=null;
                    observations.Clear();Event?.Invoke(line,"stable",raw,at-changed);return;
                }
            }
        }
        // A transient OCR miss must not erase a completed line. A genuinely
        // blank page still clears after a short, bounded confirmation period.
        if(tolerateOcrNoise&&emitted&&candidate!=null&&string.IsNullOrWhiteSpace(raw)){
            emptyAt??=at;if(at-emptyAt<400)return;
        }else emptyAt=null;
        // After 8 seconds clear an unstable candidate; remain quiet until text
        // stabilizes, then accept it with a fresh increasing line ID.
        if(tolerateOcrNoise&&!emitted&&!recovering&&unsettledAt is double started&&at-started>=8000){
            recovering=true;line++;TimedOut?.Invoke();Event?.Invoke(line,"empty","",at-started);
        }
        // A blinking advance marker can intermittently hide a detected Japanese full stop.
        // Keep the observed punctuated form; do not treat its disappearance as a new line.
        if(candidate!=null&&raw!=candidate&&raw==candidate.TrimEnd('。'))raw=candidate;
        else if(candidate!=null&&raw!=candidate&&candidate==raw.TrimEnd('。')){
            if(emitted)return;
            candidate=raw;line++;if(!recovering)Event?.Invoke(line,"preview",raw,0);
        }
        if(tolerateOcrNoise&&emitted&&candidate!=null&&raw!=candidate&&(MinorOcrDifference(candidate,raw)
            ||DecorationRows(candidate)==DecorationRows(raw)&&MinorOcrDifference(PerformanceKey(candidate),PerformanceKey(raw))||ShortTrailingRowDifference(candidate,raw))){
            var variantKey=PerformanceKey(raw);
            if(variation!=variantKey){variation=variantKey;variationAt=at;variationSamples=1;return;}
            variationSamples++;
            if(at-variationAt<1500||variationSamples<3)return;
            // A persistent minor change is accepted as new dialogue.
        }else variation=null;
        if(raw!=candidate){
            candidate=raw;changed=at;emitted=false;samples=1;line++;
            if(string.IsNullOrWhiteSpace(raw)){unsettledAt=null;recovering=false;Event?.Invoke(line,"empty",raw,0);}
            else{unsettledAt??=at;if(!recovering)Event?.Invoke(line,"preview",raw,0);}return;
        }
        samples++;var delay=at-changed;
        var trimmed=raw.TrimEnd();var end=trimmed.Length>0&&"。！？!?…」』）)".Contains(trimmed[^1]);
        if(!emitted&&samples>=2&&!string.IsNullOrWhiteSpace(raw)&&delay>=(end?300:600)){
            emitted=true;recovering=false;unsettledAt=null;observations.Clear();Event?.Invoke(line,"stable",raw,delay);
        }
    }
    // HOOK produces text on change rather than continuously; advance its quiet timer.
    public void Tick(){if(candidate!=null)Observe(candidate);}
    static int DecorationRows(string value)=>value.Split('\n').Count(row=>row.Length>0&&!row.Any(char.IsLetterOrDigit));
    internal static bool EquivalentPerformance(string a,string b)=>PerformanceKey(a)==PerformanceKey(b)&&DecorationRows(a)==DecorationRows(b);
    internal static string PerformanceKey(string raw){
        var text=raw.Normalize(System.Text.NormalizationForm.FormKC);
        if(text.Any(c=>c is >= '\u3040' and <= '\u30ff')&&text.Length>0){
            // Remove only an outer quote-shaped OCR artifact. A letter before
            // an actual closing quote is dialogue, not an edge to trim again.
            var quoted="Гl「[".Contains(text[0]);
            if(quoted&&text.EndsWith('J')&&text.Split('\n')[^1].Trim().Length>1)text=text[..^1];
            if(text.Length>0&&"Гl".Contains(text[0]))text=text[1..];
        }
        var key=new string(text.Where((c,i)=>!char.IsWhiteSpace(c)&&!"~〜～「」『』[]【】()（）\"'。…".Contains(c)
            &&(!".,、".Contains(c)||i>0&&i+1<text.Length&&char.IsDigit(text[i-1])&&char.IsDigit(text[i+1]))).ToArray());
        // Ellipsis-only dialogue and new visual rows are still real events.
        return key.Length>0?key:text;
    }
    static bool Substitution(string a,string b)=>a.Length>=4&&a.Length==b.Length&&a.Zip(b).Count(x=>x.First!=x.Second)==1
        &&!a.Where(char.IsDigit).Except(b.Where(char.IsDigit)).Any()&&!b.Where(char.IsDigit).Except(a.Where(char.IsDigit)).Any()
        &&new string(a.Where(c=>"?!".Contains(c)).ToArray())==new string(b.Where(c=>"?!".Contains(c)).ToArray());
    static bool ShortTrailingRowDifference(string complete,string observed){
        var rows=complete.Split('\n');
        var seen=observed.Split('\n');
        if(rows.Length<2||seen.Length<rows.Length-1||seen.Length>rows.Length)return false;
        var head=PerformanceKey(string.Join("\n",rows[..^1]));var whole=PerformanceKey(complete);
        var key=PerformanceKey(seen.Length==rows.Length?string.Join("\n",seen[..^1]):observed);
        if(seen.Length==rows.Length){
            var full=PerformanceKey(observed);var ending=full.StartsWith(key,StringComparison.Ordinal)?full[key.Length..]:PerformanceKey(seen[^1]);
            if(ending.Length>4)return false;
        }
        var tail=whole.StartsWith(head,StringComparison.Ordinal)?whole[head.Length..]:PerformanceKey(rows[^1]);
        // Some text effects intermittently lose only a tiny final row. Retain
        // the completed source for the existing bounded minor-change grace;
        // a persistent shortened page still progresses normally afterwards.
        return head.Length>=16&&tail.Length is >0 and <=4&&head.Length>=tail.Length*8&&(head==key||MinorOcrDifference(head,key));
    }
    static bool MinorOcrDifference(string a,string b){
        if(Math.Min(a.Length,b.Length)<4||Math.Abs(a.Length-b.Length)>1)return false;
        if(a.Length==b.Length){var differences=a.Zip(b).Count(pair=>pair.First!=pair.Second);return differences<= (a.Length>=80?2:1);}
        if(a.Length>b.Length)(a,b)=(b,a);
        var i=0;var j=0;var skipped=false;
        while(i<a.Length&&j<b.Length){if(a[i]==b[j]){i++;j++;}else{if(skipped)return false;skipped=true;j++;}}
        return true;
    }
}
