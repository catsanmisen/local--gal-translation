"""The owned model health endpoint must remain local under a system proxy."""
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'galtransl4'))
import gal_service


class LoopbackHealth(unittest.TestCase):
    def test_health_bypasses_proxy_for_the_owned_loopback_server(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200);self.end_headers();self.wfile.write(json.dumps({'status':'ok'}).encode())
            def log_message(self,*args):pass
        server=HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with patch('urllib.request.getproxies',return_value={'http':'http://127.0.0.1:1'}), \
                 patch('urllib.request.proxy_bypass',return_value=False),patch('urllib.request._opener',None):
                self.assertTrue(gal_service.health(server.server_port))
        finally:server.shutdown();thread.join();server.server_close()


if __name__=='__main__':unittest.main()
