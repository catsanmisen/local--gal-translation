"""Read-only local game-session diagnostics. Never prints bootstrap credentials."""
import argparse
import json
from pathlib import Path
import time
import urllib.request

parser=argparse.ArgumentParser()
parser.add_argument('--port',type=int,default=18079)
parser.add_argument('--output',type=Path)
args=parser.parse_args()
base=f'http://127.0.0.1:{args.port}'
with urllib.request.urlopen(base+'/bootstrap',timeout=5) as response:
    token=json.load(response)['token']
def get(path):
    request=urllib.request.Request(base+'/api/v1'+path,headers={'Authorization':'Bearer '+token})
    with urllib.request.urlopen(request,timeout=5) as response:return json.load(response)
snapshot={'at':time.time(),**{k:get('/'+k) for k in ('status','subtitle','profiles','history')}}
if args.output:
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'state':snapshot['status']['state'],'error':snapshot['status']['last_error'],'model':snapshot['status']['model'],'gpu':snapshot['status'].get('gpu'),
    'game':snapshot['status'].get('game_session'),'subtitle':snapshot['subtitle'],
    'history_count':len(snapshot['history']['items']),
    'recent_history':snapshot['history']['items'][:3]},ensure_ascii=True))
