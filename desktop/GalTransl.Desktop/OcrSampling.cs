namespace GalTransl.Desktop;
public sealed class OcrSampling {
    string? accepted;double checkedAt;
    public void Reset(){accepted=null;checkedAt=0;}
    public void Checked(string? signature,double now){accepted=signature;checkedAt=now;}
    // A full OCR pass every 600ms catches appended rows outside old text bounds.
    public bool Skip(string? signature,double now,bool final,bool geometryChanged)=>final&&!geometryChanged&&signature!=null&&signature==accepted&&now-checkedAt<600;
}
