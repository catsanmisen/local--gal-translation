"""Production layout contract; concurrent frontend changes fail with a clear diagnostic."""
from html.parser import HTMLParser
from engine import ClientError

VERSION='connected-layout-3'
REQUIRED_IDS=frozenset("""
model-mode model-reserve model-runtime model-policy-hint btn-model-save settings-input-sources-title
wallpaper-relief wallpaper-runtime
theme-toggle mock-bar mode-badge stream-empty input-ja input-speaker btn-reset-session btn-to-subtitle
page-subtitle page-glossary page-history btn-glossary-save btn-history-clear page-settings sub-clickthrough
sub-font sub-opacity stream-status state-text state-pill vram-value metric-vram model-value session-value
glossary-version btn-start btn-stop btn-translate btn-cancel banner-vram banner-vram-desc clipboard-switch
banner-error banner-error-title banner-error-desc char-count field-manual input-error source-kind field-clipboard
btn-vram-recheck banner-error-close stream-tag stream-original stream-translation stream-meta stream-content
stream-actions stream-skeleton btn-retry sub-prev-ja sub-prev-zh subtitle-preview sub-mode sub-font-value
sub-opacity-value btn-open-subtitle glossary-body btn-glossary-add banner-glossary banner-glossary-desc
banner-glossary-close btn-glossary-export btn-glossary-import history-empty history-pager pager-prev pager-next
pager-info history-list btn-history-export profile-grid
btn-backlog btn-backlog-close btn-history-refresh
""".split())
REQUIRED_SCRIPTS=frozenset(('js/sse.js','js/backlog.js','js/mock-api.js','js/app.js'))

class Layout(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids=set()
        self.duplicates=set()
        self.scripts=set()
        self.head=False
    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if tag=='head':self.head=True
        if values.get('id'):
            name=values['id']
            if name in self.ids:self.duplicates.add(name)
            self.ids.add(name)
        if tag=='script' and values.get('src'):
            self.scripts.add(values['src'].split('?')[0])

def validate_layout(html):
    layout=Layout();layout.feed(html)
    missing=REQUIRED_IDS-layout.ids
    duplicate=layout.duplicates & REQUIRED_IDS
    scripts=REQUIRED_SCRIPTS-layout.scripts
    if missing or duplicate or scripts or not layout.head:
        detail=[]
        if missing:detail.append('缺少控件：'+', '.join(sorted(missing)))
        if duplicate:detail.append('重复控件：'+', '.join(sorted(duplicate)))
        if scripts:detail.append('脚本入口变化：'+', '.join(sorted(scripts)))
        if not layout.head:detail.append('缺少 head')
        raise ClientError('UI_LAYOUT_MISMATCH','前端布局与连接层需要同步；'+'；'.join(detail),503)
