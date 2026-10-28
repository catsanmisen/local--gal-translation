"""Local source checkpoint/diff; never includes runtime, database or credentials."""
import argparse
from datetime import datetime, timezone
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / 'work/2026-10-11-backlog-fixes'
AREAS = ('backend/src', 'backend/tests', 'backend/bridge', 'desktop/GalTransl.Desktop',
         'desktop/tests', 'frontend/js', 'frontend/css', 'docs')

def sources():
    paths = {ROOT/'frontend/index.html', ROOT/'frontend/subtitle.html',
             ROOT/'frontend/test-mock.cjs', ROOT/'frontend/test-sse.mjs', ROOT/'frontend/test-backlog.cjs',
             ROOT/'frontend/package.json', ROOT/'desktop/tools/checkpoint_work.py',ROOT/'desktop/tools/build_offline.py',
             ROOT/'backend/galtransl4/gal_translate.py',ROOT/'README.md',
             ROOT/'backend/README.md',ROOT/'frontend/README.md',ROOT/'frontend/DESIGN.md',ROOT/'frontend/server.mjs',ROOT/'desktop/README.md'}
    paths.update(p for p in (ROOT/'backend/vendor/notices').glob('*') if p.is_file())
    paths.update(ROOT/'backend/vendor/textractor'/name for name in ('SOURCE-NOTICE.md','LICENSE-MinHook.txt','source-submodules.json','MinHook-423d1e45-source.zip') if (ROOT/'backend/vendor/textractor'/name).exists())
    for area in AREAS:
        paths.update(p for p in (ROOT/area).rglob('*') if p.is_file()
                     and not any(x in p.parts for x in ('bin','obj','__pycache__'))
                     and p.suffix in ('.py','.js','.mjs','.cjs','.html','.css','.cs','.csproj','.md'))
    return sorted(paths)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('baseline','checkpoint'))
    parser.add_argument('--dest',default=str(DEST),help='Workspace-local checkpoint folder; existing baselines are never overwritten.')
    a=parser.parse_args();dest=Path(a.dest).resolve()
    if not dest.is_relative_to(ROOT/'work'):raise SystemExit('Checkpoint folder must stay inside workspace/work.')
    baseline=dest/'before';dest.mkdir(parents=True,exist_ok=True)
    if a.mode=='baseline':
        if baseline.exists():raise SystemExit('Baseline already exists; refusing to overwrite.')
        for p in sources():
            out=baseline/p.relative_to(ROOT);out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,out)
        print('Baseline captured.');return
    changed=[];diff=[]
    if not baseline.exists():raise SystemExit('Capture a baseline first; refusing to fabricate a whole-repo diff.')
    with zipfile.ZipFile(dest/'changes.zip','w',zipfile.ZIP_DEFLATED) as bundle:
        for p in sources():
            relative=p.relative_to(ROOT);old=baseline/relative;data=p.read_bytes()
            if old.exists() and old.read_bytes()==data:continue
            changed.append({'path':relative.as_posix(),'sha256':hashlib.sha256(data).hexdigest(),
                            'new_file':not old.exists()})
            bundle.write(p,relative.as_posix())
            try:
                before=old.read_text(encoding='utf-8-sig').splitlines(keepends=True) if old.exists() else []
                after=p.read_text(encoding='utf-8-sig').splitlines(keepends=True)
            except UnicodeDecodeError:
                diff.append('Binary files a/'+relative.as_posix()+' and b/'+relative.as_posix()+' differ\n')
            else:
                diff.extend(difflib.unified_diff(before,after,fromfile='a/'+relative.as_posix(),tofile='b/'+relative.as_posix()))
    (dest/'changes.patch').write_text(''.join(diff),encoding='utf-8')
    (dest/'manifest.json').write_text(json.dumps({'at':datetime.now(timezone.utc).isoformat(),
        'kind':'local source checkpoint (workspace has no Git repository)','files':changed},
        ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Checkpoint saved: {len(changed)} changed source files.')

if __name__=='__main__':main()
