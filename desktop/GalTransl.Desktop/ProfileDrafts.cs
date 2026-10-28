namespace GalTransl.Desktop;

public sealed class ProfileDrafts {
    sealed class Draft {public Dictionary<string,string> Keys=new();public bool Dirty;}
    readonly Dictionary<string,Draft> values=new();
    public Dictionary<string,string> Read(Profile p){
        if(!values.TryGetValue(p.Id,out var d))values[p.Id]=d=new();
        if(!d.Dirty)d.Keys=new(p.Game.Hotkeys);
        return new(d.Keys);
    }
    public void Edit(string id,Dictionary<string,string> keys)=>values[id]=new(){Keys=new(keys),Dirty=true};
    public void Saved(string id)=>values.Remove(id);
    public static Profile? Selected(Profile? explicitSelection,Profile? active)=>explicitSelection??active;
    public static bool CanRebind(Profile selected,Profile? active,GameWindow? window)=>window!=null&&active?.Id==selected.Id&&
        string.Equals(selected.Game.Executable,window.Executable,StringComparison.OrdinalIgnoreCase);
}
