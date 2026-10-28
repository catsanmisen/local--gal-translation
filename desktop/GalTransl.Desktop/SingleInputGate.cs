namespace GalTransl.Desktop;

// No OS dependency: a physical press toggles once, never on auto-repeat,
// modified chords, settings controls, or an unrelated foreground app.
public sealed class SingleInputGate {
    public sealed record Choice(string Value,string Label);
    public static readonly Choice[] Choices=[new("none","关闭单键隐藏"),new("mouse_left","鼠标左键"),new("mouse_right","鼠标右键"),new("mouse_middle","鼠标中键"),
        ..Enumerable.Range('A',26).Select(c=>new Choice("key:"+(char)c,"字母 "+(char)c)),
        ..Enumerable.Range('0',10).Select(c=>new Choice("key:"+(char)c,"数字 "+(char)c)),
        new("key:Space","空格"),new("key:Tab","Tab"),new("key:Escape","Esc"),
        ..Enumerable.Range(1,12).Select(c=>new Choice("key:F"+c,"F"+c))];
    string selected="none";bool down;
    public void Configure(string value){if(selected==value)return;selected=value;down=false;}
    public bool Observe(string value,bool pressed,bool enabled,bool modified=false,bool overControls=false){
        if(selected=="none"||value!=selected)return false;
        if(!pressed){down=false;return false;}
        var repeated=down;down=true;return !repeated&&enabled&&!modified&&!overControls;
    }
    public static string? Key(int vk)=>vk is >=65 and <=90 or >=48 and <=57?"key:"+(char)vk:
        vk is >=112 and <=123?"key:F"+(vk-111):vk switch{32=>"key:Space",9=>"key:Tab",27=>"key:Escape",_=>null};
}
