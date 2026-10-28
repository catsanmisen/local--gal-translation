"""Bounded, owned GPU allocation for native CPU recovery QA. No UI, no inference.

Uses two or four GPU layers of the installed model for at most 90 seconds.
The test does not alter the client's mode/cap or mock its GPU monitor.
The fixture's Job is closed in finally; it cannot own or terminate the game.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend/src'))
from owned_process import OwnedProcess
from engine import gal_service


def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=18079)
    p.add_argument('--layers',type=int,choices=(2,4),default=2)
    a=p.parse_args()
    if a.port!=18079:raise SystemExit('Only the isolated SeaBed test port is allowed.')
    base=f'http://127.0.0.1:{a.port}'
    with urllib.request.urlopen(base+'/bootstrap',timeout=5) as r:token=json.load(r)['token']
    def get(path):
        request=urllib.request.Request(base+'/api/v1'+path,headers={'Authorization':'Bearer '+token})
        with urllib.request.urlopen(request,timeout=5) as r:return json.load(r)
    initial=get('/status');bound=initial.get('game_session') or {}
    if not bound.get('bound') or bound.get('profile_id')!='game-c9b566365b4e95aa' or initial['state']!='ready':
        raise SystemExit('Ready, bound SeaBed test session required.')
    before=gal_service.gpu()
    minimum=2500 if a.layers==4 else 2400
    if before['free_mib']<minimum:raise SystemExit(f'Fixture requires at least {minimum} MiB initially; no allocation started.')
    with socket.socket() as probe:probe.bind(('127.0.0.1',18088))
    manifest=json.loads((ROOT/'backend/galtransl4/installation.json').read_text(encoding='utf-8'))
    runtime=(ROOT/'backend/galtransl4'/manifest['runtime_directory']).resolve()
    model=ROOT/'backend/galtransl4/models'/manifest['model_file']
    args=[str(runtime/'llama-server.exe'),'--model',str(model),'--host','127.0.0.1','--port','18088',
        '--ctx-size','128','--parallel','1','--gpu-layers',str(a.layers),'--fit','off','--batch-size','64',
        '--ubatch-size','32','--threads','2','--no-warmup','--no-kv-offload']
    path=ROOT/'work/seabed-cpu-recovery.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
    process=None;started=time.monotonic();cpu_at=None
    try:
        with (ROOT/'work/gpu-pressure-fixture.log').open('wb') as log,path.open('a',encoding='utf-8') as output:
            process=OwnedProcess(args,runtime,log,{**os.environ,'LLAMA_API_KEY':secrets.token_urlsafe(32)})
            print(f'Owned {a.layers}-layer fixture started; pid='+str(process.pid),flush=True)
            while time.monotonic()-started<90:
                s=get('/status');gpu=gal_service.gpu()
                row={'at':datetime.now(timezone.utc).isoformat(),'seconds':round(time.monotonic()-started,3),
                    'fixture_pid':process.pid,'state':s['state'],'model':s['model'],'gpu':gpu,'game':s.get('game_session'),'last_error':s.get('last_error')}
                output.write(json.dumps(row,ensure_ascii=False)+'\n');output.flush()
                print(json.dumps({k:row[k] for k in ('seconds','state','model','gpu')},ensure_ascii=False),flush=True)
                if gpu['free_mib']<1400:raise RuntimeError('Emergency fixture release below 1400 MiB.')
                if process.poll() is not None:raise RuntimeError('Fixture exited; inspect its local log.')
                if not (s.get('game_session') or {}).get('bound'):raise RuntimeError('Game session ended; releasing fixture.')
                if s['state']=='ready' and s['model'].get('execution_mode')=='cpu':
                    cpu_at=cpu_at or time.monotonic()
                    if time.monotonic()-cpu_at>=5:break
                time.sleep(1)
    finally:
        if process is not None:
            process.close();print('Owned GPU fixture released; Wallpaper Engine and game untouched.',flush=True)
    if cpu_at is None:raise SystemExit('CPU recovery not reached in bounded window; report as unverified.')


if __name__=='__main__':main()
