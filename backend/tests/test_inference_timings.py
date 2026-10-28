"""Production stream measurements and per-request repair accounting, no model."""
import sys
import json
import threading
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from engine import Engine, ClientError
import test_backend as baseline
from test_backend import body, ended


class StreamMeasurements(unittest.TestCase):
    def test_usage_only_final_chunk_records_actual_tokens_and_server_decode_time(self):
        engine=Engine();engine.state='ready';engine.execution_mode='cpu'
        connection=MagicMock();response=connection.getresponse.return_value;response.status=200
        chunks=[{'choices':[{'delta':{'content':'早晨。'},'finish_reason':'stop'}]},
            {'choices':[],'usage':{'prompt_tokens':101,'completion_tokens':4},
             'timings':{'predicted_n':4,'predicted_ms':80,'predicted_per_second':50}}]
        response.readline.side_effect=[('data: '+json.dumps(c)+'\n').encode() for c in chunks]+[b'data: [DONE]\n']
        with patch('engine.http.client.HTTPConnection',return_value=connection), \
             patch.object(engine,'rpc',side_effect=[{'prompt':'template'},{'tokens':[1]},[]]):
            engine.generate('朝。',[],'',threading.Event(),lambda _:None)
        sent=json.loads(connection.request.call_args.args[2])
        self.assertTrue(sent['stream_options']['include_usage'])
        self.assertEqual(engine.last_generation_timings['output_tokens'],4)
        self.assertEqual(engine.last_generation_timings['prompt_tokens'],101)
        self.assertEqual(engine.last_generation_timings['server_decode_ms'],80)

    def test_stream_timings_separate_prepare_first_token_decode_and_slot_release(self):
        engine=Engine();engine.state='ready';engine.execution_mode='cpu';clock=[0.0]
        def rpc(path,*args,**kwargs):
            clock[0]+={'/apply-template':.05,'/tokenize':.02,'/slots':.03}[path]
            return {'/apply-template':{'prompt':'template'},'/tokenize':{'tokens':[1]},'/slots':[{'is_processing':False}]}[path]
        class Response:
            status=200
            def __init__(self):
                self.lines=iter([(2,b'data: {"choices":[{"delta":{"content":"\\u65e9"}}]}\n'),
                    (.3,b'data: {"choices":[{"delta":{"content":"\\u6668\\u3002"}}]}\n'),
                    (.1,b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n'),(.01,b'data: [DONE]\n')])
            def readline(self,*args):
                duration,line=next(self.lines);clock[0]+=duration;return line
        class Connection:
            sock=None
            def __init__(self,*args,**kwargs):pass
            def connect(self):clock[0]+=.1
            def request(self,*args,**kwargs):pass
            def getresponse(self):clock[0]+=.2;return Response()
            def close(self):pass
        with patch.object(engine,'rpc',side_effect=rpc), \
             patch('engine.http.client.HTTPConnection',Connection),patch('engine.time.perf_counter',side_effect=lambda:clock[0]):
            output=engine.generate('朝。',[],'',threading.Event(),lambda _:None)
        self.assertEqual(output,'早晨。')
        self.assertEqual(engine.last_generation_timings,{'prepare_ms':70,'first_token_ms':2300,
            'decode_ms':410,'slot_release_ms':30,'generation_ms':2810})

    def test_preparation_failure_does_not_reuse_previous_generation_metrics(self):
        engine=Engine();engine.last_generation_timings={'generation_ms':9000}
        with patch.object(engine,'rpc',side_effect=ClientError('ENGINE_ERROR','离线')):
            with self.assertRaises(ClientError):engine.generate('朝。',[],'',threading.Event(),lambda _:None)
        self.assertEqual(engine.last_generation_timings,{})

    def test_real_stream_keeps_diagnostic_inputs_for_reasoning_truncation_and_raw_whitespace(self):
        cases=[('FORMAT_DAMAGE',[{'delta':{'reasoning_content':'unexpected reasoning'}}],'','unexpected reasoning',None),
            ('GENERATION_TRUNCATED',[{'delta':{'content':'partial'}},{'delta':{},'finish_reason':'length'}],'partial','','length'),
            (None,[{'delta':{'content':'  早晨。\n'}},{'delta':{},'finish_reason':'stop'}],'  早晨。\n','','stop')]
        for code,chunks,raw,reasoning,finish in cases:
            with self.subTest(code=code):
                engine=Engine();connection=MagicMock();response=connection.getresponse.return_value;response.status=200
                response.readline.side_effect=[('data: '+json.dumps({'choices':[chunk]})+'\n').encode() for chunk in chunks]+[b'data: [DONE]\n']
                with patch('engine.http.client.HTTPConnection',return_value=connection), \
                     patch.object(engine,'rpc',side_effect=[{'prompt':'template'},{'tokens':[1]}]):
                    if code:
                        with self.assertRaises(ClientError) as caught:engine.generate('朝。',[],'',threading.Event(),lambda _:None)
                        self.assertEqual(caught.exception.code,code)
                    else:self.assertEqual(engine.generate('朝。',[],'',threading.Event(),lambda _:None),'早晨。')
                self.assertEqual(engine.last_generation_trace,{'raw_output':raw,'reasoning_output':reasoning,'finish_reason':finish})


class RequestMeasurements(unittest.TestCase):
    def setUp(self):baseline.CoreTests.setUp(self)
    def tearDown(self):baseline.CoreTests.tearDown(self)
    def test_success_preserves_capture_and_persists_model_segments(self):
        def generate(*args):
            self.engine.last_generation_timings={'prepare_ms':7,'first_token_ms':200,'decode_ms':80,'slot_release_ms':3,'generation_ms':290}
            return '早晨。'
        b=body(self.session,text='朝。');b['timings']={'ocr_ms':400}
        with patch.object(self.engine,'generate',side_effect=generate):event,data=ended(self.client.submit(b))
        timing=data['timings'];self.assertEqual(event,'final')
        for key,value in {'ocr_ms':400,'model_prepare_ms':7,'model_first_token_ms':200,
            'model_decode_ms':80,'model_slot_release_ms':3,'generation_count':1,'repair_ms':0}.items():
            self.assertEqual(timing[key],value,key)
        self.assertEqual(self.storage.history()[0]['timings'],timing)

    def test_repair_counts_both_generations_and_does_not_hide_its_cost(self):
        clock=[0.0];calls=[]
        def generate(*args):
            calls.append(args[0]);clock[0]+=.25 if len(calls)==1 else .4
            self.engine.last_generation_timings={'prepare_ms':10,'first_token_ms':100,'decode_ms':80,'slot_release_ms':5}
            return '' if len(calls)==1 else '早晨。'
        b=body(self.session,text='朝。');b['timings']={}
        with patch.object(self.engine,'generate',side_effect=generate),patch('core.time.perf_counter',side_effect=lambda:clock[0]):
            event,data=ended(self.client.submit(b))
        self.assertEqual(event,'final');timing=data['timings']
        self.assertEqual(timing['generation_count'],2);self.assertEqual(timing['repair_ms'],400)
        self.assertEqual(timing['model_prepare_ms'],20);self.assertEqual(timing['model_first_token_ms'],200)
        self.assertEqual(timing['model_decode_ms'],160);self.assertEqual(len(self.storage.history()),1)

    def test_new_request_cannot_inherit_previous_repair_measurements(self):
        b=body(self.session,text='朝。');b['timings']={}
        with patch.object(self.engine,'generate',side_effect=['','早晨。']):ended(self.client.submit(b))
        b=body(self.session,2,text='夜。');b['timings']={}
        event,data=ended(self.client.submit(b))
        self.assertEqual(event,'final');self.assertEqual(data['timings']['generation_count'],1)
        self.assertEqual(data['timings']['repair_ms'],0)

if __name__=='__main__':unittest.main()
