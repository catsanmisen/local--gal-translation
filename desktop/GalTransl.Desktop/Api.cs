using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace GalTransl.Desktop;

public sealed class Api:IDisposable {
    readonly HttpClient http=new(new HttpClientHandler{UseProxy=false}){Timeout=TimeSpan.FromSeconds(20)};
    readonly HttpClient stream=new(new HttpClientHandler{UseProxy=false}){Timeout=Timeout.InfiniteTimeSpan};
    string? token;
    public string ClientId {get;}=Guid.NewGuid().ToString();
    public string Base {get;}
    public string BackendRoot {get;private set;}="";
    public string DatabasePath {get;private set;}="";
    public string InstanceId {get;private set;}="";
    public Api(int port){Base=$"http://127.0.0.1:{port}";http.BaseAddress=new Uri(Base);stream.BaseAddress=http.BaseAddress;}
    public async Task Connect(CancellationToken cancellation=default){
        using var data=JsonDocument.Parse(await http.GetStringAsync("/bootstrap",cancellation));
        BackendProtocol.Verify(data.RootElement);token=data.RootElement.GetProperty("token").GetString();
        BackendRoot=data.RootElement.GetProperty("backend_root").GetString()!;
        DatabasePath=data.RootElement.GetProperty("database_path").GetString()!;
        InstanceId=data.RootElement.GetProperty("instance_id").GetString()!;
    }
    void Authenticate(HttpRequestMessage req){req.Headers.Authorization=new AuthenticationHeaderValue("Bearer",token);req.Headers.Add("X-Client-Id",ClientId);}
    public async Task<JsonElement> Call(string path,string method="GET",object? body=null,CancellationToken token=default){
        using var req=new HttpRequestMessage(new HttpMethod(method),"/api/v1"+path);
        Authenticate(req);
        if(body!=null)req.Content=new StringContent(JsonSerializer.Serialize(body,JsonConfig.Options),Encoding.UTF8,"application/json");
        using var response=await http.SendAsync(req,token);
        var value=JsonSerializer.Deserialize<JsonElement>(await response.Content.ReadAsStringAsync(token));
        if(!response.IsSuccessStatusCode)throw new ApiError(value.TryGetProperty("error",out var e)?e.GetProperty("message").GetString()!:"后台连接失败",value);
        return value;
    }
    public async Task<JsonElement> Ocr(byte[] png,string gameId,int epoch,CancellationToken token){
        using var req=new HttpRequestMessage(HttpMethod.Post,"/api/v1/ocr-frame");
        Authenticate(req);
        req.Headers.Add("X-Game-Session",gameId);req.Headers.Add("X-Epoch",epoch.ToString());
        req.Content=new ByteArrayContent(png);req.Content.Headers.ContentType=new MediaTypeHeaderValue("image/png");
        using var response=await http.SendAsync(req,token);
        var value=JsonSerializer.Deserialize<JsonElement>(await response.Content.ReadAsStringAsync(token));
        if(!response.IsSuccessStatusCode)throw new ApiError(value.GetProperty("error").GetProperty("message").GetString()!,value);
        return value;
    }
    public async Task Subscribe(Action<JsonElement> receive,CancellationToken token){
        while(!token.IsCancellationRequested){
            try {
                using var req=new HttpRequestMessage(HttpMethod.Get,"/api/v1/subtitle/events");
                Authenticate(req);
                using var response=await stream.SendAsync(req,HttpCompletionOption.ResponseHeadersRead,token);response.EnsureSuccessStatusCode();
                using var reader=new StreamReader(await response.Content.ReadAsStreamAsync(token),Encoding.UTF8);
                while(await reader.ReadLineAsync(token) is string line)if(line.StartsWith("data: "))receive(JsonSerializer.Deserialize<JsonElement>(line[6..]));
            } catch(OperationCanceledException) when(token.IsCancellationRequested){return;}
              catch(Exception){await Task.Delay(1000,token);}
        }
    }
    public void Dispose(){http.Dispose();stream.Dispose();}
}
public sealed class ApiError(string message,JsonElement data):Exception(message){public JsonElement DataJson {get;}=data;}
