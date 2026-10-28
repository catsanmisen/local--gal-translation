using System.Text.Json;
using System.Text.Json.Serialization;

namespace GalTransl.Desktop;

public sealed record ModelPreferences {
    [JsonPropertyName("model_mode")] public string Mode {get;init;}="auto";
    [JsonPropertyName("gpu_reserve_mib")] public int Reserve {get;init;}=2048;
    [JsonPropertyName("wallpaper_relief")] public bool WallpaperRelief {get;init;}=true;
}

public sealed class Profile {
    public string Id {get;set;}="";
    public string Name {get;set;}="";
    public Dictionary<string,JsonElement> Prefs {get;set;}=new();
    public JsonElement[] Glossary {get;set;}=[];
    public GameConfig Game {get;set;}=new();
    [JsonPropertyName("glossary_version")] public int GlossaryVersion {get;set;}
    public int Font=>Prefs.TryGetValue("font",out var f)?f.GetInt32():24;
    public double Opacity=>Prefs.TryGetValue("opacity",out var f)?f.GetInt32()/100.0:.62;
}
public sealed class GameConfig {
    public string? Executable {get;set;}
    [JsonPropertyName("input_mode")] public string InputMode {get;set;}="ocr";
    public Region? Region {get;set;}
    [JsonPropertyName("dialogue_box")] public Region? DialogueBox {get;set;}
    [JsonPropertyName("special_region")] public Region? SpecialRegion {get;set;}
    [JsonPropertyName("hide_input")] public string HideInput {get;set;}="none";
    public Anchor Anchor {get;set;}=new();
    [JsonPropertyName("subtitle_placement")] public string SubtitlePlacement {get;set;}="auto";
    public HookSelection? Hook {get;set;}
    public bool Enabled {get;set;}=true;
    [JsonPropertyName("auto_recovery")] public bool AutoRecovery {get;set;}=true;
    public Dictionary<string,string> Hotkeys {get;set;}=new(){{"visibility","Ctrl+Shift+H"},{"pause","Ctrl+Shift+P"},{"reset","Ctrl+Shift+R"},{"backlog","Ctrl+Shift+B"}};
}
public sealed record Region(double X,double Y,double Width,double Height);
public sealed class Anchor {public double Dx {get;set;} public double Dy {get;set;}}
public sealed class HookSelection {public string Code {get;set;}="";public string Name {get;set;}="";public string Context {get;set;}="";[JsonPropertyName("context2")] public string Context2 {get;set;}="";}
public sealed record GameWindow(nint Handle,int Pid,string Executable,string Title,PixelRect Client);
public readonly record struct PixelRect(double X,double Y,double Width,double Height) {
    public double Right=>X+Width;public double Bottom=>Y+Height;
    public PixelRect Region(Region r)=>new(X+Width*r.X,Y+Height*r.Y,Width*r.Width,Height*r.Height);
}
public sealed record Caption(string Ja,string Zh,string State,string? RequestId,int Epoch,int Sequence,string? Reason,double? ElapsedMs){
    public bool HasSource=>!string.IsNullOrWhiteSpace(Ja)&&State is "capturing" or "streaming" or "final" or "error" or "paused";
}
public static class JsonConfig {
    public static readonly JsonSerializerOptions Options=new(){PropertyNamingPolicy=JsonNamingPolicy.SnakeCaseLower,PropertyNameCaseInsensitive=true,DefaultIgnoreCondition=JsonIgnoreCondition.WhenWritingNull};
}
