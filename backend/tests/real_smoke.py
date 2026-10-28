"""Explicit real-model integration test, isolated-port/output options, no import-time actions."""
import argparse
import http.client
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime,timezone
import uuid
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend/src'))
from cli_config import add_client_port

class Api:
    def __init__(self,port):
        self.port=port;self.base=f'http://127.0.0.1:{port}'
        with urllib.request.urlopen(self.base+'/bootstrap',timeout=5) as response:
            token=json.load(response)['token']
        self.headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'}
    def call(self,path,body=None,method=None):
        req=urllib.request.Request(self.base+'/api/v1'+path,
            data=json.dumps(body,ensure_ascii=False).encode('utf-8') if body is not None else None,
            headers=self.headers,method=method)
        with urllib.request.urlopen(req,timeout=15) as response:return json.load(response)
    def wait(self,wanted,timeout=60):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            status=self.call('/status')
            if status['state'] in wanted:return status
            if status['state'] in ('paused','error'):raise AssertionError(status['last_error'])
            time.sleep(.5)
        raise AssertionError('state timeout')
    def connection(self,body):
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=30)
        conn.request('POST','/api/v1/translate',json.dumps(body,ensure_ascii=False).encode('utf-8'),self.headers)
        response=conn.getresponse()
        if response.status!=200:raise AssertionError(response.read().decode())
        return conn,response
    def stream(self,body):
        start=time.monotonic();first=None;events=[];name=None
        conn,response=self.connection(body)
        try:
            while True:
                line=response.readline()
                if not line:break
                if line.startswith(b'event:'):name=line[6:].decode().strip()
                if line.startswith(b'data:'):
                    data=json.loads(line[5:]);events.append((name,data))
                    if name=='delta' and first is None:first=time.monotonic()-start
        finally:response.close();conn.close()
        return events,round((time.monotonic()-start)*1000),round(first*1000) if first is not None else None

def request(session,sequence,text):
    return {'request_id':'smoke-'+uuid.uuid4().hex,'session_id':session['session_id'],'epoch':session['epoch'],'sequence':sequence,
        'source_text':text,'source_kind':'manual','speaker':None,'captured_at':datetime.now(timezone.utc).isoformat(),'complete':True,'stream':True}

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();add_client_port(parser)
    parser.add_argument('--keep-model',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT/'work/backend-real-smoke.json')
    args=parser.parse_args();api=Api(args.port)
    report={'at':datetime.now(timezone.utc).isoformat(),'cases':[]}
    try:
        api.call('/engine/start',{})
        status=api.wait({'ready'});report['ready']=status
        print('Model ready; GPU layers='+str(status['model']['gpu_layers']),flush=True)
        api.call('/profiles',{'id':'integration','name':'联调验证','prefs':{'font':24,'mode':'both','opacity':85,'source_kind':'manual'}},'PUT')
        session=api.call('/sessions',{'profile_id':'integration'})
        for seq,text in enumerate(['今日はいい天気ですね。','「葵、待って！」','名前は{name}です。'],1):
            b=request(session,seq,text);events,elapsed,ttft=api.stream(b)
            final=[d for event,d in events if event=='final']
            assert len(final)==1,(text,events[-1])
            assert all(all(d[k]==b[k] for k in ('request_id','session_id','epoch','sequence')) for _,d in events)
            translation=final[0]['translation'];assert translation!=text and 'mock' not in translation.lower()
            if '{name}' in text:assert '{name}' in translation
            report['cases'].append({'source':text,'translation':translation,'elapsed_ms':elapsed,'first_token_ms':ttft,'warnings':final[0]['warnings']})
            print(text+' => '+translation+' ('+str(elapsed)+' ms)',flush=True)
        session=api.call('/sessions/'+session['session_id']+'/glossary',{'entries':[{'source':'葵','target':'小葵','note':'人物名'}]},'PUT')
        events,_,_=api.stream(request(session,1,'葵はここにいます。'))
        assert events[-1][0]=='final';assert '小葵' in events[-1][1]['translation']
        report['glossary_translation']=events[-1][1]['translation']
        b=request(session,2,'今日はいい天気ですね。'*30)
        conn,response=api.connection(b)
        while True:
            line=response.readline()
            if line.startswith(b'event: delta'):break
            if not line:raise AssertionError('no delta before disconnect')
        response.close();conn.close()
        deadline=time.monotonic()+15
        while True:
            result=api.call('/requests/'+b['request_id'])
            if result['status'] in ('final','cancelled','error'):break
            assert time.monotonic()<deadline,'disconnect cancellation timeout'
            time.sleep(.2)
        assert result['status']=='cancelled'
        assert result['result']['reason']=='client_disconnected'
        report['disconnect_terminal']=result
        assert not any(slot['is_processing'] for slot in api.call('/engine/slots'))
        report['slot_idle_after_cancel']=True
        try:
            urllib.request.urlopen('http://127.0.0.1:18038/slots',timeout=5)
            raise AssertionError('internal model endpoint lacks authentication')
        except urllib.error.HTTPError as error:assert error.code==401
        report['internal_auth_verified']=True
        events,_,_=api.stream(request(session,3,'また会いましょう。'))
        assert events[-1][0]=='final';report['post_cancel_translation']=events[-1][1]['translation']
        old=session['epoch'];session=api.call('/sessions/'+session['session_id']+'/reset',{})
        assert session['epoch']==old+1
        history=api.call('/history?profile_id=integration&limit=100')['items']
        assert any(h['request_id']==b['request_id'] and h['source_text']==b['source_text'] and h['terminal']=='cancelled' for h in history)
        report['history_originals_verified']=True
        report['result']='PASS'
    finally:
        if not args.keep_model:
            api.call('/engine/stop',{});report['stopped']=api.wait({'stopped'})
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Integration '+report.get('result','FAIL'),flush=True)

if __name__=='__main__':main()
