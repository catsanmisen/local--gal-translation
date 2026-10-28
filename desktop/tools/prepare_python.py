"""Assemble a project-local Python runtime from the installed matching interpreter."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[2]
def main():
    source=Path(sys.base_prefix);dest=ROOT/'backend/runtime/python';dest.mkdir(parents=True,exist_ok=True)
    for pattern in ('python*.exe','python*.dll','vcruntime*.dll','LICENSE.txt'):
        for p in source.glob(pattern):shutil.copy2(p,dest/p.name)
    shutil.copytree(source/'DLLs',dest/'DLLs',dirs_exist_ok=True)
    shutil.copytree(source/'Lib',dest/'Lib',dirs_exist_ok=True,ignore=shutil.ignore_patterns('site-packages','__pycache__','test','tests'))
    shutil.copytree(ROOT/'.venv-ocr/Lib/site-packages',dest/'Lib/site-packages',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','tests'))
    (dest/'python312._pth').write_text('.\nDLLs\nLib\nLib/site-packages\n../../src\nimport site\n',encoding='utf-8')
    files=[]
    for p in sorted(dest.rglob('*')):
        if p.is_file() and p.name!='runtime-manifest.json':files.append({'path':str(p.relative_to(dest)).replace('\\','/'),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'size':p.stat().st_size})
    (dest/'runtime-manifest.json').write_text(json.dumps({'python':sys.version.split()[0],'files':files},indent=2),encoding='utf-8')
    print('Portable Python + locked CPU OCR runtime assembled; files='+str(len(files)))
if __name__=='__main__':main()
