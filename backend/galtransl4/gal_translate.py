"""GalTransl-v4 Japanese-to-Chinese client using the publisher's format."""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parent
SYSTEM='你是一个视觉小说翻译模型，可以通顺地使用给定的术语表以指定的风格将日文翻译成简体中文，并联系上下文正确使用人称代词，注意不要混淆使役态和被动态的主语和宾语，不要擅自添加原文中没有的特殊符号，也不要擅自增加或减少换行。不要猜测原文未明确的性别或第三人称。省略的主语无法确定时保留省略，不擅自补出人物。'
REPAIR_EXAMPLE_SOURCE='{GT_EXAMPLE_0}から{GT_EXAMPLE_1}を引くと{GT_EXAMPLE_2}になる。'
REPAIR_EXAMPLE_RESULT='{GT_EXAMPLE_0}减去{GT_EXAMPLE_1}等于{GT_EXAMPLE_2}。'

def payload(text,context='',glossary='',seed=42,*,repair=False):
    history=('历史翻译：'+context+'\n\n') if context else ''
    glossary='\n'.join(re.sub(r'\s*->\s*','->',line.strip().replace('→','->')) for line in re.split('[;；\n]',glossary) if line.strip())
    prompt=history+'参考以下术语表（可为空，格式为src->dst #备注）：\n'+glossary+'\n根据以上术语表的对应关系和备注，结合历史剧情和上下文，将下面的文本从日文翻译成简体中文：\n'+text
    messages=[{'role':'system','content':SYSTEM}]
    if repair:
        # A separate, short formatting example is used only after failed token
        # validation. It is not game history or part of the captured source.
        messages.extend([
            {'role':'user','content':'将下面的文本从日文翻译成简体中文，原样保留每个变量：\n'+REPAIR_EXAMPLE_SOURCE},
            {'role':'assistant','content':REPAIR_EXAMPLE_RESULT}])
    messages.append({'role':'user','content':prompt})
    return {'model':'galtransl4-ja-zh','messages':messages,'temperature':0.1,'top_p':0.8,'top_k':20,'repeat_penalty':1.0,'max_tokens':384,'seed':seed,'stream':False}

def request(body):
    port=json.loads((ROOT/'service-config.json').read_text(encoding='utf-8'))['port']
    req=urllib.request.Request(f'http://127.0.0.1:{port}/v1/chat/completions',data=json.dumps(body,ensure_ascii=False).encode('utf-8'),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=120) as r:data=json.load(r)
    choice=data['choices'][0]
    if choice.get('finish_reason')!='stop':raise RuntimeError('Translation did not finish normally')
    if choice['message'].get('reasoning_content'):raise RuntimeError('Thinking unexpectedly enabled')
    return choice['message']['content'].strip()

@lru_cache(maxsize=128)
def translated_context(context,glossary=''):
    # Publisher history is Chinese. Raw Japanese context is translated once.
    if any('\u3040'<=c<='\u30ff' for c in context):return request(payload(context,glossary=glossary))
    return context

def prepared_payload(text,context='',glossary='',seed=42):
    return payload(text,translated_context(context,glossary) if context else '',glossary,seed)

def assess_risks(source,translation):
    issues=[]
    controls=re.findall(r'\{[^{}]+\}|%(?:\d+\$)?[sdif]|\[[A-Za-z_][A-Za-z0-9_]*\]',source)
    if any(source.count(token)!=translation.count(token) for token in set(controls)):
        issues.append({'code':'format_damage','message':'译文的变量或控制符数量与原文不一致。'})
    if source.count('\n')!=translation.count('\n'):
        issues.append({'code':'line_count_changed','message':'译文换行数量与原文不一致。'})
    if re.search('[他她]',translation) and not re.search('彼女|彼|男性|女性|男の子|女の子',source):
        issues.append({'code':'inferred_gender','message':'译文补出了原文未明确的性别，请结合人物信息复核。'})
    if re.search('一人にして|大丈夫|付き合|今さら|今更|わけじゃない',source):
        issues.append({'code':'context_sensitive','message':'此句包含人称省略、否定或多义表达，请对照前文复核。'})
    return issues

def translate(text,context='',glossary=''):
    result=request(prepared_payload(text,context,glossary))
    damage=[issue for issue in assess_risks(text,result) if issue['code'] in ['format_damage','line_count_changed']]
    if damage:raise RuntimeError(' '.join(issue['message'] for issue in damage))
    return result

def interactive(context='',glossary=''):
    history=[translated_context(context,glossary)] if context else []
    print('粘贴一条日文后按回车；/reset 清空前文，/quit 退出。切换作品或场景时请清空前文。')
    while True:
        try:source=input('日文> ').strip()
        except (EOFError,KeyboardInterrupt):print();break
        if source=='/quit':break
        if source=='/reset':history.clear();translated_context.cache_clear();print('前文已清空。');continue
        if not source:continue
        try:
            selected=[]
            for entry in reversed(history[-4:]):
                if sum(len(part) for part in selected)+len(entry)>900:break
                selected.insert(0,entry)
            context='\n'.join(selected)
            result=translate(source,context,glossary)
            print('中文> '+result)
            issues=assess_risks(source,result)
            if issues:print('需复核：'+' '.join(issue['message'] for issue in issues))
            if any(issue['code']=='inferred_gender' for issue in issues):
                print('此句疑似补错性别，未写入自动前文；请人工确认后再使用。')
                continue
            history.append(result)
            history=history[-4:]
        except (OSError,urllib.error.URLError,RuntimeError) as error:
            print('翻译失败：'+str(error)+'。请确认服务窗口已显示 Ready。')

def main():
    sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    sys.stderr.reconfigure(encoding='utf-8',errors='replace')
    parser=argparse.ArgumentParser()
    parser.add_argument('text',nargs='?')
    parser.add_argument('--context',default='',help='Chinese history, or raw Japanese history to translate first')
    parser.add_argument('--glossary',default='')
    parser.add_argument('--glossary-file',type=Path,help='UTF-8 glossary, one src->dst per line')
    parser.add_argument('--context-file',type=Path,help='UTF-8 Chinese history or Japanese context')
    parser.add_argument('--file',type=Path)
    parser.add_argument('--json',action='store_true',help='Return source, translation and rule-based review flags')
    parser.add_argument('--interactive',action='store_true',help='Translate pasted lines with rolling Chinese history')
    args=parser.parse_args()
    if args.glossary_file:args.glossary=args.glossary_file.read_text(encoding='utf-8-sig')
    if args.context_file:args.context=args.context_file.read_text(encoding='utf-8-sig')
    if args.interactive:return interactive(args.context,args.glossary)
    text=args.file.read_text(encoding='utf-8') if args.file else args.text
    if text is None:text=sys.stdin.read()
    if not text.strip():parser.error('Provide Japanese text')
    result=translate(text,args.context,args.glossary)
    issues=assess_risks(text,result)
    if args.json:
        print(json.dumps({'source':text,'translation':result,'review_required':bool(issues),'review_issues':issues},ensure_ascii=False))
    else:
        print(result)
        if issues:print('需复核：'+' '.join(issue['message'] for issue in issues),file=sys.stderr)

if __name__=='__main__':
    try:main()
    except (OSError,urllib.error.URLError,RuntimeError) as error:
        print('翻译失败：'+str(error)+'。请确认本地服务已启动且窗口显示 Ready。',file=sys.stderr)
        sys.exit(1)
