using System.Text.Json;
namespace GalTransl.Desktop;

public static class SnapshotGate {
    static bool Number(JsonElement value,string key,out int number){number=0;return value.TryGetProperty(key,out var item)&&item.ValueKind==JsonValueKind.Number&&item.TryGetInt32(out number);}
    public static bool Accept(JsonElement snapshot,string? gameId,bool boundWindow,int epoch,Caption shown){
        if(snapshot.ValueKind!=JsonValueKind.Object||!snapshot.TryGetProperty("subtitle",out var subtitle)||subtitle.ValueKind!=JsonValueKind.Object)return false;
        if(gameId==null)return !boundWindow;
        if(!snapshot.TryGetProperty("game_session",out var game)||game.ValueKind!=JsonValueKind.Object||
           !game.TryGetProperty("game_session_id",out var id)||id.ValueKind!=JsonValueKind.String||id.GetString()!=gameId||
           !Number(game,"epoch",out var scopeEpoch)||scopeEpoch<epoch)return false;
        if(!Number(subtitle,"epoch",out var textEpoch)||textEpoch!=scopeEpoch||textEpoch<shown.Epoch||
           !Number(subtitle,"sequence",out var sequence)||sequence<0)return false;
        if(textEpoch==shown.Epoch&&sequence<shown.Sequence)return false;
        if(textEpoch==shown.Epoch&&sequence==shown.Sequence&&shown.RequestId!=null&&
           subtitle.TryGetProperty("request_id",out var request)&&request.ValueKind==JsonValueKind.String&&request.GetString()!=shown.RequestId)return false;
        return true;
    }
}
