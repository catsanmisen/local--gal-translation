"""Explicit device/reserve benchmark on recorded full-page text, isolated data."""
import argparse,hashlib,http.client,json,logging,statistics,sys,threading,time,uuid
from logging.handlers import RotatingFileHandler
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'backend/src'))
from engine import Engine,gal_service
from core import Client,now
from storage import Storage
from wallpaper import WallpaperController

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('cpu','gpu','auto'),required=True)
    p.add_argument('--reserve',type=int,choices=(2048,1536,1024),required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--port',type=int,default=18138)
    p.add_argument('--wallpaper-relief',action='store_true',help='Opt in to the production Wallpaper Engine controller.')
    p.add_argument('--long-page',action='store_true',help='Replay the last recorded historical long source.')
    p.add_argument('--environment',type=Path,help='Observed process/resource snapshot with observed_at, method and game_running; absence means unknown.')
    a=p.parse_args();out=a.output.resolve()
    if not out.is_relative_to(ROOT/'work') or out.exists():p.error('Use a new output path inside work.')
    evidence=json.loads(a.evidence.read_text(encoding='utf-8'))
    environment=json.loads(a.environment.read_text(encoding='utf-8-sig')) if a.environment else {}
    source=evidence['old_failures'][-1]['source'] if a.long_page else evidence['cold_pages'][0]['source']
    connection=http.client.HTTPConnection
    class ColdConnection(connection):
        def request(self,method,url,body=None,headers={},**kwargs):
            if url=='/v1/chat/completions':
                value=json.loads(body);value['cache_prompt']=False;body=json.dumps(value,ensure_ascii=False).encode('utf-8')
            return super().request(method,url,body,headers,**kwargs)
    wallpaper=WallpaperController() if a.wallpaper_relief else None
    engine=Engine(wallpaper=wallpaper);engine.config={**engine.config,'port':a.port};engine.set_cpu_fallback(True)
    storage=Storage(out.with_suffix('.sqlite3'));storage.settings({'model_mode':a.mode,'gpu_reserve_mib':a.reserve,'wallpaper_relief':a.wallpaper_relief})
    client=Client(engine,storage)
    game_running=environment.get('game_running') if environment.get('observed_at') and environment.get('method') else None
    if type(game_running) is not bool:game_running=None
    report={'at':now(),'requested':client.settings(),'source':source,'cache_prompt':False,'game_running':game_running,'environment':environment,'cases':[],
        'physical_display':'not_measured','context':[],'backend_root':str(ROOT),'database':str(out.with_suffix('.sqlite3')),
        'wallpaper_control_enabled':a.wallpaper_relief,'sample':'long-page' if a.long_page else 'cold-page',
        'note':'Recorded uncached full-source CPU/GPU benchmark; wallpaper control is explicitly opt-in. Not game latency/P95 acceptance.',
        'source_hashes':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ('backend/src/engine.py','backend/src/core.py','backend/src/execution_policy.py','backend/src/wallpaper.py','backend/tests/real_model_choice.py')}}
    logger=logging.getLogger();previous_level=logger.level
    handler=RotatingFileHandler(out.with_suffix('.quality.log'),maxBytes=1024*1024,backupCount=2,encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler);logger.setLevel(logging.INFO)
    report['quality_log']=str(out.with_suffix('.quality.log'))
    gpu_samples=[];sampling_stop=threading.Event()
    def sample_gpu():
        while not sampling_stop.is_set():
            sample={'at':now(),'monotonic_seconds':time.monotonic()}
            try:sample.update(gal_service.gpu())
            except Exception as error:sample['error']=str(error)
            gpu_samples.append(sample)
            sampling_stop.wait(.75)
    monitor=threading.Thread(target=sample_gpu,daemon=True);monitor.start()
    http.client.HTTPConnection=ColdConnection
    try:
        if wallpaper:wallpaper.recover()
        try:report['gpu_before']=gal_service.gpu()
        except Exception as error:report['gpu_before_error']=str(error)
        client.start();deadline=time.monotonic()+190;state=None
        while True:
            status=client.status()
            if status['state']!=state:state=status['state'];print(state,flush=True)
            if state=='ready':break
            if state in ('paused','error') or time.monotonic()>deadline:raise RuntimeError(status.get('last_error') or state)
            time.sleep(.2)
        report['ready']=client.status()
        report['launch_parameters']=engine.launch_parameters
        report['offload_log']=[line for line in (ROOT/'logs/engine.log').read_text(encoding='utf-8',errors='replace').splitlines()
            if 'offload' in line.lower() and 'GPU' in line or 'CUDA0 model buffer' in line]
        for i in range(3):
            session=client.create_session();body={'request_id':'bench-'+uuid.uuid4().hex,'session_id':session['session_id'],'epoch':session['epoch'],'sequence':1,
                'source_text':source,'source_kind':'ocr','speaker':None,'captured_at':now(),'complete':True,'stream':True,'timings':{}}
            req=client.submit(body,wait_for_engine=True)
            with req.condition:
                if not req.condition.wait_for(lambda:req.terminal,180):raise TimeoutError('inference')
            terminal,data=req.events[-1];text=data.get('translation','')
            timing=data.get('timings',{});tokens=timing.get('model_output_tokens');decode=timing.get('model_server_decode_ms')
            report['cases'].append({'request_id':body['request_id'],'terminal':terminal,'data':data,
                'decode_tokens_per_second':tokens*1000/decode if tokens is not None and decode else None,
                'output_chars':len(text),'output_sha256':hashlib.sha256(text.encode('utf-8')).hexdigest(),'status':client.status()})
            out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(i+1,terminal,data.get('elapsed_ms',data.get('code')),len(text),flush=True)
            if terminal!='final':raise RuntimeError(data)
        report['median_ms']=statistics.median(c['data']['elapsed_ms'] for c in report['cases'])
        print('median_ms',report['median_ms'],'actual',report['ready']['model'],flush=True)
    except Exception as error:
        report['error']=str(error);raise
    finally:
        try:client.close()
        finally:
            try:
                if wallpaper:wallpaper.close()
            finally:
                http.client.HTTPConnection=connection
                sampling_stop.set();monitor.join()
                report['gpu_sampling']={'target_interval_seconds':.75,'samples':gpu_samples,
                    'sampled_peak_used_mib':max((s['used_mib'] for s in gpu_samples if 'used_mib' in s),default=None),
                    'note':'Whole-GPU sampled peak, not a process peak or all instantaneous peaks; actual intervals include the sampling call.'}
                logger.removeHandler(handler);handler.close();logger.setLevel(previous_level)
                storage.close();report['stopped']=engine.status()
                out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print('owned model stopped',flush=True)

if __name__=='__main__':main()
