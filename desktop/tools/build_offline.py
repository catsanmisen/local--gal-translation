"""Assemble a private offline candidate; excludes databases, logs, tests and credentials."""
import argparse,email,hashlib,json,shutil,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DEST=ROOT/'dist/galtransl-completion-candidate'

def main():
    global DEST
    parser=argparse.ArgumentParser();parser.add_argument('--refresh',action='store_true');parser.add_argument('--dest',type=Path,default=DEST)
    parser.add_argument('--publish',type=Path,default=ROOT/'desktop/publish-reliability');parser.add_argument('--zip',action='store_true')
    parser.add_argument('--release-version',help='Version metadata for an offline release using desktop/OFFLINE-README.txt')
    args=parser.parse_args();DEST=args.dest.resolve();publish=args.publish.resolve();refresh=args.refresh
    if not DEST.is_relative_to(ROOT/'dist') or not publish.is_relative_to(ROOT/'desktop'):raise SystemExit('Build directories must stay in workspace dist/desktop.')
    if refresh and not (DEST/'package-manifest.json').is_file():raise SystemExit('Refresh requires this tool\'s existing candidate manifest.')
    if DEST.exists() and not refresh:raise SystemExit('Candidate directory exists; use --refresh only for this generated candidate.')
    DEST.mkdir(parents=True,exist_ok=True)
    def copy_changed(source,target):
        source=Path(source);target=Path(target)
        if target.is_file() and source.stat().st_size==target.stat().st_size:
            with source.open('rb') as a,target.open('rb') as b:
                if hashlib.file_digest(a,'sha256').digest()==hashlib.file_digest(b,'sha256').digest():return str(target)
        return shutil.copy2(source,target)
    def tree(source,target):
        shutil.copytree(ROOT/source,DEST/target,dirs_exist_ok=True,copy_function=copy_changed,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    tree(publish,'.')
    tree('backend/src','backend/src');tree('backend/bridge','backend/bridge')
    if not refresh:tree('backend/runtime','backend/runtime')
    tree('backend/vendor','backend/vendor')
    for name in ('index.html','subtitle.html'):
        (DEST/'frontend').mkdir(exist_ok=True);shutil.copy2(ROOT/'frontend'/name,DEST/'frontend'/name)
    for name in ('css','js','vendor'):tree('frontend/'+name,'frontend/'+name)
    folder=DEST/'backend/galtransl4';folder.mkdir(parents=True,exist_ok=True)
    for name in ('gal_service.py','gal_translate.py','installation.json','model-metadata.json','service-config.json'):
        shutil.copy2(ROOT/'backend/galtransl4'/name,folder/name)
    manifest=json.loads((folder/'installation.json').read_text(encoding='utf-8'))
    if Path(manifest['runtime_directory']).is_absolute():raise RuntimeError('Runtime must be relocatable.')
    model=ROOT/'backend/galtransl4/models'/manifest['model_file'];(folder/'models').mkdir(exist_ok=True)
    if not refresh:shutil.copy2(model,folder/'models'/model.name)
    licenses=DEST/'licenses';licenses.mkdir(exist_ok=True)
    for name in ('LICENSE.txt','ThirdPartyNotices.txt'):
        if (ROOT/'.tools/dotnet'/name).exists():shutil.copy2(ROOT/'.tools/dotnet'/name,licenses/('dotnet-'+name))
    (licenses/'COMPONENTS.md').write_text('Private candidate component list\n\nGalTransl 4B Q6_K: '+manifest['model_repository']+' @ '+manifest['model_revision']+'; license '+manifest['license']+'.\nModel source: '+manifest['download_source']+'\n\nTextractor v5.2.0 GPL-3.0: upstream source zip and LICENSE in backend/vendor/textractor. MinHook submodule commit 423d1e45af2ed2719a5c31e990e935ef301ed9c3 source, BSD license and pin manifest are included.\nRapidOCR/PaddleOCR: licenses and model hashes in backend/vendor/ocr. Phosphor icon fonts: backend/vendor/phosphor/LICENSE.\nPython: backend/runtime/python/LICENSE.txt; package licenses in site-packages; FlatBuffers 25.12.19 license in backend/vendor/notices/LICENSE-flatbuffers-25.12.19.txt. Python component versions and license paths are in licenses/PYTHON-PACKAGES.json.\n.NET notices in this folder. llama.cpp b11429 MIT and CUDA 13.0 EULA are in backend/vendor/notices. CUDA redistribution component list and exact DLL versions are recorded in NOTICE-SOURCES.json. Source completeness and attribution have been assembled; this does not assert a legal opinion or certify public distribution.\nThis private candidate still awaits actual GUI/game acceptance and is not a public release.\n',encoding='utf-8')
    packages=[];library=DEST/'backend/runtime/python/Lib/site-packages'
    for path in sorted(library.glob('*.dist-info/METADATA')):
        data=email.message_from_bytes(path.read_bytes());candidates=list(path.parent.rglob('*'))
        top=path.parent/'top_level.txt'
        modules=set(top.read_text(encoding='utf-8').splitlines() if top.exists() else [])
        modules.add(data['Name'].replace('-','_'))
        for name in modules:
            if name.isidentifier() and (library/name).is_dir():candidates.extend((library/name).rglob('*'))
        if data['Name']=='flatbuffers':candidates.append(DEST/'backend/vendor/notices/LICENSE-flatbuffers-25.12.19.txt')
        files=sorted({p.relative_to(DEST).as_posix() for p in candidates if p.is_file()
            and any(word in p.name.lower() for word in ('license','licence','copying','notice'))})
        packages.append({'name':data['Name'],'version':data['Version'],
            'license_metadata':data.get('License-Expression') or data.get('License'),'license_files':files})
    (licenses/'PYTHON-PACKAGES.json').write_text(json.dumps(packages,ensure_ascii=False,indent=2),encoding='utf-8')
    (DEST/'README.txt').write_text('''GalTransl 私人离线候选（桌面协议2）

解压到新目录，运行 GalTransl.Desktop.exe。无需另装开发工具或系统Python。
首次从托盘设置中选择已运行的日文游戏，框选取词区域并调整字幕位置；
以后自动恢复已保存配置。选HOOK时首次还需选择有效文本线程。
字幕正文穿透；Backlog仅在玩家主动打开时显示历史。“全文”只读当前句。
单次输入隐藏/恢复可在位置设置中开启，输入仍传给游戏。
在桌面设置或浏览器“配置”中选择模型设备并保存：自动沿用现有策略；
CPU 使用处理器；GPU 显存不足时保持选择并提示等待，不自动切到 CPU。
GPU 显存预留默认 2048 MiB，可选 1536 / 1024 MiB；降低后可加载更多 GPU 层，
也会减少留给游戏的显存。实际 CPU / GPU 层数会显示在设置中。
运行中保存设备设置会安全重载模型；已完成的当前句保留，不重复进入历史。
自动壁纸释放默认开启，可在同一设置中关闭。检测到高占用 Wallpaper Engine
限制模型运行时，临时 stop 壁纸；停止翻译、游戏退出或客户端退出后自动 play 恢复。
CPU/GPU选择不变，不修改壁纸配置。提示：占用显存过大的壁纸可能暂时关闭。
关闭设置窗进入托盘；托盘“退出客户端”回收所属后台与模型。

默认数据：本目录 data/client.sqlite3。不要覆盖运行中的旧包或玩家数据。
升级前在旧包目录备份到新的文件名：
backend\\runtime\\python\\python.exe -B backend/src/data_tools.py backup data/client.sqlite3 ../client-before-upgrade.sqlite3
正常退出旧客户端后，在新包目录恢复备份：
backend\\runtime\\python\\python.exe -B backend/src/data_tools.py restore ../client-before-upgrade.sqlite3 data/client.sqlite3
恢复拒绝活动数据库；回退时保留并使用升级前备份。

许可与源码材料：licenses/COMPONENTS.md、backend/vendor/。
本包供私人离线验证。SeaBed/Aokana已有历史探索性短测记录；
当前构建的完整50句、稳定长测与最终性能达标仍待确认。
OCR仍可能误识省略号、生僻字或特殊演出，请保留原文对照。
壁纸控制或恢复失败会提示；异常退出后下次启动尝试补偿恢复。CPU就绪后不会在游戏中自动升级GPU。
GPU/混合中位目标为2秒；整页性能仍未达标，高占用壁纸恢复待实测。
包内不含游戏文件或存档，也不会替换汉化文件或Magpie设置。
''',encoding='utf-8')
    if args.release_version:
        shutil.copy2(ROOT/'desktop/OFFLINE-README.txt',DEST/'README.txt')
        components=licenses/'COMPONENTS.md'
        content=components.read_text(encoding='utf-8').replace('Private candidate component list','Offline release component list')
        content=content.replace('This private candidate still awaits actual GUI/game acceptance and is not a public release.',
            'Local offline release '+args.release_version+'. Acceptance scope and known limitations: README.txt. Not uploaded or publicly published.')
        components.write_text(content,encoding='utf-8')
    files=[]
    for file in sorted(DEST.rglob('*')):
        relative=file.relative_to(DEST)
        if file.is_file() and file.name!='package-manifest.json' and not any(p in {'logs','work','data','service-state','__pycache__'} for p in relative.parts):
            with file.open('rb') as stream: digest=hashlib.file_digest(stream,'sha256').hexdigest()
            files.append({'path':file.relative_to(DEST).as_posix(),'size':file.stat().st_size,'sha256':digest})
    metadata={'kind':'offline release' if args.release_version else 'private offline candidate, final acceptance pending','desktop_protocol':2,'files':files}
    if args.release_version:metadata.update(version=args.release_version,scope='ordinary Japanese dialogue OCR and offline translation')
    (DEST/'package-manifest.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    if args.zip:
        with zipfile.ZipFile(DEST.with_name(DEST.name+'.zip'),'w',zipfile.ZIP_STORED,allowZip64=True) as archive:
            for item in files:archive.write(DEST/item['path'],item['path'])
            archive.write(DEST/'package-manifest.json','package-manifest.json')
    print('Offline candidate assembled: '+str(len(files))+' files; '+str(sum(f['size'] for f in files))+' bytes.')
if __name__=='__main__':main()
