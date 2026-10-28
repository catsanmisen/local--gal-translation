"""Read-only assertions and shutdown for an explicitly selected integration-test server."""
import argparse
import json
from pathlib import Path
import socket
import time
import urllib.error
import urllib.request
from real_smoke import Api, ROOT
from cli_config import add_client_port


def main():
    parser=argparse.ArgumentParser();add_client_port(parser)
    parser.add_argument('phase',choices=['snapshot','closed-window','restart','shutdown'])
    parser.add_argument('--output',type=Path,default=ROOT/'work/full-flow-lifecycle.json')
    parser.add_argument('--timeout',type=int,default=110)
    args=parser.parse_args();api=Api(args.port)
    report=json.loads(args.output.read_text(encoding='utf-8')) if args.output.exists() else {}
    if args.phase=='snapshot':
        profiles=api.call('/profiles');p=next(p for p in profiles if p['id']=='integration')
        assert p['prefs']=={'font':25,'opacity':20,'mode':'zh','source_kind':'manual'},p['prefs']
        assert len(p['glossary'])==2 and p['glossary'][1]['target']=='学长'
        items=api.call('/history?profile_id=integration&limit=200')['items']
        assert len(items)>=3 and all(h['terminal']=='final' for h in items)
        assert any(h['source_text']=='先輩、また会いましょう。' and '学长' in h['translation'] for h in items)
        assert not api.call('/history?profile_id=default')['items']
        report.update(profile=p,history=items,ui_history_isolated=True)
        def code(url,headers=None):
            try:
                with urllib.request.urlopen(urllib.request.Request(url,headers=headers or {}),timeout=5) as r:return r.status
            except urllib.error.HTTPError as e:return e.code
        assert code(api.base+'/api/v1/status')==401
        assert code(api.base+'/api/v1/status',{**api.headers,'Origin':'https://invalid.example'})==403
        assert code(api.base+'/bootstrap',{'Host':'invalid.example'})==403
        for path in ['/data/client.sqlite3','/logs/engine.log','/backend/src/core.py']:
            assert code(api.base+path)==404
            assert code('http://127.0.0.1:8082'+path)==403
        assert code('http://127.0.0.1:18038/slots')==401
        report['live_security_checks']='PASS'
    elif args.phase=='closed-window':
        started=time.monotonic()
        status=api.wait({'stopped'},timeout=args.timeout)
        assert status['owned_pid'] is None
        report['last_main_window_reclaims_model']='PASS'
        report['closed_window_wait_ms']=round((time.monotonic()-started)*1000)
        report['stopped']=status
    elif args.phase=='restart':
        assert api.call('/status')['state']=='stopped'
        assert api.call('/history?profile_id=integration&limit=200')['items']==report['history']
        assert next(p for p in api.call('/profiles') if p['id']=='integration')==report['profile']
        report['process_restart_preserves_history_glossary_preferences']='PASS'
    else:
        api.call('/shutdown',{})
        deadline=time.monotonic()+10
        while True:
            try:
                conn=socket.create_connection(('127.0.0.1',args.port),timeout=.3);conn.close()
            except OSError:break
            assert time.monotonic()<deadline,'client port still open'
            time.sleep(.1)
        try:
            conn=socket.create_connection(('127.0.0.1',18038),timeout=.3);conn.close()
            raise AssertionError('model port still open')
        except OSError:pass
        report['shutdown_releases_client_and_model_ports']='PASS'
    if all(report.get(k)=='PASS' for k in ('live_security_checks','process_restart_preserves_history_glossary_preferences',
        'last_main_window_reclaims_model','shutdown_releases_client_and_model_ports')):
        report['result']='PASS'
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(args.phase+' PASS')


if __name__=='__main__':main()
