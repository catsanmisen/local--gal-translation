"""Read-only timed observation of a real native game session; never owns its lease."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import urllib.request

# Embedded Python's isolated ._pth does not add the invoked script directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from process_metrics import ProcessMetrics


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--port',type=int,default=18079)
    p.add_argument('--duration',type=float,default=1800)
    p.add_argument('--output',type=Path,default=Path('work/seabed-observation.jsonl'))
    p.add_argument('--host-pid',type=int)
    p.add_argument('--backend-pid',type=int)
    p.add_argument('--ocr-pid',type=int)
    a=p.parse_args()
    base=f'http://127.0.0.1:{a.port}'
    with urllib.request.urlopen(base+'/bootstrap',timeout=5) as r:token=json.load(r)['token']
    def get(path):
        request=urllib.request.Request(base+'/api/v1'+path,headers={'Authorization':'Bearer '+token})
        with urllib.request.urlopen(request,timeout=5) as r:return json.load(r)
    started=time.monotonic();next_print=0;seen=set();metrics=ProcessMetrics()
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('a',encoding='utf-8') as f:
        while time.monotonic()-started<a.duration:
            elapsed=time.monotonic()-started
            item={'at':datetime.now(timezone.utc).isoformat(),'observed_seconds':round(elapsed,3)}
            try:
                status=get('/status');caption=get('/subtitle')
                item.update(state=status['state'],model=status['model'],gpu=status.get('gpu'),
                    game=status.get('game_session'),subtitle=caption)
                item['processes']={label:metrics.sample(pid) for label,pid in (
                    ('desktop',a.host_pid),('backend',a.backend_pid),('ocr',a.ocr_pid),
                    ('game',(status.get('game_session') or {}).get('pid')),('model',status.get('owned_pid'))) if pid}
                if caption.get('request_id') and caption['state'] in ('final','error','cancelled') and caption['request_id'] not in seen:
                    seen.add(caption['request_id'])
                    item['history']=next((h for h in get('/history')['items'] if h['request_id']==caption['request_id']),None)
            except Exception as error:item['observer_error']=str(error)
            f.write(json.dumps(item,ensure_ascii=False)+'\n');f.flush()
            if elapsed>=next_print:
                print(json.dumps({'seconds':round(elapsed),'state':item.get('state'),
                    'mode':item.get('model',{}).get('execution_mode'),
                    'free_mib':(item.get('gpu') or {}).get('free_mib'),
                    'bound':(item.get('game') or {}).get('bound'),
                    'foreground':(item.get('game') or {}).get('foreground'),
                    'terminal_requests_observed':len(seen),'error':item.get('observer_error')},ensure_ascii=False),flush=True)
                next_print=elapsed+30
            time.sleep(2)
    print('Timed observation finished; evaluate recorded foreground time and genuine lines separately.',flush=True)


if __name__=='__main__':main()
