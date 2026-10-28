using System.Security.Cryptography;
using System.Text.Json;

namespace GalTransl.Desktop;

public static class Assets {
    public static bool Validate(string folder){
        try{
            using var manifest=JsonDocument.Parse(File.ReadAllText(Path.Combine(folder,"manifest.json")));
            foreach(var file in manifest.RootElement.GetProperty("files").EnumerateArray()){
                var path=Path.GetFullPath(Path.Combine(folder,file.GetProperty("path").GetString()!));
                if(!path.StartsWith(Path.GetFullPath(folder)+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))return false;
                using var stream=File.OpenRead(path);var hash=Convert.ToHexString(SHA256.HashData(stream));
                if(!hash.Equals(file.GetProperty("sha256").GetString(),StringComparison.OrdinalIgnoreCase))return false;
            }return true;
        }catch(Exception e) when(e is IOException or JsonException or KeyNotFoundException){return false;}
    }
}
