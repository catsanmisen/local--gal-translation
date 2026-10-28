"""Observe a new native-caption result; never submits translation or captures game pixels."""
import argparse
import json
from pathlib import Path
import time
import urllib.request
import sys

sys.stdout.reconfigure(encoding='utf-8')
p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=18079);p.add_argument('--previous',default='');p.add_argument('--case',required=True);p.add_argument('--timeout',type=float,default=30)
p.add_argument('--output',type=Path,default=Path('work/seabed-cases.jsonl'));a=p.parse_args()
base=f'http://127.0.0.1:{a.port}'
with urllib.request.urlopen(base+'/bootstrap',timeout=5) as r:token=json.load(r)['token']
def get(path):
    req=urllib.request.Request(base+'/api/v1'+path,headers={'Authorization':'Bearer '+token})
    with urllib.request.urlopen(req,timeout=5) as r:return json.load(r)
deadline=time.monotonic()+a.timeout;seen=[];caption=None
while time.monotonic()<deadline:
    s=get('/subtitle')
    if s.get('request_id')!=a.previous and s.get('request_id'):
        if s['state'] not in seen:seen.append(s['state'])
        if s['state'] in ('final','error','cancelled'):
            caption=s;break
    time.sleep(.2)
status=get('/status')
if caption is None:caption=get('/subtitle')
items=get('/history')['items'];entry=next((h for h in items if h['request_id']==caption.get('request_id')),None)
case={'case':a.case,'at':time.time(),'states':seen,'caption':caption,'history':entry,'model':status['model'],'gpu':status.get('gpu'),'game':status.get('game_session'),'engine_state':status['state']}
a.output.parent.mkdir(parents=True,exist_ok=True)
with a.output.open('a',encoding='utf-8') as f:f.write(json.dumps(case,ensure_ascii=False)+'\n')
print(json.dumps({'case':a.case,'request_id':caption.get('request_id'),'state':caption['state'],
    'ja':caption.get('ja'),'zh':caption.get('zh'),'timings':entry.get('timings') if entry else None,
    'gpu_layers':status['model'].get('gpu_layers'),'free_mib':(status.get('gpu') or {}).get('free_mib')},ensure_ascii=False))
if caption.get('request_id')==a.previous or caption['state']!='final':raise SystemExit(1)
