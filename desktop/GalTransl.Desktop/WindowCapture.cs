using System.Runtime.InteropServices;
using Windows.Graphics.Capture;
using Windows.Graphics.DirectX;
using Windows.Graphics.DirectX.Direct3D11;
using Windows.Graphics.Imaging;
using Windows.Storage.Streams;

namespace GalTransl.Desktop;

// Capture the original HWND, not the monitor or the translated overlay.
public sealed class WindowCapture:IDisposable {
    [ComImport,Guid("3628E81B-3CAC-4C60-B7F4-23CE0E0C3356"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IItemInterop {
        [PreserveSig] int CreateForWindow(nint window,in Guid iid,out nint result);
        [PreserveSig] int CreateForMonitor(nint monitor,in Guid iid,out nint result);
    }
    [DllImport("d3d11.dll")] static extern int D3D11CreateDevice(nint adapter,int type,nint software,uint flags,nint levels,uint count,uint version,out nint device,out int level,out nint context);
    [DllImport("d3d11.dll")] static extern int CreateDirect3D11DeviceFromDXGIDevice(nint dxgi,out nint device);
    [DllImport("combase.dll",CharSet=CharSet.Unicode)] static extern int WindowsCreateString(string text,int length,out nint value);
    [DllImport("combase.dll")] static extern int WindowsDeleteString(nint value);
    [DllImport("combase.dll")] static extern int RoGetActivationFactory(nint name,in Guid iid,out nint factory);
    readonly GraphicsCaptureItem item;readonly IDirect3DDevice device;readonly Direct3D11CaptureFramePool pool;readonly GraphicsCaptureSession session;
    readonly object gate=new();Direct3D11CaptureFrame? latest;bool disposed;
    readonly nint window;
    Windows.Graphics.SizeInt32 size;
    public static bool Supported=>GraphicsCaptureSession.IsSupported();
    public WindowCapture(nint hwnd){
        window=hwnd;
        var className="Windows.Graphics.Capture.GraphicsCaptureItem";WindowsCreateString(className,className.Length,out var hs);
        try {
            var interopId=typeof(IItemInterop).GUID;Marshal.ThrowExceptionForHR(RoGetActivationFactory(hs,interopId,out var f));
            try {
                var interop=(IItemInterop)Marshal.GetObjectForIUnknown(f);var iid=new Guid("79C3F95B-31F7-4EC2-A464-632EF5D30760");
                Marshal.ThrowExceptionForHR(interop.CreateForWindow(hwnd,iid,out var ptr));
                try{item=WinRT.MarshalInterface<GraphicsCaptureItem>.FromAbi(ptr);}finally{Marshal.Release(ptr);}
                Marshal.ReleaseComObject(interop);
            } finally{Marshal.Release(f);}
        } finally{WindowsDeleteString(hs);}
        Marshal.ThrowExceptionForHR(D3D11CreateDevice(0,1,0,0x20,0,0,7,out var d,out _,out var context));
        try {
            var iid=new Guid("54EC77FA-1377-44E6-8C32-88FD5F44C84C");Marshal.ThrowExceptionForHR(Marshal.QueryInterface(d,in iid,out var dxgi));
            try{Marshal.ThrowExceptionForHR(CreateDirect3D11DeviceFromDXGIDevice(dxgi,out var inspectable));
                try{device=WinRT.MarshalInterface<IDirect3DDevice>.FromAbi(inspectable);}finally{Marshal.Release(inspectable);}
            }finally{Marshal.Release(dxgi);}
        } finally{Marshal.Release(context);Marshal.Release(d);}
        size=item.Size;
        pool=Direct3D11CaptureFramePool.CreateFreeThreaded(device,DirectXPixelFormat.B8G8R8A8UIntNormalized,2,size);
        pool.FrameArrived+=Arrived;session=pool.CreateCaptureSession(item);session.IsCursorCaptureEnabled=false;session.StartCapture();
    }
    void Arrived(Direct3D11CaptureFramePool sender,object e){
        lock(gate){if(disposed)return;var frame=sender.TryGetNextFrame();if(frame==null)return;latest?.Dispose();latest=frame;}
    }
    public string? TextSignature {get;private set;}
    public async Task<byte[]?> Crop(Region region,CancellationToken token,Region? textMask=null){
        TextSignature=null;
        Direct3D11CaptureFrame? frame;
        lock(gate){frame=latest;latest=null;}
        if(frame==null)return null;
        using(frame){
            token.ThrowIfCancellationRequested();
            if(frame.ContentSize.Width!=size.Width||frame.ContentSize.Height!=size.Height){
                size=frame.ContentSize;if(size.Width>0&&size.Height>0)pool.Recreate(device,DirectXPixelFormat.B8G8R8A8UIntNormalized,2,size);
                return null;
            }
            using var bitmap=await SoftwareBitmap.CreateCopyFromSurfaceAsync(frame.Surface);
            token.ThrowIfCancellationRequested();
            var bounds=Native.WindowRect(window);var crop=Native.ClientRect(window).Region(region);
            var sx=bitmap.PixelWidth/bounds.Width;var sy=bitmap.PixelHeight/bounds.Height;
            var x=(uint)Math.Clamp((int)((crop.X-bounds.X)*sx),0,bitmap.PixelWidth-1);
            var y=(uint)Math.Clamp((int)((crop.Y-bounds.Y)*sy),0,bitmap.PixelHeight-1);
            var w=(uint)Math.Min(bitmap.PixelWidth-x,Math.Max(1,(int)(crop.Width*sx)));
            var h=(uint)Math.Min(bitmap.PixelHeight-y,Math.Max(1,(int)(crop.Height*sy)));
            if(textMask!=null&&(long)bitmap.PixelWidth*bitmap.PixelHeight<=4_000_000){
                var mask=Native.ClientRect(window).Region(textMask);var mx=Math.Clamp((int)((mask.X-bounds.X)*sx),0,bitmap.PixelWidth-1);var my=Math.Clamp((int)((mask.Y-bounds.Y)*sy),0,bitmap.PixelHeight-1);
                var mw=Math.Clamp((int)(mask.Width*sx),1,bitmap.PixelWidth-mx);var mh=Math.Clamp((int)(mask.Height*sy),1,bitmap.PixelHeight-my);
                var buffer=new Windows.Storage.Streams.Buffer((uint)(bitmap.PixelWidth*bitmap.PixelHeight*4));bitmap.CopyToBuffer(buffer);
                using var pixelReader=DataReader.FromBuffer(buffer);var pixels=new byte[buffer.Length];pixelReader.ReadBytes(pixels);
                using var hash=System.Security.Cryptography.IncrementalHash.CreateHash(System.Security.Cryptography.HashAlgorithmName.SHA256);
                for(int row=my;row<my+mh;row++)hash.AppendData(pixels,(row*bitmap.PixelWidth+mx)*4,mw*4);
                TextSignature=Convert.ToHexString(hash.GetHashAndReset());
            }
            var scale=Math.Min(1,Math.Min(1280d/w,Math.Sqrt(1_500_000d/((double)w*h))));
            for(var attempt=0;attempt<3;attempt++,scale*=.5){
                token.ThrowIfCancellationRequested();
                using var stream=new InMemoryRandomAccessStream();var encoder=await BitmapEncoder.CreateAsync(BitmapEncoder.PngEncoderId,stream);
                encoder.SetSoftwareBitmap(bitmap);
                // WinRT scales before cropping; bounds must use the scaled coordinate space.
                var scaledWidth=Math.Max(1,(uint)(bitmap.PixelWidth*scale));var scaledHeight=Math.Max(1,(uint)(bitmap.PixelHeight*scale));
                var cx=(uint)(x*scale);var cy=(uint)(y*scale);
                encoder.BitmapTransform.ScaledWidth=scaledWidth;encoder.BitmapTransform.ScaledHeight=scaledHeight;
                encoder.BitmapTransform.InterpolationMode=BitmapInterpolationMode.Cubic;
                encoder.BitmapTransform.Bounds=new BitmapBounds{X=cx,Y=cy,Width=Math.Min(scaledWidth-cx,Math.Max(1,(uint)(w*scale))),Height=Math.Min(scaledHeight-cy,Math.Max(1,(uint)(h*scale)))};
                encoder.IsThumbnailGenerated=false;await encoder.FlushAsync();
                if(stream.Size>2*1024*1024)continue;
                stream.Seek(0);using var reader=new DataReader(stream.GetInputStreamAt(0));await reader.LoadAsync((uint)stream.Size);var png=new byte[stream.Size];reader.ReadBytes(png);return png;
            }
            return null;
        }
    }
    public void Dispose(){lock(gate){disposed=true;latest?.Dispose();latest=null;}session.Dispose();pool.Dispose();(device as IDisposable)?.Dispose();}
}
