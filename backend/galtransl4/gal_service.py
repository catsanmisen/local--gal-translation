"""Portable GalTransl-v4 translator with an NVIDIA VRAM watchdog (stdlib only)."""
import argparse
import datetime
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
STATE = ROOT / 'service-state'
CONFIG = ROOT / 'service-config.json'
HIDDEN = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0

def now():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()

def gpu():
    result = subprocess.run(['nvidia-smi','--query-gpu=memory.total,memory.used,memory.free','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=8,creationflags=HIDDEN,check=True)
    total, used, free = map(int, result.stdout.strip().splitlines()[0].split(','))
    return {'total_mib':total,'used_mib':used,'free_mib':free}

def save_state(data):
    temp = STATE / 'status.tmp'
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2),encoding='utf-8')
    temp.replace(STATE / 'status.json')

def status():
    try: return json.loads((STATE / 'status.json').read_text(encoding='utf-8'))
    except (OSError,json.JSONDecodeError): return {}

def health(port):
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f'http://127.0.0.1:{port}/health', timeout=2) as r:
            return json.load(r).get('status') == 'ok'
    except Exception: return False

def run(config_override=None):
    STATE.mkdir(exist_ok=True)
    config = json.loads(CONFIG.read_text(encoding='utf-8'))
    if config_override: config.update(config_override)
    manifest = json.loads((ROOT / 'installation.json').read_text(encoding='utf-8'))
    lock = STATE / 'watchdog.lock'
    existing = status()
    if lock.exists():
        updated = existing.get('heartbeat_unix',0)
        if time.time() - updated < 20:
            print('Service watchdog is already running.', flush=True)
            return 1
        lock.unlink()
    lock.write_text(str(__import__('os').getpid()),encoding='ascii')
    stop = STATE / 'stop.request'
    if stop.exists(): stop.unlink()
    data = {'state':'starting','started_at':now(),'heartbeat_unix':time.time(),'watchdog_pid':__import__('os').getpid(),'configuration':config}
    child = None
    loaded = False
    try:
        baseline = gpu()
        data['baseline_gpu'] = baseline
        save_state(data)
        if baseline['free_mib'] < config['minimum_start_free_mib']:
            raise RuntimeError(f"Only {baseline['free_mib']} MiB VRAM free; need {config['minimum_start_free_mib']} MiB before startup.")
        if health(config['port']): raise RuntimeError('Configured port is already in use.')
        runtime = Path(manifest['runtime_directory'])
        if not runtime.is_absolute():
            runtime = (ROOT / runtime).resolve()
        executable = next(runtime.rglob('llama-server.exe'))
        model = ROOT / 'models' / manifest['model_file']
        # Under Windows WDDM CUDA may report more free memory than nvidia-smi.
        # Limit offload explicitly using the measured global free VRAM.
        weight_budget=baseline['free_mib']-config['minimum_free_mib']-config['reserve_headroom_mib']-config['runtime_allowance_mib']
        model_info=json.loads((ROOT/'model-metadata.json').read_text(encoding='utf-8'))
        if model_info['metadata'].get('general.architecture')!='qwen3' or model_info['metadata'].get('general.file_type')!=18:
            raise RuntimeError('Expected the verified GalTransl Q6_K model metadata')
        layer_weights={int(k):v for k,v in model_info['gpu_offload_weight_mib'].items()}
        candidates=[n for n,size in layer_weights.items() if n<=config['max_gpu_layers'] and size<=weight_budget]
        layers=max(candidates,default=0)
        data['gpu_layers']=layers
        data['estimated_weight_budget_mib']=weight_budget
        print(f'Starting GalTransl-v4-4B: GPU layers={layers}, free VRAM={baseline["free_mib"]} MiB, reserve={config["minimum_free_mib"]} MiB',flush=True)
        args = [str(executable),'--model',str(model),'--alias','galtransl4-ja-zh','--host','127.0.0.1','--port',str(config['port']),'--ctx-size',str(config['context_tokens']),'--parallel','1','--batch-size','256','--ubatch-size','128','--threads','8','--threads-batch','8','--gpu-layers',str(layers),'--fit','off','--flash-attn','on','--jinja','--reasoning','off','--temp','0.7','--top-p','0.8','--top-k','20','--presence-penalty','0','--predict','384','--log-verbosity','4']
        data['command'] = args
        args[args.index('--temp')+1]='0.1'
        args[args.index('--top-p')+1]='0.8'
        args+=['--repeat-penalty','1.0']
        args+=['--seed','42']
        reasoning_index=args.index('--reasoning')+1
        args[reasoning_index]=config.get('reasoning_mode','off')
        args+=['--reasoning-budget',str(config.get('reasoning_budget',-1))]
        args[args.index('--log-verbosity')+1]='3'
        with (STATE / 'server.log').open('w',encoding='utf-8') as logfile, (STATE / 'gpu-samples.jsonl').open('w',encoding='utf-8') as samples:
            child = subprocess.Popen(args,cwd=executable.parent,stdout=logfile,stderr=subprocess.STDOUT,creationflags=HIDDEN)
            data['server_pid'] = child.pid
            data['state'] = 'loading'
            data['lowest_free_mib'] = baseline['free_mib']
            data['highest_used_mib'] = baseline['used_mib']
            errors = 0
            loaded = False
            beginning = time.monotonic()
            last_health = 0
            while child.poll() is None:
                if stop.exists():
                    data['stop_reason'] = 'User requested stop'
                    break
                try:
                    current = gpu()
                    errors = 0
                    data['current_gpu'] = current
                    data['lowest_free_mib'] = min(data['lowest_free_mib'],current['free_mib'])
                    data['highest_used_mib'] = max(data['highest_used_mib'],current['used_mib'])
                    samples.write(json.dumps({'at':now(),'pid':child.pid,**current})+'\n')
                    samples.flush()
                    if current['free_mib'] < config['minimum_free_mib']:
                        data['stop_reason'] = f"VRAM guard: {current['free_mib']} MiB free, below {config['minimum_free_mib']} MiB"
                        break
                except Exception as error:
                    errors += 1
                    data['monitor_error'] = str(error)
                    if errors >= 3:
                        data['stop_reason'] = 'VRAM monitoring failed three consecutive times'
                        break
                if not loaded and time.monotonic() - last_health > 3:
                    last_health = time.monotonic()
                    loaded = health(config['port'])
                    if loaded:
                        data['state'] = 'ready'
                        data['ready_at'] = now()
                        data['load_seconds'] = round(time.monotonic()-beginning,3)
                        print(f'Ready: http://127.0.0.1:{config["port"]}/v1 (model: galtransl4-ja-zh)',flush=True)
                    elif time.monotonic()-beginning > 180:
                        data['stop_reason'] = 'Startup timed out after 180 seconds'
                        break
                data['heartbeat_unix'] = time.time()
                save_state(data)
                time.sleep(0.75)
        if child.poll() is not None and not data.get('stop_reason'):
            data['stop_reason'] = f'Server exited with code {child.returncode}'
    except KeyboardInterrupt:
        data['stop_reason'] = 'User interrupted service'
    except Exception as error:
        data['stop_reason'] = str(error)
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try: child.wait(timeout=10)
            except subprocess.TimeoutExpired: child.kill(); child.wait()
        data['state'] = 'stopped'
        data['stopped_at'] = now()
        data['heartbeat_unix'] = time.time()
        save_state(data)
        lock.unlink(missing_ok=True)
        print('Service stopped: '+data.get('stop_reason','shutdown'),flush=True)
    return 0 if data.get('stop_reason') in ['User requested stop','User interrupted service'] else 1

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action',choices=['start','run','stop','status'])
    args = parser.parse_args()
    STATE.mkdir(exist_ok=True)
    if args.action == 'run': return run()
    if args.action == 'stop':
        (STATE / 'stop.request').write_text(now(),encoding='ascii')
        for _ in range(15):
            if status().get('state') == 'stopped': break
            time.sleep(1)
    elif args.action == 'start':
        if status().get('state') in ['starting','loading','ready'] and time.time()-status().get('heartbeat_unix',0)<20:
            print(json.dumps(status(),ensure_ascii=False,indent=2)); return 0
        with (STATE / 'watchdog.log').open('a',encoding='utf-8') as log:
            subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'run'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=HIDDEN | subprocess.CREATE_NEW_PROCESS_GROUP)
        time.sleep(3)
    print(json.dumps(status(),ensure_ascii=False,indent=2))
    return 0

if __name__ == '__main__': sys.exit(main())
