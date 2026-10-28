using System.Globalization;
using System.Text.RegularExpressions;
namespace GalTransl.Desktop;

public sealed record HookText(string Handle,int Pid,string Address,string Context,string Context2,string Name,string Code,string Text);
public static class HookProtocol {
    // Upstream hook names may contain ':' and '['; the code is the field
    // beginning H/R with an @ address, and may contain a module ':' itself.
    static readonly Regex Header=new(@"^\[([0-9A-F]{1,16}):([0-9A-F]{1,8}):([0-9A-F]{1,16}):([0-9A-F]{1,16}):([0-9A-F]{1,16}):(.*?):([HR][^:\]\s]*@[^\]\s]+)\] (.*)$",RegexOptions.IgnoreCase|RegexOptions.Compiled);
    static readonly Regex EmbeddedHeader=new(@"\[[0-9A-F]{1,16}:[0-9A-F]{1,8}:[0-9A-F]{1,16}:[0-9A-F]{1,16}:[0-9A-F]{1,16}:",RegexOptions.IgnoreCase|RegexOptions.Compiled);
    public static bool LooksLikeHeader(string line)=>Regex.IsMatch(line,@"^\[[0-9A-F]+:",RegexOptions.IgnoreCase)||EmbeddedHeader.IsMatch(line);
    public static bool CanRestore(HookSelection selected){
        var at=selected.Code.LastIndexOf('@');
        bool Fixed(string context)=>context.Length==0||(ulong.TryParse(context,NumberStyles.HexNumber,CultureInfo.InvariantCulture,out var number)&&number<=0xffff);
        return at>0&&selected.Code.Count(c=>c=='@')==1&&selected.Code[0] is 'H' or 'R'&&
            !selected.Code.Any(char.IsWhiteSpace)&&Regex.IsMatch(selected.Code[(at+1)..],@"^[0-9A-F]+:[^:\s]+(?::[^\s]+)?$",RegexOptions.IgnoreCase)&&Fixed(selected.Context)&&Fixed(selected.Context2);
    }
    public static bool Readable(string text)=>text.Length<=2000&&!text.Contains('\0')&&!EmbeddedHeader.IsMatch(text)&&
        text.Count(c=>c=='\uFFFD')<=Math.Max(1,text.Length/20)&&
        text.Count(c=>char.IsControl(c)&&c is not '\n' and not '\r' and not '\t')<=Math.Max(3,text.Length/100);
    public static HookText? Parse(string line){
        if(line.Length>3000)return null;var m=Header.Match(line);
        if(!m.Success||m.Groups[6].Length>400||m.Groups[7].Length>400||
           !int.TryParse(m.Groups[2].Value,NumberStyles.HexNumber,CultureInfo.InvariantCulture,out var pid)||pid<0||!Readable(m.Groups[8].Value))return null;
        return new(m.Groups[1].Value,pid,m.Groups[3].Value,m.Groups[4].Value,m.Groups[5].Value,m.Groups[6].Value,m.Groups[7].Value,m.Groups[8].Value);
    }
    public static HookText? Append(HookText pending,string line){
        var text=pending.Text+"\n"+line;return LooksLikeHeader(line)||!Readable(text)?null:pending with{Text=text};
    }
}
