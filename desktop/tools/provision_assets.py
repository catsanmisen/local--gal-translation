"""Build-time official downloads only. Production OCR/HOOK never downloads assets."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile
import yaml

ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT/'work/desktop-assets';WORK.mkdir(parents=True,exist_ok=True)
UA={'User-Agent':'GalTranslClient-build'}

def download(url,path,expected=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        print('Downloading '+path.name,flush=True)
        with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=90) as r,path.open('wb') as f:shutil.copyfileobj(r,f)
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if expected and digest!=expected:raise RuntimeError('Asset hash mismatch: '+path.name)
    return {'path':path.name,'sha256':digest,'size':path.stat().st_size,'source':url}

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    import rapidocr
    package=Path(rapidocr.__file__).parent
    routes=yaml.safe_load((package/'default_models.yaml').read_text(encoding='utf-8'))['onnxruntime']['PP-OCRv4']
    folder=ROOT/'backend/vendor/ocr';folder.mkdir(parents=True,exist_ok=True)
    files=[]
    for task,key in [('det','ch_PP-OCRv4_det_mobile'),('cls','ch_ppocr_mobile_v2.0_cls_mobile'),('rec','japan_PP-OCRv4_rec_mobile')]:
        item=routes[task][key];url=item['model_dir'];files.append({**download(url,folder/(key+'.onnx'),item['SHA256']),'task':task})
    download('https://raw.githubusercontent.com/RapidAI/RapidOCR/v3.10.0/LICENSE',folder/'LICENSE-RapidOCR')
    download('https://raw.githubusercontent.com/PaddlePaddle/PaddleOCR/main/LICENSE',folder/'LICENSE-PaddleOCR')
    (folder/'manifest.json').write_text(json.dumps({'rapidocr':'3.10.0','engine':'onnxruntime CPU','ocr_version':'PP-OCRv4','language':'japan','files':files},ensure_ascii=False,indent=2),encoding='utf-8')
    freeze=subprocess.check_output([sys.executable,'-m','pip','freeze'],text=True)
    (ROOT/'desktop/ocr-requirements.lock').write_text(freeze,encoding='utf-8')
    vendor=ROOT/'backend/vendor/textractor';vendor.mkdir(parents=True,exist_ok=True)
    archive=WORK/'Textractor-5.2.0.zip'
    asset=download('https://github.com/Artikash/Textractor/releases/download/v5.2.0/Textractor-5.2.0-Zip-Version-English-Only.zip',archive)
    expanded=WORK/'textractor-expanded';expanded.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for entry in z.infolist():
            target=(expanded/entry.filename).resolve()
            if not target.is_relative_to(expanded.resolve()):raise RuntimeError('Archive escapes workspace')
        z.extractall(expanded)
    runtime=[]
    for cli in expanded.rglob('TextractorCLI.exe'):
        arch=next((p.lower() for p in cli.parts if p.lower() in ('x86','x64')),None)
        if arch is None:raise RuntimeError('Unknown CLI architecture')
        target=vendor/arch;target.mkdir(exist_ok=True)
        for file in cli.parent.iterdir():
            if file.name.lower().startswith('texthook') or file.name=='TextractorCLI.exe':
                shutil.copy2(file,target/file.name)
                runtime.append({'path':arch+'/'+file.name,'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'size':file.stat().st_size})
    if len(list(vendor.rglob('TextractorCLI.exe')))!=2:raise RuntimeError('Missing x86/x64 CLI')
    source=download('https://codeload.github.com/Artikash/Textractor/zip/refs/tags/v5.2.0',vendor/'Textractor-v5.2.0-source.zip')
    download('https://raw.githubusercontent.com/Artikash/Textractor/v5.2.0/LICENSE',vendor/'LICENSE-GPL-3.0')
    (vendor/'SOURCE-NOTICE.md').write_text('Textractor v5.2.0, Artikash and contributors, GPL-3.0.\n\nOfficial unmodified CLI and texthook are separate processes/components. Corresponding upstream source is included in Textractor-v5.2.0-source.zip. Repository/tag: https://github.com/Artikash/Textractor/tree/v5.2.0 . To rebuild, initialize the pinned .gitmodules dependencies and follow upstream README/CMake instructions (Visual Studio + CMake; Qt required for GUI, not CLI). This client does not ship the Qt GUI or translation extensions. Upstream release: https://github.com/Artikash/Textractor/releases/tag/v5.2.0 . Keep this notice, the GPL and source archive in redistributed packages.\n',encoding='utf-8')
    (vendor/'manifest.json').write_text(json.dumps({'version':'5.2.0','license':'GPL-3.0','release':asset,'source':source,'files':runtime},indent=2),encoding='utf-8')
    print('Offline OCR and x86/x64 HOOK assets provisioned',flush=True)


if __name__=='__main__':main()
