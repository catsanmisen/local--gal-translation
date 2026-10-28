"""Analyze recorded real-game evidence. Does not operate the client or game."""
from collections import Counter
from datetime import datetime
import json
import math
from pathlib import Path
import statistics

ROOT=Path(__file__).resolve().parents[2]
def read(name):
    return [json.loads(s) for s in (ROOT/name).read_text(encoding='utf-8-sig').splitlines() if s.strip()]
def timestamp(s):return datetime.fromisoformat(s).timestamp()
def stats(values):
    values=sorted(v for v in values if isinstance(v,(int,float)))
    if not values:return None
    return {'n':len(values),'min':round(values[0],3),'median':round(statistics.median(values),3),
            'p95':round(values[max(0,math.ceil(len(values)*.95)-1)],3),'max':round(values[-1],3)}
def compact(s):return ''.join(s.split())
def distance(a,b):
    previous=list(range(len(b)+1))
    for i,c in enumerate(a,1):
        row=[i]
        for j,d in enumerate(b,1):row.append(min(row[-1]+1,previous[j]+1,previous[j-1]+(c!=d)))
        previous=row
    return previous[-1]

refs=json.loads((ROOT/'work/seabed-manual-reference.json').read_text(encoding='utf-8'))
refs=[r for r in refs if 27<=r['n']<=77 and r.get('kind')!='chapter']
cases={c['case']:c for c in read('work/seabed-acceptance-cases.jsonl')}
observations=read('work/seabed-acceptance-30min.jsonl')
native=read('work/native-verification.jsonl')
display={r['request_id']:r for r in native if r['kind']=='display'}
stable=[r for r in native if r['kind']=='capture' and r['phase']=='stable']
repeated={28,29,49,50,52,53,56,61,62,65,68,70,71,74}
newpage={27,30,35,36,43,48,55,63,69,77}
missing={33,51}
decor={27,48,55,69}
rows=[]
for ref in refs:
    n=ref['n'];name=ref.get('case',f'cpu-acceptance-{n}')
    case=cases[name];cap=case['caption'];history=case.get('history')
    usable=bool(history and history['terminal']=='final' and n not in missing)
    source=history['source_text'] if usable else ''
    ja=ref.get('ja',ref.get('text',''))
    row={'n':n,'case':name,'reference':ja,'input':source,'request_id':cap.get('request_id'),
         'epoch':cap.get('epoch'),'completed_response':usable,'new_page':n in newpage,
         'repeated_old_input':n in repeated,'missed_or_timeout':n in missing,
         'background_fragments':n in decor,'note':ref.get('note'),
         'payload_edits':distance(compact(ja),compact(source)),'reference_chars':len(compact(ja)),
         'cpu_mode':case['model']['execution_mode'],'timings':history.get('timings') if usable else None,
         'prompt_echo':bool(usable and any(t in (history.get('translation') or '') for t in
             ('参考以下术语表','根据以上术语表','历史翻译：')))}
    if usable and cap.get('request_id') in display:
        end=timestamp(display[cap['request_id']]['at']);accepted=timestamp(history['at'])
        candidates=[r for r in stable if r['text']==source and accepted-5<=timestamp(r['at'])<=accepted+.5]
        if candidates:
            start=min(candidates,key=lambda r:abs(timestamp(r['at'])-accepted))
            row['stable_to_dispatcher_ms']=round((end-timestamp(start['at']))*1000,3)
            row['approx_capture_to_dispatcher_ms']=round(row['stable_to_dispatcher_ms']+
                sum(row['timings'][k] for k in ('capture_ms','ocr_ms','stable_wait_ms')),3)
    rows.append(row)

summary={'dialogue_samples':len(rows),'completed_responses':sum(r['completed_response'] for r in rows),
    'missing_or_timeout':[r['n'] for r in rows if r['missed_or_timeout']],
    'repeat_input_samples':sorted(repeated),'append_samples':sum(not r['new_page'] for r in rows),
    'background_fragment_samples':sorted(decor),'prompt_echo_samples':[r['n'] for r in rows if r['prompt_echo']],
    'execution_modes':dict(Counter(r['cpu_mode'] for r in rows)),
    'payload_cer':sum(r['payload_edits'] for r in rows)/sum(r['reference_chars'] for r in rows),
    'payload_cer_definition':'Submitted new-text payload versus manually transcribed new text; includes repeated old rows and missing samples. NOT raw OCR CER.',
    'timing_ms':{k:stats([r['timings'][k] for r in rows if r['timings']]) for k in
        ('capture_ms','ocr_ms','stable_wait_ms','queue_ms','inference_ms')},
    'stable_to_dispatcher_ms':stats([r.get('stable_to_dispatcher_ms') for r in rows]),
    'approx_capture_to_dispatcher_ms':stats([r.get('approx_capture_to_dispatcher_ms') for r in rows]),
    'display_definition':'Native final event receipt/dispatcher update, not measured pixel paint. Successful response timings include malformed outputs; 2 missing samples are reported separately.',
    'observation':{'first':observations[0]['at'],'last':observations[-1]['at'],
        'last_sample_elapsed_s':observations[-1]['observed_seconds'],'samples':len(observations),
        'states':dict(Counter(o.get('state') for o in observations)),
        'modes':dict(Counter(o.get('model',{}).get('execution_mode') for o in observations)),
        'foreground_samples':sum((o.get('game') or {}).get('foreground') is True for o in observations),
        'bound_samples':sum((o.get('game') or {}).get('bound') is True for o in observations),
        'observer_errors':sum('observer_error' in o for o in observations),
        'epochs':dict(Counter((o.get('game') or {}).get('epoch') for o in observations)),
        'free_vram_mib':stats([(o.get('gpu') or {}).get('free_mib') for o in observations]),
        'processes':{label:{k:stats([(o.get('processes',{}).get(label) or {}).get(k) for o in observations])
            for k in ('working_set_mib','private_mib','cpu_total_percent')} for label in
            ('desktop','backend','ocr','game','model')}}}
pressure=read('work/seabed-cpu-recovery.jsonl');recoveries=[]
for pid in sorted({r['fixture_pid'] for r in pressure}):
    trial=[r for r in pressure if r['fixture_pid']==pid]
    low=next((r for r in trial if r['state']=='paused'),None)
    cpu=next((r for r in trial if r['state']=='ready' and r['model']['execution_mode']=='cpu'),None)
    if low and cpu:recoveries.append({'fixture_pid':pid,'low_at':low['at'],'cpu_at':cpu['at'],
        'wall_seconds':round(cpu['seconds']-low['seconds'],3),
        'nonforeground_samples':sum(not (r.get('game') or {}).get('foreground') for r in trial if low['seconds']<=r['seconds']<=cpu['seconds'])})
summary['controlled_pressure_recoveries']=recoveries
summary['build_hashes_unchanged']=json.loads((ROOT/'work/seabed-acceptance-build-hashes.json').read_text(encoding='utf-8-sig'))==json.loads((ROOT/'work/seabed-acceptance-build-hashes-end.json').read_text(encoding='utf-8-sig'))
(ROOT/'work/seabed-acceptance-analysis.json').write_text(json.dumps({'summary':summary,'samples':rows},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
