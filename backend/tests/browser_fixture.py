"""UI-only fixture with simulated diagnostics; never reads clipboard or starts a model."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from server import Server
from engine import ClientError,utcnow

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=18069)
    args=parser.parse_args()
    server=Server(args.port,':memory:')
    server.storage.save_profile({'id':'default','name':'连接层回归（模拟错误）','glossary':[],
        'prefs':{'font':26,'opacity':20,'mode':'both','source_kind':'clipboard'}})
    server.client.create_session('default')
    server.client.subtitle.update(ja='原文保持不变。',zh='不得显示为完整译文的片段',state='error',reason='模拟截断')
    server.client.set_clipboard_error({'code':'CLIPBOARD_BUSY','message':'剪贴板被占用，正在重试。','retryable':True},'notice')
    server.engine.stop_diagnostic=ClientError('CANCEL_TIMEOUT','模拟回收超时：模型已停止，请重新启动。',503,occurred_at=utcnow()).json()
    print(f'UI fixture (no model): http://127.0.0.1:{args.port}/app/',flush=True)
    try:server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:server.dispose()
if __name__=='__main__':main()
