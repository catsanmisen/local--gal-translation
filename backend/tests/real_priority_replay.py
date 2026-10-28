"""Explicit, isolated Q6 CPU replay. Never opens games or the player database."""
import argparse, hashlib, json, re, sys, threading, time, uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend/src'))
from engine import Engine, ClientError
from core import Client
from storage import Storage
from translation_quality import rejection

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser()
    p.add_argument('--evidence',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--port',type=int,default=18138)
    p.add_argument('--threads',type=int)
    p.add_argument('--threads-batch',type=int)
    p.add_argument('--cpu-mask')
    p.add_argument('--cold-only',action='store_true')
    p.add_argument('--probe-constraints',action='store_true')
    p.add_argument('--probe-example',action='store_true')
    p.add_argument('--probe-ocr-layout',action='store_true')
    p.add_argument('--probe-softwrap',action='store_true')
    a=p.parse_args()
    out=a.output.resolve()
    if not out.is_relative_to(ROOT/'work'):p.error('Output must be inside workspace/work')
    if out.exists():p.error('Refusing to overwrite earlier replay')
    out.parent.mkdir(parents=True,exist_ok=True)
    evidence=json.loads(a.evidence.read_text(encoding='utf-8'))
    cases=[{'id':f'old-{i+1}','source':c['source'],'kind':c['kind'],
            'context':c['contexts'][0] if c['contexts'] else [],'evidence':c['evidence']}
           for i,c in enumerate(evidence['old_failures'])]
    cases += [
        {'id':'named','source':'名前は{name}、${city}に住んでいます。','kind':'manual'},
        {'id':'printf','source':'%sは%d歳、残高は%02dです。','kind':'manual'},
        {'id':'controls','source':r'\c[1]朝\c[0]\n夜、\v[1]。','kind':'hook'},
        {'id':'blank-rows','source':'朝。\n\n夜。','kind':'manual'},
        {'id':'uppercase-controls','source':r'朝\N夜\C[1]。','kind':'hook'},
        {'id':'hook-rows','source':'「待って！」\n「すぐ行くよ。」','kind':'hook'},
        {'id':'waves','source':'「はあっ、はあっ、はあっ……は～、はっ、は～～～\nんっ」','kind':'ocr'},
        {'id':'cold-page','source':evidence['old_failures'][-1]['source'],'kind':'ocr'},
    ]
    e=Engine();e.config={**e.config,'port':a.port,'max_gpu_layers':0}
    # Experimental launch overrides live only in this test, not player config.
    if a.threads or a.threads_batch or a.cpu_mask:
        import engine as engine_module
        owned=engine_module.OwnedProcess
        def launch(args,*rest):
            args=list(args)
            if a.threads:
                for flag in ('--threads','--threads-batch'):args[args.index(flag)+1]=str(a.threads)
            if a.threads_batch:args[args.index('--threads-batch')+1]=str(a.threads_batch)
            if a.cpu_mask:args.extend(['--cpu-mask',a.cpu_mask,'--cpu-mask-batch',a.cpu_mask,'--cpu-strict','1','--cpu-strict-batch','1'])
            return owned(args,*rest)
        engine_module.OwnedProcess=launch
    if a.cold_only:
        page=evidence.get('cold_pages',[{'source':cases[-1]['source']}])[0]['source']
        cases=[{'id':f'cold-page-{i+1}','source':page,'kind':'ocr'} for i in range(3)]
        import http.client
        connection=http.client.HTTPConnection
        class ColdConnection(connection):
            def request(self,method,url,body=None,headers={},**kwargs):
                if url=='/v1/chat/completions':
                    value=json.loads(body);value['cache_prompt']=False
                    body=json.dumps(value,ensure_ascii=False).encode('utf-8')
                return super().request(method,url,body,headers,**kwargs)
        http.client.HTTPConnection=ColdConnection
    if a.probe_constraints or a.probe_example:
        import engine as engine_module
        original_payload=engine_module.payload
        def constrained(*args,**kwargs):
            body=original_payload(*args,**kwargs)
            if a.probe_constraints:body['messages'][0]['content']+=' 原文中的每一个变量均须逐个原样保留，不能省略或合并变量，也不能改变位置变量顺序。'
            if a.probe_example:
                body['messages'][1:1]=[
                    {'role':'user','content':'将下面的文本从日文翻译成简体中文，原样保留每个变量：\n{GT_KEEP_0}から{GT_KEEP_1}を引くと{GT_KEEP_2}になる。'},
                    {'role':'assistant','content':'{GT_KEEP_0}减去{GT_KEEP_1}等于{GT_KEEP_2}。'}]
            return body
        engine_module.payload=constrained
        cases=[c for c in cases if c['id']=='printf']
    if a.probe_ocr_layout:
        import engine as engine_module
        original_payload=engine_module.payload
        def visual_lines(*args,**kwargs):
            body=original_payload(*args,**kwargs)
            body['messages'][0]['content']=body['messages'][0]['content'].replace('不要擅自增加或减少换行。','画面换行只是视觉排版，请完整翻译全部文字，译文按自然中文分句。')
            return body
        engine_module.payload=visual_lines
    e.set_cpu_fallback(True)
    storage=Storage(out.with_suffix('.sqlite3'));client=Client(e,storage)
    calls=[];generate=e.generate
    def traced(source,context,glossary,cancel,delta,**options):
        entry={'source':source,'context':list(context),'options':options,'at':datetime.now(timezone.utc).isoformat()}
        calls.append(entry);started=time.monotonic();first=None
        def streamed(text):
            nonlocal first
            if first is None:first=round((time.monotonic()-started)*1000)
            delta(text)
        try:
            model_source=re.sub(r'(?<=[^。！？」）\n])\n(?=[\u3040-\u9fff])','',source) if a.probe_softwrap else source
            entry['model_source']=model_source
            value=generate(model_source,context,glossary,cancel,streamed,**options)
            entry.update(result=value,rejection=rejection(source,value,'ocr'))
            return value
        except ClientError as ex:entry['error']=ex.json();raise
        finally:entry.update(elapsed_ms=round((time.monotonic()-started)*1000),first_token_ms=first)
    e.generate=traced
    report={'started':datetime.now(timezone.utc).isoformat(),'cases':[],
            'note':'Recorded game-source replay plus explicit format probes; not live game cue acceptance.',
            'source_hashes':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in
                ('backend/src/core.py','backend/src/engine.py','backend/src/translation_quality.py','backend/galtransl4/gal_translate.py')}}
    def save():out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        e.start();deadline=time.monotonic()+190;last_state=None
        while e.status()['state']!='ready':
            s=e.status()
            if s['state']!=last_state:
                last_state=s['state'];print('Model',s['state'],s.get('owned_pid'),flush=True)
            if s['state'] in ('error','paused'):raise RuntimeError(s)
            if time.monotonic()>deadline:raise TimeoutError('model startup')
            time.sleep(.25)
        report['model']=e.status();print('CPU model ready',flush=True)
        for case in cases:
            s=client.create_session();client.context=list(case.get('context',[]));calls.clear()
            b={'request_id':'replay-'+uuid.uuid4().hex,'session_id':s['session_id'],'epoch':s['epoch'],'sequence':1,
               'source_text':case['source'],'source_kind':case['kind'],'speaker':None,
               'captured_at':datetime.now(timezone.utc).isoformat(),'complete':True,'stream':True,'timings':{}}
            req=client.submit(b,wait_for_engine=case['kind'] in ('ocr','hook'))
            with req.condition:
                if not req.condition.wait_for(lambda:req.terminal,180):raise TimeoutError(case['id'])
            terminal,data=req.events[-1]
            row={**case,'terminal':terminal,'data':data,'calls':list(calls),'events':list(req.events),
                 'history':storage.history(session=s['session_id']),'context_after':list(client.context)}
            report['cases'].append(row);save()
            print(case['id'],terminal,data.get('elapsed_ms',data.get('code')), 'calls',len(calls),flush=True)
        report['completed']=datetime.now(timezone.utc).isoformat()
    finally:
        client.close();storage.close();report['stopped']=e.status();save()
        print('Owned model stopped',flush=True)

if __name__=='__main__':main()
