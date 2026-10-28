"""Local authenticated client API and read-only frontend asset hosting."""
import argparse
import hmac
import json
import logging
from logging.handlers import RotatingFileHandler
import mimetypes
import re
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote

from core import Client
from engine import ClientError, Engine, ROOT
from storage import Storage
from clipboard import Clipboard
from cli_config import add_client_port
from ui_contract import validate_layout, VERSION as UI_CONTRACT_VERSION
from game_session import GameSession, validate_game
from ocr_service import OcrService
from wallpaper import WallpaperController

BRIDGE = ROOT / 'backend' / 'bridge'
FRONTEND = ROOT / 'frontend'
ID = r'[A-Za-z0-9_-]{1,100}'

class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False
    def __init__(self, port, database, engine=None):
        self.token = secrets.token_urlsafe(32)
        self.instance_id = uuid.uuid4().hex
        self.leases = {}
        self.lease_lock = threading.Lock()
        self.had_browser = False
        self.finished = threading.Event()
        self.slots = threading.BoundedSemaphore(32)
        # Reserve the endpoint before opening/migrating storage: a conflicting launcher must not
        # mark another running client's unfinished history as interrupted.
        super().__init__(('127.0.0.1', port), Handler)
        try:
            self.wallpaper=WallpaperController() if engine is None else getattr(engine,'wallpaper',None)
            self.engine = engine or Engine(wallpaper=self.wallpaper)
            if self.server_port == getattr(self.engine, 'config', {}).get('port'):
                raise ClientError('INVALID_CONFIG', '客户端端口不能与内部模型端口相同。')
            self.storage = Storage(database)
            self.client = Client(self.engine, self.storage)
            if self.wallpaper:self.wallpaper.recover()
            self.game = GameSession(self.client)
            self.ocr = OcrService()
            self.client.ocr_available = lambda: self.ocr.available
            self.clipboard = Clipboard(self.client)
        except Exception:
            if hasattr(self, 'game'):self.game.close()
            if hasattr(self, 'ocr'):self.ocr.close()
            if hasattr(self, 'clipboard'):self.clipboard.close()
            if hasattr(self, 'client'):self.client.close()
            if getattr(self,'wallpaper',None):self.wallpaper.close()
            if hasattr(self, 'storage'):self.storage.close()
            self.server_close()
            raise
        self.lease_thread = threading.Thread(target=self._leases, daemon=True)
        self.lease_thread.start()

    def _leases(self):
        while not self.finished.wait(2):
            if self.wallpaper:self.wallpaper.tick()
            with self.lease_lock:
                self.leases = {k: v for k, v in self.leases.items() if time.monotonic() - v < 90}
                lost = self.had_browser and not self.leases
                if lost:
                    self.had_browser = False
            if lost:
                self.client.request_stop()

    def dispose(self):
        self.finished.set()
        self.lease_thread.join(timeout=3)
        self.clipboard.close()
        self.game.close()
        self.ocr.close()
        try:self.client.close()
        finally:
            if self.wallpaper:self.wallpaper.close()
        self.server_close()
        self.storage.close()

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        # No request bodies, headers, tokens or source text in access logs.
        logging.info('%s %s', self.command, self.path.split('?')[0])

    def do_GET(self): self.dispatch()
    def do_POST(self): self.dispatch()
    def do_PUT(self): self.dispatch()
    def do_PATCH(self): self.dispatch()
    def do_DELETE(self): self.dispatch()
    def do_OPTIONS(self): self.reply(403, {'error': {'code': 'ORIGIN_DENIED', 'message': '只接受同源调用。'}})

    def reply(self, status, data, content_type='application/json; charset=utf-8'):
        blob = json.dumps(data, ensure_ascii=False).encode('utf-8') if isinstance(data, (dict, list)) else data
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(blob)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('Content-Security-Policy', "frame-ancestors 'none'; base-uri 'self'")
        self.end_headers()
        self.wfile.write(blob)

    def body(self):
        if self.headers.get('Transfer-Encoding'):
            raise ClientError('INVALID_INPUT', '不支持分块请求体。')
        try:
            size = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            raise ClientError('INVALID_INPUT', '请求长度不正确。')
        if not 0 <= size <= 128 * 1024:
            raise ClientError('INPUT_TOO_LONG', '请求体超出限制。', 413)
        if size and self.headers.get_content_type() != 'application/json':
            raise ClientError('INVALID_INPUT', '请求必须使用 application/json。', 415)
        try:
            result = json.loads(self.rfile.read(size)) if size else {}
        except (ValueError, UnicodeError):
            raise ClientError('INVALID_INPUT', 'JSON 格式不正确。')
        if not isinstance(result, dict):
            raise ClientError('INVALID_INPUT', '请求必须是 JSON 对象。')
        return result

    def guard(self, api):
        port = self.server.server_port
        if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
            raise ClientError('ORIGIN_DENIED', '请求地址不允许。', 403)
        origin = self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
            raise ClientError('ORIGIN_DENIED', '只接受本客户端同源请求。', 403)
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            raise ClientError('ORIGIN_DENIED', '拒绝跨站请求。', 403)
        if api and not hmac.compare_digest(self.headers.get('Authorization', '').encode('utf-8'), ('Bearer ' + self.server.token).encode('utf-8')):
            raise ClientError('UNAUTHORIZED', '连接凭据失效，请重新打开客户端。', 401)

    def dispatch(self):
        if not self.server.slots.acquire(blocking=False):
            self.close_connection = True
            return self.reply(503, {'error': {'code': 'BUSY', 'message': '连接过多，请稍后重试。'}})
        try:
            self.connection.settimeout(10)
            parsed = urlsplit(self.path)
            path = unquote(parsed.path)
            api = path.startswith('/api/v1/')
            self.guard(api)
            if not api:
                if self.command != 'GET':
                    raise ClientError('NOT_FOUND', '接口不存在。', 404)
                return self.asset(path)
            route = path[len('/api/v1'):]
            if route == '/ocr-frame' and self.command == 'POST':return self.ocr_frame()
            body = self.body() if self.command in ('POST', 'PUT', 'PATCH') else {}
            method, client = self.command, self.server.client
            if method == 'GET' and route == '/status':
                return self.reply(200, client.status())
            if method == 'POST' and route == '/engine/start':
                with client.lock:
                    self.server.game.manual_paused=False
                    self.server.game.retries.clear()
                client.start()
                return self.reply(202, {'accepted': True})
            if method == 'POST' and route == '/engine/stop':
                self.server.game.manual_stop()
                client.request_stop()
                return self.reply(202, {'accepted': True})
            if method == 'GET' and route == '/engine/slots':
                slots = self.server.engine.rpc('/slots', timeout=2)
                return self.reply(200, [{'id': s['id'], 'is_processing': s['is_processing']} for s in slots])
            if method == 'POST' and route == '/sessions':
                if self.server.game.bound:raise ClientError('GAME_IN_USE','游戏正在自动翻译，请从桌面设置切换游戏。',409)
                return self.reply(201, client.create_session(body.get('profile_id', 'default')))
            if route == '/game-session':
                if method == 'GET':
                    with client.lock:return self.reply(200,self.server.game.status())
                if method == 'PUT':return self.reply(200,self.server.game.update(body,self.headers.get('X-Client-Id','')))
            if route == '/text-events' and method == 'POST':
                return self.reply(202,self.server.game.event(body,self.headers.get('X-Client-Id','')))
            if route == '/subtitle/events' and method == 'GET':
                return self.subtitle_events()
            match = re.fullmatch('/sessions/(' + ID + ')/(reset|glossary|history)', route)
            if match:
                session_id, operation = match.groups()
                if operation == 'reset' and method == 'POST':
                    return self.reply(200, client.reset(session_id))
                if operation == 'glossary' and method == 'PUT':
                    return self.reply(200, client.glossary(session_id, body.get('entries')))
                if operation == 'glossary' and method == 'GET':
                    with client.lock:
                        client._session(session_id)
                        profile = self.server.storage.profile(client.session['profile_id'])
                    return self.reply(200, {'entries': profile['glossary'], 'glossary_version': profile['glossary_version']})
                if operation == 'history' and method == 'GET':
                    client._session(session_id)
                    return self.history(parsed, session=session_id)
            if route == '/translate' and method == 'POST':
                if self.server.game.bound:raise ClientError('GAME_IN_USE','当前由游戏自动会话分配台词序号，请先解除游戏绑定。',409)
                if body.get('source_kind') not in ('manual','clipboard'):raise ClientError('INVALID_INPUT','OCR/HOOK 请使用 text-events。')
                req = client.submit(body)
                return self.stream(req)
            match = re.fullmatch('/requests/(' + ID + ')', route)
            if match:
                with client.lock:
                    req = client.get_request(match[1])
                    if method == 'DELETE':
                        client.cancel(match[1])
                        return self.reply(202, {'accepted': True})
                    if method == 'GET':
                        with req.condition:
                            terminal = req.events[-1][1] if req.terminal else None
                            state = req.events[-1][0] if req.terminal else 'running' if client.active is req else 'queued'
                        return self.reply(200, {'request_id': match[1], 'status': state, 'result': terminal})
            if route == '/history' and method == 'GET':
                return self.history(parsed)
            if route == '/history' and method == 'DELETE':
                query = parse_qs(parsed.query)
                profile_id = query.get('profile_id', [''])[0]
                if not re.fullmatch(ID, profile_id) or len(query.get('profile_id', [])) != 1:
                    raise ClientError('INVALID_PROFILE', '删除历史必须指定一个游戏配置。')
                with client.lock:
                    if not self.server.storage.profile(profile_id):
                        raise ClientError('INVALID_PROFILE', '游戏配置不存在。', 404)
                    deleted = self.server.storage.clear_history(profile_id)
                return self.reply(200, {'deleted': deleted, 'profile_id': profile_id})
            if route == '/profiles' and method == 'GET':
                return self.reply(200, self.server.storage.profiles())
            if route == '/profiles' and method == 'PUT':
                return self.profile(body)
            if route == '/profiles' and method == 'PATCH':
                return self.profile(body, patch=True)
            if route == '/settings':
                if method == 'GET':
                    return self.reply(200, client.settings())
                if method in ('PUT','PATCH'):
                    return self.reply(200, client.update_settings(body))
            if route == '/subtitle' and method == 'GET':
                with client.lock:
                    return self.reply(200, dict(client.subtitle))
            if route == '/clipboard' and method == 'PUT':
                if type(body.get('enabled')) is not bool:
                    raise ClientError('INVALID_INPUT', 'enabled 必须是布尔值。')
                if body['enabled'] and self.server.game.bound:raise ClientError('GAME_IN_USE','自动游戏采集期间不启用全局剪贴板。',409)
                return self.reply(200, self.server.clipboard.enable(body['enabled']))
            if route == '/lease':
                lease_id = self.headers.get('X-Client-Id', '')
                if not re.fullmatch(ID, lease_id):
                    raise ClientError('INVALID_INPUT', '客户端窗口编号缺失。')
                with self.server.lease_lock:
                    if method == 'POST':
                        self.server.leases[lease_id] = time.monotonic()
                        self.server.had_browser = True
                    elif method == 'DELETE':
                        self.server.leases.pop(lease_id, None)
                    else:
                        raise ClientError('NOT_FOUND', '接口不存在。', 404)
                return self.reply(200, {'ok': True})
            if route == '/shutdown' and method == 'POST':
                self.reply(202, {'accepted': True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            raise ClientError('NOT_FOUND', '接口不存在。', 404)
        except ClientError as error:
            self.close_connection = True
            self.reply(error.status, {'error': error.json(), 'request_id': None})
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            self.close_connection = True
        except Exception:
            logging.exception('API operation failed')
            self.close_connection = True
            self.reply(500, {'error': {'code': 'INTERNAL_ERROR', 'message': '后台操作失败，请检查日志。', 'retryable': True}})
        finally:
            self.server.slots.release()

    def history(self, parsed, session=None):
        query = parse_qs(parsed.query)
        try:
            limit, offset = int(query.get('limit', ['100'])[0]), int(query.get('offset', ['0'])[0])
        except ValueError:
            raise ClientError('INVALID_INPUT', '分页参数不正确。')
        if not 1 <= limit <= 200 or not 0 <= offset <= 10000:
            raise ClientError('INVALID_INPUT', '分页参数超出范围。')
        items = self.server.storage.history(query.get('profile_id', [None])[0], limit, offset, session)
        self.reply(200, {'items': items, 'limit': limit, 'offset': offset, 'has_more': len(items) == limit})

    def profile(self, body, patch=False):
        if patch:
            from profile_patch import merge_profile
            if not isinstance(body.get('id'),str) or not re.fullmatch(ID,body['id']):
                raise ClientError('INVALID_PROFILE','配置编号不正确。')
            with self.server.client.lock:
                profile = merge_profile(self.server.storage.profile(body.get('id')), body)
                return self.profile(profile)
        profile_id, name, prefs = body.get('id'), body.get('name'), body.get('prefs', {})
        if not isinstance(profile_id, str) or not re.fullmatch(ID, profile_id) or not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ClientError('INVALID_PROFILE', '配置编号或名称不正确。')
        if not isinstance(prefs, dict) or any(k not in ('font', 'opacity', 'mode', 'source_kind') for k in prefs):
            raise ClientError('INVALID_PROFILE', '显示设置字段不正确。')
        for key, low, high in [('font', 14, 40), ('opacity', 20, 100)]:
            if key in prefs and (type(prefs[key]) is not int or not low <= prefs[key] <= high):
                raise ClientError('INVALID_PROFILE', key + ' 超出范围。')
        if prefs.get('mode', 'both') not in ('both', 'ja', 'zh') or prefs.get('source_kind', 'manual') not in ('manual', 'clipboard'):
            raise ClientError('INVALID_PROFILE', '字幕或输入模式不正确。')
        with self.server.client.lock:
            profile = self.server.storage.profile(profile_id) or {'id': profile_id, 'glossary': [], 'glossary_version': 1}
            if 'game' in body:profile['game']=validate_game(body['game'])
            profile.update(name=name.strip(), prefs=prefs if 'prefs' in body else profile.get('prefs',{}))
            self.server.storage.save_profile(profile)
            if self.server.client.session and self.server.client.session['profile_id'] == profile_id:
                self.server.client.subtitle['prefs'] = dict(profile['prefs'])
        self.reply(200, profile)

    def subtitle_events(self):
        self.close_connection=True
        self.send_response(200);self.send_header('Content-Type','text/event-stream; charset=utf-8')
        self.send_header('Cache-Control','no-store');self.send_header('Connection','close');self.end_headers()
        last=None;heartbeat=time.monotonic()
        while not self.server.finished.wait(.05):
            with self.server.client.lock:
                runtime=self.server.engine.status()
                value={'subtitle':dict(self.server.client.subtitle),'game_session':self.server.game.status(),
                    'model_preferences':dict(self.server.client.model_settings),'model_reloading':self.server.client.model_reloading,
                    'model':runtime.get('model',{}),'engine_state':runtime['state'],'wallpaper':runtime.get('wallpaper',{})}
            blob=json.dumps(value,ensure_ascii=False)
            if blob!=last:
                self.wfile.write(('event: subtitle\ndata: '+blob+'\n\n').encode('utf-8'));self.wfile.flush();last=blob;heartbeat=time.monotonic()
            elif time.monotonic()-heartbeat>5:
                self.wfile.write(b': keepalive\n\n');self.wfile.flush();heartbeat=time.monotonic()

    def ocr_frame(self):
        game=self.server.game;client=self.server.client
        scope=self.headers.get('X-Game-Session');owner=self.headers.get('X-Client-Id')
        try:epoch=int(self.headers.get('X-Epoch','0'));size=int(self.headers.get('Content-Length','0'))
        except ValueError:raise ClientError('INVALID_INPUT','帧身份或长度不正确。')
        if not 0<size<=2*1024*1024 or self.headers.get_content_type()!='image/png':raise ClientError('INVALID_INPUT','只接受最大2MiB的PNG台词帧。')
        def check():
            if not game.bound or game.owner!=owner or game.bound['game_session_id']!=scope:raise ClientError('STALE_GAME','游戏已改变。',409)
            if not client.session or client.session['epoch']!=epoch:raise ClientError('STALE_EPOCH','场景已改变。',409)
            if game.manual_paused or not game.foreground:raise ClientError('CAPTURE_PAUSED','采集已暂停。',409)
        with client.lock:check()
        png=self.rfile.read(size)
        if len(png)!=size or not png.startswith(b'\x89PNG\r\n\x1a\n'):raise ClientError('INVALID_INPUT','PNG帧不完整。')
        result=self.server.ocr.recognize(png)
        with client.lock:check()
        self.reply(200,result)

    def stream(self, req):
        self.close_connection = True
        with req.condition:
            req.readers += 1
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            offset = 0
            while True:
                with req.condition:
                    req.condition.wait_for(lambda: len(req.events) > offset or req.terminal, timeout=1)
                    batch = req.events[offset:]
                    offset += len(batch)
                    done = req.terminal
                if not batch:
                    self.wfile.write(b': heartbeat\n\n')
                for event, data in batch:
                    self.wfile.write(('event: ' + event + '\ndata: ' + json.dumps(data, ensure_ascii=False) + '\n\n').encode('utf-8'))
                self.wfile.flush()
                if done:
                    break
        finally:
            with self.server.client.lock, req.condition:
                req.readers -= 1
                if not req.readers and not req.terminal:
                    self.server.client.cancel(req.body['request_id'], 'client_disconnected')

    def asset(self, path):
        if path in ('/', '/app'):
            self.send_response(302)
            self.send_header('Location', '/app/')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if path == '/bootstrap':
            return self.reply(200, {'api': '/api/v1', 'token': self.server.token, 'ui_contract': UI_CONTRACT_VERSION,
                                    'desktop_protocol': 2, 'backend_build': 'reliability-2',
                                    'backend_root': str(ROOT.resolve()), 'database_path': self.server.storage.path,
                                    'instance_id': self.server.instance_id})
        if path in ('/', '/app/', '/app/index.html'):
            try:
                html = (FRONTEND / 'index.html').read_text(encoding='utf-8')
            except OSError as error:
                raise ClientError('UI_UNAVAILABLE', '界面文件暂时无法读取，请完成前端更新后刷新。', 503) from error
            validate_layout(html)
            html = html.replace('js/mock-api.js', '/bridge/api.js').replace('js/app.js', '/bridge/client.js')
            html = html.replace('https://unpkg.com/@phosphor-icons/web@2.1.1/src/regular/style.css', '/vendor/phosphor/style.css')
            html = re.sub(r'href="[^"]*phosphor[^"]*/(?:regular/)?style\.css"', 'href="/vendor/phosphor/style.css"', html, flags=re.IGNORECASE)
            html = html.replace('</head>', '<link rel="stylesheet" href="/bridge/connection.css"><script src="/bridge/presentation.js"></script></head>')
            html = html.replace('<title>GalTransl Client · 界面设计稿（Mock）</title>', '<title>GalTransl Client · 本地模型</title>')
            return self.reply(200, html.encode('utf-8'), 'text/html; charset=utf-8')
        if path in ('/app/subtitle.html', '/subtitle/'):
            return self.reply(200, (BRIDGE / 'subtitle.html').read_bytes(), 'text/html; charset=utf-8')
        # Explicit public asset allowlist. Never serve project data, model files or logs.
        mapping = {
            '/app/css/tokens.css': FRONTEND / 'css/tokens.css', '/app/css/app.css': FRONTEND / 'css/app.css',
            '/app/js/sse.js': FRONTEND / 'js/sse.js',
            '/app/js/backlog.js': FRONTEND / 'js/backlog.js',
            '/bridge/api.js': BRIDGE / 'api.js', '/bridge/client.js': BRIDGE / 'client.js',
            '/bridge/presentation.js': BRIDGE / 'presentation.js', '/bridge/subtitle.js': BRIDGE / 'subtitle.js',
            '/bridge/connection.css': BRIDGE / 'connection.css'}
        mapping.update({'/vendor/phosphor/style.css': ROOT / 'backend/vendor/phosphor/style.css',
            '/vendor/phosphor/Phosphor.woff2': ROOT / 'backend/vendor/phosphor/Phosphor.woff2',
            '/app/vendor/phosphor/style.css': ROOT / 'backend/vendor/phosphor/style.css',
            '/app/vendor/phosphor/Phosphor.woff2': ROOT / 'backend/vendor/phosphor/Phosphor.woff2'})
        file = mapping.get(path)
        if not file:
            raise ClientError('NOT_FOUND', '文件不存在。', 404)
        kind = {'.js': 'text/javascript', '.css': 'text/css', '.woff2': 'font/woff2'}.get(file.suffix, mimetypes.guess_type(file.name)[0])
        return self.reply(200, file.read_bytes(), kind + '; charset=utf-8')

def main():
    parser = argparse.ArgumentParser()
    add_client_port(parser)
    parser.add_argument('--database', type=Path, default=ROOT / 'data' / 'client.sqlite3')
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args()
    (ROOT / 'logs').mkdir(exist_ok=True)
    handler = RotatingFileHandler(ROOT / 'logs' / 'client.log', maxBytes=1024 * 1024, backupCount=2, encoding='utf-8')
    logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(levelname)s %(message)s')
    server = Server(args.port, args.database)
    if args.open:
        import webbrowser
        webbrowser.open(f'http://127.0.0.1:{server.server_port}/app/')
    print(f'GalTransl client: http://127.0.0.1:{server.server_port}/app/', flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.dispose()

if __name__ == '__main__':
    main()
