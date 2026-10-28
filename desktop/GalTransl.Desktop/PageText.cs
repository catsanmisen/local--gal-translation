namespace GalTransl.Desktop;

public sealed class PageText {
    string? accepted;string latest="";int latestLine;bool replay;
    public sealed record Selection(string Text,int FirstLine,bool Same);
    public void Reset(bool newScene){if(newScene){accepted=null;latest="";latestLine=0;}replay=!newScene;}
    public Selection Read(string page){
        if(accepted==null)return new(page,0,false);
        if(page==accepted)return new(latest,latestLine,!replay);
        // Use the same decorative identity as the stability gate. Otherwise a
        // quote-shaped final J can be misread as an NVL appended character.
        if(TextStabilizer.EquivalentPerformance(accepted,page))return new(latest,latestLine,!replay);
        // Detect exact appended rows before the wrapping key removes punctuation.
        // A new "..." or "?!" row is dialogue even when it adds no letter glyphs.
        if(page.StartsWith(accepted,StringComparison.Ordinal)){
            var cut=accepted.Length;
            if(cut<page.Length&&page[cut]=='。'&&!accepted.EndsWith('。'))cut++;
            // Only a new rendered row denotes NVL-page accumulation. A similar new
            // single-line sentence must keep its complete source.
            if(cut<page.Length&&page[cut]=='\n'){
                while(cut<page.Length&&char.IsWhiteSpace(page[cut]))cut++;
                if(cut==page.Length)return new(latest,latestLine,!replay);
                return new(page[cut..],page[..cut].Count(c=>c=='\n'),false);
            }
        }
        var oldKey=Key(accepted);var (nextKey,positions)=MappedKey(page);
        // Quotes/punctuation and visual wrapping can fluctuate without a new line.
        if(oldKey.Length>0&&oldKey==nextKey){
            string Intent(string s)=>new(s.Where(c=>"?!？！".Contains(c)).Select(c=>c=='？'?'?':c=='！'?'!':c).ToArray());
            if(Intent(accepted)!=Intent(page))return new(page,0,false);
            return new(latest,latestLine,!replay);
        }
        // A multiline NVL page may grow at the end of an existing visual row.
        // Align its existing content, then retain the exact new raw characters.
        // A standalone similar replacement sentence keeps its complete source.
        if(oldKey.Length>0&&(accepted.Contains('\n')||page.Contains('\n'))&&nextKey.Length>oldKey.Length){
            var prefix=nextKey.StartsWith(oldKey,StringComparison.Ordinal)?oldKey.Length:AlignedPrefix(oldKey,nextKey);
            if(prefix>0&&prefix<positions.Count){
                var cut=positions[prefix-1]+1;
                while(cut<page.Length&&(char.IsWhiteSpace(page[cut])||"。．.,、，」』〕］]）)！？!?".Contains(page[cut])))cut++;
                if(cut<page.Length)return new(page[cut..],page[..cut].Count(c=>c=='\n'),false);
            }
        }
        var previous=accepted.Split('\n');var current=page.Split('\n');
        // Old NVL rows may fluctuate slightly while new rows are appended.
        // This tolerance applies only to an appended row; a replaced single line
        // or a larger prefix change must retain its complete source.
        if(current.Length>previous.Length){
            string Normalize(IEnumerable<string> rows)=>string.Join("\n",rows.Select(s=>s.Trim().TrimEnd('。')));
            var oldPrefix=Normalize(previous);var nextPrefix=Normalize(current.Take(previous.Length));
            if(oldPrefix==nextPrefix||SmallOcrDifference(oldPrefix,nextPrefix)){
                var next=string.Join("\n",current.Skip(previous.Length));
                if(!string.IsNullOrWhiteSpace(next))return new(next,previous.Length,false);
            }
        }
        return new(page,0,false);
    }
    static string Key(string text)=>MappedKey(text).Key;
    static (string Key,List<int> Positions) MappedKey(string text){
        var key=new System.Text.StringBuilder();var positions=new List<int>();
        for(var i=0;i<text.Length;i++){
            var c=text[i];
            if(char.IsWhiteSpace(c)||"「」『』〔〕［］[]（）()\"'。．.,、，！？!?".Contains(c))continue;
            key.Append(c);positions.Add(i);
        }
        return(key.ToString(),positions);
    }
    static int AlignedPrefix(string oldKey,string nextKey){
        if(oldKey.Length<12)return 0;
        var limit=oldKey.Length>=80?2:1;
        // Reuse the conservative glyph budget only when new text follows.
        foreach(var length in new[]{oldKey.Length,oldKey.Length-1,oldKey.Length+1,oldKey.Length-2,oldKey.Length+2}){
            if(length>0&&length<nextKey.Length&&Math.Abs(length-oldKey.Length)<=limit&&SmallOcrDifference(oldKey,nextKey[..length]))return length;
        }
        return 0;
    }
    static bool SmallOcrDifference(string a,string b){
        var length=Math.Min(a.Length,b.Length);if(length<12)return false;
        var limit=length>=80?2:1;if(Math.Abs(a.Length-b.Length)>limit)return false;
        var previous=Enumerable.Range(0,b.Length+1).ToArray();
        for(var i=1;i<=a.Length;i++){
            var next=new int[b.Length+1];next[0]=i;
            for(var j=1;j<=b.Length;j++)next[j]=Math.Min(Math.Min(previous[j]+1,next[j-1]+1),previous[j-1]+(a[i-1]==b[j-1]?0:1));
            if(next.Min()>limit)return false;previous=next;
        }
        return previous[^1]<=limit;
    }
    public void Accept(string page,Selection selection){accepted=page;latest=selection.Text;latestLine=selection.FirstLine;replay=false;}
}
