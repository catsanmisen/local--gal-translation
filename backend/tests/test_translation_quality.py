"""Actual rejected-output cases, bounded repair and stale-request safety."""
import sys
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from translation_quality import normalize, rejection
from engine import REPAIR_EXAMPLE_RESULT
import test_backend as baseline
from test_backend import body, ended

class QualityTests(unittest.TestCase):
    def test_typographic_variable_can_be_restored_without_guessing(self):
        result,warnings=normalize('名前は{name}、%sです。','名字是｛ name ｝，％s。')
        self.assertEqual(result,'名字是{name}，%s。');self.assertTrue(warnings)
        self.assertIsNone(rejection('名前は{name}、%sです。',result,'manual'))
    def test_missing_duplicate_or_invented_controls_remain_invalid(self):
        for result in ('名字没了','{name}{name}','{other}'):
            self.assertEqual(rejection('名前は{name}です。',result,'ocr')[0],'FORMAT_DAMAGE')
    def test_number_format_and_engine_variables_are_not_silently_dropped(self):
        source=r'残高は%02d、${name}、\v[1]。'
        self.assertIsNone(rejection(source,r'余额%02d，${name}，\v[1]。','ocr'))
        for wrong in (r'余额%d，${name}，\v[1]。',r'余额%02d，{name}，\v[1]。',r'余额%02d，${name}，[1]。'):
            self.assertEqual(rejection(source,wrong,'ocr')[0],'FORMAT_DAMAGE')
    def test_wrapping_is_not_variable_damage_for_ocr(self):
        self.assertIsNone(rejection('私たちは\n歩いた。','我们走着。','ocr'))
        self.assertEqual(rejection('私たちは\n歩いた。','我们走着。','hook')[0],'LINE_FORMAT_DAMAGE')
    def test_positional_format_order_is_preserved_but_named_tokens_can_move(self):
        self.assertEqual(rejection('%sは%d歳。','%d岁，名字%s。','ocr')[0],'FORMAT_DAMAGE')
        self.assertEqual(rejection(r'\c[1]朝\c[0]',r'\c[0]早晨\c[1]','ocr')[0],'FORMAT_DAMAGE')
        self.assertIsNone(rejection('%1$sは%2$d歳。','%2$d岁，名字%1$s。','ocr'))
        self.assertIsNone(rejection('{name}は{city}へ。','去{city}的{name}。','ocr'))
    def test_escaped_line_controls_and_compound_printf_formats_are_guarded(self):
        source=r'朝\n夜、%+#08.2f、%lld、%%s。'
        self.assertIsNone(rejection(source,r'早晨\n夜晚，%+#08.2f，%lld，%%s。','ocr'))
        for target in ('早晨\n夜晚，%+#08.2f，%lld，%%s。',r'早晨\n夜晚，%.2f，%lld，%%s。'):
            self.assertEqual(rejection(source,target,'ocr')[0],'FORMAT_DAMAGE')
    def test_crlf_code_wrapper_and_escaped_newlines(self):
        self.assertEqual(normalize('朝。\n夜。','```text\n早晨。\\n夜晚。\n```')[0],'早晨。\n夜晚。')
        self.assertEqual(normalize('朝。\r\n夜。','早晨。\r\n夜晚。')[0],'早晨。\n夜晚。')
    def test_prompt_echo_is_rejected_without_rejecting_a_literal_quote(self):
        text='参考以下术语表（可为空，格式为src->dst #备注）：'
        self.assertEqual(rejection('朝。',text,'ocr')[0],'PROMPT_ECHO')
        self.assertIsNone(rejection(text,text,'manual'))
    def test_empty_and_pathological_length_have_specific_codes(self):
        self.assertEqual(rejection('朝。','  ','ocr')[0],'EMPTY_TRANSLATION')
        self.assertEqual(rejection('朝。','啊'*300,'ocr')[0],'OUTPUT_TOO_LONG')
    def test_uppercase_hook_line_controls_cannot_be_dropped(self):
        source=r'朝\N夜\C[1]。'
        self.assertIsNone(rejection(source,r'早晨\N夜晚\C[1]。','hook'))
        problem=rejection(source,r'早晨夜晚\C[1]。','hook')
        self.assertIsNotNone(problem);self.assertEqual(problem[0],'FORMAT_DAMAGE')

class RepairTests(unittest.TestCase):
    def setUp(self):baseline.CoreTests.setUp(self)
    def tearDown(self):baseline.CoreTests.tearDown(self)
    def submit_auto(self,text):
        b=body(self.session,text=text);b['source_kind']='ocr'
        return self.client.submit(b,wait_for_engine=True)
    def test_empty_retry_is_one_request_and_one_durable_history(self):
        results=iter(['','今天是晴天。'])
        with patch.object(self.engine,'generate',side_effect=lambda *args:next(results)) as generate:
            event,data=ended(self.submit_auto('今日は晴れです。'))
        self.assertEqual(event,'final');self.assertEqual(generate.call_count,2)
        self.assertEqual(len(self.storage.history()),1);self.assertEqual(self.client.context,['今天是晴天。'])
        self.assertIn('translation_repaired',[w['code'] for w in data['warnings']])
    def test_rejected_output_and_repair_are_reproducible_in_local_log_only(self):
        source='%sは%d歳。';self.client.context=['前文。']
        first='  %s岁。\n';fixed='{GT_KEEP_0}今年{GT_KEEP_1}岁。'
        with self.assertLogs(level='INFO') as logs, \
             patch.object(self.engine,'generate',return_value=first), \
             patch.object(self.engine,'generate_repair',create=True,return_value=fixed):
            req=self.submit_auto(source);event,data=ended(req)
        records=[json.loads(r.getMessage().split(' ',1)[1]) for r in logs.records
                 if r.getMessage().startswith('translation_quality ')]
        self.assertEqual([r['stage'] for r in records],['initial','repair','terminal'])
        initial=records[0]
        self.assertEqual(initial['source_text'],source);self.assertEqual(initial['context'],['前文。'])
        self.assertEqual(initial['raw_output'],first);self.assertEqual(initial['rejection'],'FORMAT_DAMAGE')
        self.assertEqual(initial['normalized_output'],'%s岁。')
        self.assertEqual(records[1]['raw_output'],fixed);self.assertEqual(records[-1]['terminal'],'final')
        for record in records:
            self.assertEqual({k:record[k] for k in ('request_id','session_id','epoch','sequence')},
                             {k:req.body[k] for k in ('request_id','session_id','epoch','sequence')})
        self.assertEqual(event,'final');self.assertEqual(data['translation'],'%s今年%d岁。')
        self.assertNotIn('raw_output',json.dumps(req.events,ensure_ascii=False))
        self.assertNotIn('raw_output',json.dumps(self.storage.history(),ensure_ascii=False))
        self.assertEqual(len(self.storage.history()),1)

    def test_failed_row_repair_log_keeps_each_output_and_error_terminal(self):
        outputs={'朝。\n夜。':'早晨与夜晚。','朝。':'早晨。','夜。':'  '}
        with self.assertLogs(level='INFO') as logs, \
             patch.object(self.engine,'generate',side_effect=lambda source,*args:outputs[source]):
            event,data=ended(self.client.submit(body(self.session,text='朝。\n夜。')))
        records=[json.loads(r.getMessage().split(' ',1)[1]) for r in logs.records]
        self.assertEqual([r['stage'] for r in records],['initial','repair','repair','terminal'])
        self.assertEqual([r['raw_output'] for r in records[:-1]],['早晨与夜晚。','早晨。','  '])
        self.assertEqual(records[-2]['rejection'],'EMPTY_TRANSLATION')
        self.assertEqual(records[-1]['terminal'],'error');self.assertEqual(records[-1]['code'],'EMPTY_TRANSLATION')
        self.assertEqual(event,'error');self.assertFalse(self.client.context)

    def test_failure_diagnostics_bound_large_outputs_and_mark_truncation(self):
        self.client.context=['前'*9000];outputs=iter(['坏'*9000,'早晨。'])
        with self.assertLogs(level='INFO') as logs, \
             patch.object(self.engine,'generate',side_effect=lambda *args:next(outputs)):
            event,_=ended(self.submit_auto('朝。'))
        initial=json.loads(logs.records[0].getMessage().split(' ',1)[1])
        self.assertEqual(initial['raw_output'],'坏'*8000)
        self.assertEqual(initial['context'],['前'*8000])
        self.assertIn('raw_output',initial['truncated_fields']);self.assertIn('context',initial['truncated_fields'])
        self.assertEqual(event,'final')

    def test_engine_raised_format_error_keeps_trace_and_terminal_without_public_raw_output(self):
        self.client.context=['前文。']
        self.engine.last_generation_trace={'raw_output':'未验证片段','reasoning_output':'意外推理','finish_reason':None}
        with self.assertLogs(level='INFO') as logs, \
             patch.object(self.engine,'generate',side_effect=baseline.ClientError('FORMAT_DAMAGE','模型意外产生推理内容。',502)):
            req=self.submit_auto('朝。');event,data=ended(req)
        records=[json.loads(r.getMessage().split(' ',1)[1]) for r in logs.records]
        self.assertEqual([r['stage'] for r in records],['generation_error','terminal'])
        self.assertEqual(records[0]['raw_output'],'未验证片段');self.assertEqual(records[0]['reasoning_output'],'意外推理')
        self.assertEqual(records[0]['source_text'],'朝。');self.assertEqual(records[0]['context'],['前文。'])
        self.assertEqual(records[0]['request_id'],req.body['request_id'])
        self.assertEqual(records[-1]['terminal'],'error');self.assertEqual(data['code'],'FORMAT_DAMAGE')
        self.assertEqual(event,'error');self.assertEqual(self.client.context,['前文。'])
        self.assertNotIn('未验证片段',str(req.events));self.assertNotIn('未验证片段',str(self.storage.history()))

    def test_engine_exception_during_repair_retains_partial_repair_evidence(self):
        def generate(*args):
            if not getattr(self.engine,'last_generation_trace',None):
                self.engine.last_generation_trace={'raw_output':'','reasoning_output':'','finish_reason':'stop'};return ''
            self.engine.last_generation_trace={'raw_output':'早','reasoning_output':'','finish_reason':'length'}
            raise baseline.ClientError('GENERATION_TRUNCATED','未正常完成。',502)
        with self.assertLogs(level='INFO') as logs,patch.object(self.engine,'generate',side_effect=generate):
            req=self.submit_auto('朝。');event,data=ended(req)
        records=[json.loads(r.getMessage().split(' ',1)[1]) for r in logs.records]
        self.assertEqual([r['stage'] for r in records],['initial','generation_error','terminal'])
        self.assertEqual(records[1]['raw_output'],'早');self.assertEqual(records[1]['finish_reason'],'length')
        self.assertTrue(records[1]['repair']);self.assertEqual(records[1]['request_id'],req.body['request_id'])
        self.assertEqual(event,'error');self.assertEqual(data['code'],'GENERATION_TRUNCATED')
        self.assertFalse(self.client.context);self.assertIsNone(self.storage.history()[0]['translation'])
    def test_failed_retry_is_bounded_and_never_poisoned_context(self):
        with patch.object(self.engine,'generate',return_value='') as generate:
            req=self.submit_auto('朝。');event,data=ended(req)
        self.assertEqual(event,'error');self.assertEqual(data['code'],'EMPTY_TRANSLATION')
        self.assertEqual(generate.call_count,2);self.assertFalse(self.client.context)
        self.assertEqual(self.storage.history()[0]['source_text'],'朝。')
    def test_echo_never_reaches_auto_delta_and_repair_has_no_history(self):
        self.client.context=['以前的合法译文。'];calls=[]
        def generate(source,context,glossary,cancel,on_delta):
            calls.append(list(context))
            output='历史翻译：坏输出' if len(calls)==1 else '现在到了。'
            on_delta(output);return output
        with patch.object(self.engine,'generate',side_effect=generate):
            req=self.submit_auto('今、着いた。');event,data=ended(req)
        self.assertEqual(event,'final');self.assertEqual(data['translation'],'现在到了。')
        self.assertEqual(calls,[['以前的合法译文。'],[]])
        self.assertFalse(any(name=='delta' for name,_ in req.events))
        self.assertNotIn('历史翻译',str(self.client.context))
    def test_strict_multiline_repaired_per_row_with_blank_rows_kept(self):
        calls=[]
        def generate(source,*args):
            calls.append(source);return {'朝。\n\n夜。':'早晨和夜晚。','朝。':'早晨。','夜。':'夜晚。'}[source]
        with patch.object(self.engine,'generate',side_effect=generate):
            event,data=ended(self.client.submit(body(self.session,text='朝。\n\n夜。')))
        self.assertEqual(event,'final');self.assertEqual(data['translation'],'早晨。\n\n夜晚。')
        self.assertEqual(calls,['朝。\n\n夜。','朝。','夜。'])
    def test_blank_output_during_per_row_repair_cannot_be_completed(self):
        outputs={'朝。\n夜。':'早晨与夜晚。','朝。':'早晨。','夜。':''}
        with patch.object(self.engine,'generate',side_effect=lambda source,*args:outputs[source]) as generate:
            event,data=ended(self.client.submit(body(self.session,text='朝。\n夜。')))
        self.assertEqual(event,'error');self.assertEqual(data['code'],'EMPTY_TRANSLATION')
        self.assertEqual(generate.call_count,3);self.assertFalse(self.client.context)
        self.assertEqual(self.storage.history()[0]['source_text'],'朝。\n夜。')
    def test_superseded_failed_output_does_not_start_repair(self):
        entered=threading.Event();release=threading.Event();calls=[]
        def generate(source,*args):
            calls.append(source)
            if len(calls)==1:entered.set();release.wait(2);return ''
            return '下一句。'
        with patch.object(self.engine,'generate',side_effect=generate):
            a=self.submit_auto('朝。');self.assertTrue(entered.wait(1))
            b=body(self.session,2,text='次の文。');b['source_kind']='ocr'
            new=self.client.submit(b,wait_for_engine=True);release.set()
            self.assertEqual(ended(a)[0],'cancelled');self.assertEqual(ended(new)[0],'final')
        self.assertEqual(calls,['朝。','次の文。']);self.assertEqual(self.client.subtitle['zh'],'下一句。')

    def test_cancel_reset_and_game_switch_during_repair_cannot_commit_stale_output(self):
        self.storage.save_profile({'id':'other-game','name':'Other game','glossary':[],'prefs':{}})
        for action in ('cancel','reset','game'):
            with self.subTest(action=action):
                session=self.client.create_session();entered=threading.Event();release=threading.Event()
                def repair(*args):
                    entered.set();release.wait(2);return '{GT_KEEP_0}今年{GT_KEEP_1}岁。'
                with patch.object(self.engine,'generate',side_effect=lambda source,*args:'%s岁。' if '%s' in source else '新游戏台词。'), \
                     patch.object(self.engine,'generate_repair',create=True,side_effect=repair):
                    req=self.client.submit(body(session,text='%sは%d歳。',request_id='old-'+action))
                    try:
                        self.assertTrue(entered.wait(1))
                        if action=='cancel':self.client.cancel(req.body['request_id']);current=session
                        elif action=='reset':current=self.client.reset(session['session_id'])
                        else:current=self.client.create_session('other-game')
                        newest=self.client.submit(body(current,2,text='新しい台詞。',request_id='new-'+action))
                    finally:release.set()
                    self.assertEqual(ended(req)[0],'cancelled');self.assertEqual(ended(newest)[0],'final')
                history=self.storage.history(session=session['session_id'])
                old=next(h for h in history if h['request_id']==req.body['request_id'])
                self.assertIsNone(old['translation']);self.assertEqual(old['source_text'],'%sは%d歳。')
                self.assertEqual(self.client.subtitle['request_id'],newest.body['request_id'])
                self.assertEqual(self.client.subtitle['zh'],'新游戏台词。')
                self.assertEqual(self.client.context,['新游戏台词。'])

    def test_failed_printf_retry_uses_observed_surrogate_tokens_without_losing_original(self):
        source='%sは%d歳、残高は%02dです。'
        def model(text,context,glossary,cancel,delta):
            # The real Q6 failure dropped %d twice. Named placeholders are a
            # separate repair input; missing output markers must still fail.
            if text==source:return '%s岁，余额是%02d。'
            return text.replace('は','是').replace('歳、残高は','岁，余额是').replace('です。','。')
        with patch.object(self.engine,'generate',side_effect=model):
            req=self.submit_auto(source);event,data=ended(req)
        self.assertEqual(event,'final');self.assertIsNone(rejection(source,data['translation'],'ocr'))
        self.assertNotIn('GT_KEEP',data['translation'])
        self.assertEqual(self.storage.history()[0]['source_text'],source)
        self.assertIn('translation_repaired',[w['code'] for w in data['warnings']])

    def test_missing_repair_placeholder_is_not_recreated_from_the_source(self):
        with patch.object(self.engine,'generate',return_value='变量全没了。'):
            event,data=ended(self.submit_auto('%sは%d歳。'))
        self.assertEqual(event,'error');self.assertEqual(data['code'],'FORMAT_DAMAGE')
        self.assertFalse(self.client.context);self.assertIsNone(self.storage.history()[0]['translation'])

    def test_variables_use_the_constrained_repair_path_after_the_first_failure(self):
        source='%sは%d歳、残高は%02dです。'
        with patch.object(self.engine,'generate',return_value='%s岁，余额是%02d。'), \
             patch.object(self.engine,'generate_repair',create=True,return_value='{GT_KEEP_0}今年{GT_KEEP_1}岁，余额是{GT_KEEP_2}。'):
            event,data=ended(self.submit_auto(source))
        self.assertEqual(event,'final');self.assertEqual(data['translation'],'%s今年%d岁，余额是%02d。')
        self.assertEqual(len(self.storage.history()),1)
        self.assertEqual(self.storage.history()[0]['source_text'],source)

    def test_repair_example_copy_cannot_pass_as_current_printf_dialogue(self):
        with patch.object(self.engine,'generate',return_value='%s岁，余额是%02d。'), \
             patch.object(self.engine,'generate_repair',create=True,return_value=REPAIR_EXAMPLE_RESULT):
            event,data=ended(self.submit_auto('%sは%d歳、残高は%02dです。'))
        self.assertEqual(event,'error');self.assertEqual(data['code'],'FORMAT_DAMAGE')
        self.assertFalse(self.client.context);self.assertIsNone(self.storage.history()[0]['translation'])

    def test_actual_arithmetic_source_can_have_the_example_translation(self):
        with patch.object(self.engine,'generate',return_value='减去等于。'), \
             patch.object(self.engine,'generate_repair',create=True,return_value='{GT_KEEP_0}减去{GT_KEEP_1}等于{GT_KEEP_2}。'):
            event,data=ended(self.submit_auto('%sから%dを引くと%02dになる。'))
        self.assertEqual(event,'final');self.assertEqual(data['translation'],'%s减去%d等于%02d。')

    def test_polite_arithmetic_is_not_blacklisted_by_the_example_wording(self):
        with patch.object(self.engine,'generate',return_value='减去等于。'), \
             patch.object(self.engine,'generate_repair',create=True,return_value='{GT_KEEP_0}减去{GT_KEEP_1}等于{GT_KEEP_2}。'):
            event,data=ended(self.submit_auto('%sから%dを引くと%02dになります。'))
        self.assertEqual(event,'final');self.assertEqual(data['translation'],'%s减去%d等于%02d。')

if __name__=='__main__':unittest.main()
