using System.Text.Json;
namespace GalTransl.Desktop;
public sealed class BackendCompatibilityException(string message):Exception(message);
public static class BackendProtocol {
    public static void Verify(JsonElement data){
        if(data.ValueKind!=JsonValueKind.Object||!data.TryGetProperty("desktop_protocol",out var version)||version.ValueKind!=JsonValueKind.Number||!version.TryGetInt32(out var number)||number!=2||
           !data.TryGetProperty("api",out var api)||api.ValueKind!=JsonValueKind.String||api.GetString()!="/api/v1"||!data.TryGetProperty("token",out var token)||token.ValueKind!=JsonValueKind.String||string.IsNullOrEmpty(token.GetString()))
            throw new BackendCompatibilityException("后台版本不兼容，请退出旧客户端后启动此版本。不会替换其他服务。");
        foreach(var name in new[]{"backend_root","database_path","instance_id"})
            if(!data.TryGetProperty(name,out var value)||value.ValueKind!=JsonValueKind.String||string.IsNullOrWhiteSpace(value.GetString()))
                throw new BackendCompatibilityException("后台缺少目录与实例身份，不会接入未知服务。");
    }
    public static void VerifyLocation(string actualRoot,string actualDatabase,string expectedRoot,string expectedDatabase){
        static string Normalize(string value)=>Path.TrimEndingDirectorySeparator(Path.GetFullPath(value));
        if(!string.Equals(Normalize(actualRoot),Normalize(expectedRoot),StringComparison.OrdinalIgnoreCase)||
            !string.Equals(Normalize(actualDatabase),Normalize(expectedDatabase),StringComparison.OrdinalIgnoreCase))
            throw new BackendCompatibilityException("此端口的后台属于其他程序目录或数据库，请使用独立端口。不会修改另一份数据。");
    }
}
