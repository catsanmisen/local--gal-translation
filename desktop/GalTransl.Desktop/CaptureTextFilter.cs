using System.Text;
using System.Text.RegularExpressions;
namespace GalTransl.Desktop;

public static class CaptureTextFilter {
    // Require several exact UI labels together, so kanji-only short dialogue is retained.
    static readonly HashSet<string> Menu=["セーブ","ロード","コンフィグ","タイトルへ戻る","メニューを閉じる"];
    static readonly HashSet<string> Config=["ランゲージ","スクリーンモード","解像度","メッセージスピード","オートスピード","BGMボリューム","SEボリューム"];
    static readonly Regex ChapterLabel=new(@"^(?:ゲームを最初から開始|第[一二三四五六七八九十百0-9０-９]+話から開始|次のページへ進む\s*(?:[>＞〉]{2}|[ンソ]{2}))$",RegexOptions.Compiled);
    public static string Dialogue(string text){
        if(!text.EnumerateRunes().Any(r=>r.Value is >=0x3040 and <=0x30ff or >=0x3400 and <=0x9fff or >=0xf900 and <=0xfaff or >=0x20000 and <=0x323af))return "";
        var lines=text.Split('\n').Select(s=>s.Trim()).ToHashSet();
        if(lines.Count>0&&lines.All(s=>s.Length==0||ChapterLabel.IsMatch(s)))return "";
        return lines.Count(Menu.Contains)>=3||lines.Count(Config.Contains)>=3?"":text;
    }
}
