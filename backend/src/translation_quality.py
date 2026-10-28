"""Conservative output repairs and rejection reasons; never invent missing variables."""
from collections import Counter
import re

CONTROL = re.compile(r'\$?\{[^{}\n]+\}|%%|%(?:\d+\$)?[-+0# ]*(?:\d+|\*)?(?:\.(?:\d+|\*))?(?:hh|ll|[hlLzjt])?[sdifuxXocgeEG]|'
                     r'\\[vncVNC]\[\d+\]|\\[nrtNRT](?![A-Za-z0-9_\[])|\[[A-Za-z_][A-Za-z0-9_]*\]')
PROMPT_MARKERS = ('参考以下术语表（可为空', '根据以上术语表的对应关系和备注',
                  '历史翻译：', '你是一个视觉小说翻译模型')

def protect_controls(source):
    """One named surrogate per observed control, only for the bounded retry.

    Restoration is permitted only after the surrogate output passes validation.
    The original request/history is never changed and missing markers are never
    filled in. Unique occurrences keep positional order verifiable afterwards.
    """
    prefix='GT_KEEP_'
    while prefix in source:prefix='_'+prefix
    tokens={}
    def replace(match):
        marker='{'+prefix+str(len(tokens))+'}'
        tokens[marker]=match.group();return marker
    return CONTROL.sub(replace,source),tokens

def normalize(source, result):
    result = result.replace('\r\n', '\n').replace('\r', '\n').strip()
    original = result
    if '```' not in source and re.fullmatch(r'```(?:text|plaintext|zh|中文)?\s*\n[\s\S]*\n```', result):
        result = result.split('\n', 1)[1].rsplit('\n', 1)[0].strip()
    if '\n' in source and '\\n' not in source and '\n' not in result:
        result = result.replace('\\n', '\n')
    # Restore only a visibly present, exact named token in alternate typography.
    # A missing token, wrong name, duplicate or reordered token is never guessed.
    for token in set(CONTROL.findall(source)):
        if token.startswith(('{','${')):
            prefix='$' if token.startswith('$') else ''
            inner = token[len(prefix)+1:-1]
            if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*|\d+', inner):
                result = re.sub(re.escape(prefix)+r'[｛{]\s*'+re.escape(inner)+r'\s*[｝}]', lambda _:token, result)
        elif token.startswith('%'):
            result = re.sub(r'[%％]\s*'+re.escape(token[1:]), lambda _:token, result)
    warnings = [] if result == original else [{'code':'normalized_format','message':'已修正模型输出的外层包装或可明确恢复的格式，原文保持不变。'}]
    return result, warnings

def rejection(source, result, kind):
    if not result.strip():
        return 'EMPTY_TRANSLATION', '模型没有返回译文；自动重试仍未完成，原文已保留。'
    if any(marker in result and marker not in source for marker in PROMPT_MARKERS):
        return 'PROMPT_ECHO', '模型输出了翻译指令或历史内容；已阻止显示和写入上下文，原文已保留。'
    expected, actual = Counter(CONTROL.findall(source)), Counter(CONTROL.findall(result))
    if expected != actual:
        return 'FORMAT_DAMAGE', '模型改变了变量或控制符；自动修复仍未完成，原文已保留。'
    def positional(text):
        return [t for t in CONTROL.findall(text) if t.startswith('\\') or
                (t.startswith('%') and t!='%%' and not re.match(r'%\d+\$',t))]
    if positional(source) != positional(result):
        return 'FORMAT_DAMAGE', '模型改变了位置变量或控制符的顺序；自动修复仍未完成，原文已保留。'
    if kind != 'ocr' and source.replace('\r\n','\n').replace('\r','\n').strip().count('\n') != result.count('\n'):
        return 'LINE_FORMAT_DAMAGE', '模型改变了原文分行；逐行修复仍未完成，原文已保留。'
    if len(result) > max(240, len(source)*4+80):
        return 'OUTPUT_TOO_LONG', '模型输出明显超出当前台词长度；已阻止显示，原文已保留。'
    return None
