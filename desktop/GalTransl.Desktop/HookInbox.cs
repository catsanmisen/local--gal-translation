namespace GalTransl.Desktop;

// Scanner traffic must not enqueue an unbounded number of WPF callbacks.
public sealed class HookInbox {
    readonly int limit;readonly object gate=new();readonly Dictionary<string,HookText> pending=new();HookText? selected;
    public HookInbox(int capacity=128){limit=capacity;}
    public void Put(HookText text,bool isSelected=false){lock(gate){
        if(isSelected)selected=text;
        if(!pending.ContainsKey(text.Handle)&&pending.Count>=limit)pending.Remove(pending.Keys.First());
        pending[text.Handle]=text;
    }}
    public List<HookText> Drain(){lock(gate){
        var result=pending.Values.ToList();
        if(selected!=null){result.RemoveAll(x=>x.Handle==selected.Handle);result.Add(selected);}
        pending.Clear();selected=null;return result;
    }}
    public void Clear(){lock(gate){pending.Clear();selected=null;}}
}
