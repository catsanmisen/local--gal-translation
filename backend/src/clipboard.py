"""Opt-in Windows Unicode clipboard input; no writes, sequence-based dedup."""
import ctypes
from ctypes import wintypes as w
import os
import logging
import threading
import time
import uuid
from core import now
from engine import ClientError


class Clipboard:
    def __init__(self, client):
        self.client = client
        self.stop = threading.Event()
        self.last = None
        if os.name == 'nt':
            self.user = ctypes.WinDLL('user32', use_last_error=True)
            self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            for name, args, ret in [('GetClipboardSequenceNumber', [], w.DWORD), ('OpenClipboard', [w.HWND], w.BOOL),
                ('CloseClipboard', [], w.BOOL), ('GetClipboardData', [w.UINT], w.HANDLE), ('IsClipboardFormatAvailable', [w.UINT], w.BOOL)]:
                fn = getattr(self.user, name)
                fn.argtypes, fn.restype = args, ret
            self.kernel.GlobalLock.argtypes, self.kernel.GlobalLock.restype = [w.HANDLE], ctypes.c_void_p
            self.kernel.GlobalUnlock.argtypes, self.kernel.GlobalUnlock.restype = [w.HANDLE], w.BOOL
            self.kernel.GlobalSize.argtypes, self.kernel.GlobalSize.restype = [w.HANDLE], ctypes.c_size_t
        self.thread = threading.Thread(target=self._run, daemon=True, name='clipboard-input')
        self.thread.start()

    def enable(self, enabled):
        if os.name != 'nt':
            raise ClientError('UNSUPPORTED', '剪贴板监听只支持 Windows。', 409)
        with self.client.lock:
            if enabled and not self.client.session:
                raise ClientError('SESSION_NOT_FOUND', '请先建立游戏会话。', 409)
            # Start from the current sequence: never ingest clipboard contents from before opt-in.
            self.last = self.user.GetClipboardSequenceNumber()
            self.client.clipboard_on = enabled
            self.client.set_clipboard_error(None)
        return {'enabled': enabled}

    def read(self):
        if not self.user.IsClipboardFormatAvailable(13):
            return None
        if not self.user.OpenClipboard(None):
            raise OSError('剪贴板正被其他程序占用')
        try:
            handle = self.user.GetClipboardData(13)
            if not handle or self.kernel.GlobalSize(handle) > 1024 * 1024:
                return None
            ptr = self.kernel.GlobalLock(handle)
            if not ptr:
                raise OSError('无法读取剪贴板')
            try:
                size = self.kernel.GlobalSize(handle) // 2
                return ctypes.wstring_at(ptr, size).split('\0', 1)[0]
            finally:
                self.kernel.GlobalUnlock(handle)
        finally:
            self.user.CloseClipboard()

    def _run(self):
        changed = None
        changed_at = 0
        retry_at, retry_delay = 0, 0.25
        pending_scope = None
        while not self.stop.wait(0.1):
            with self.client.lock:
                if os.name != 'nt' or not self.client.clipboard_on:
                    changed = None
                    retry_at, retry_delay = 0, 0.25
                    continue
                sequence = self.user.GetClipboardSequenceNumber()
                scope = (self.client.session['session_id'], self.client.session['epoch']) if self.client.session else None
                if sequence != self.last:
                    self.last, changed, changed_at = sequence, sequence, time.monotonic()
                    pending_scope = scope
                    retry_at, retry_delay = 0, 0.25
                if changed is not None and scope != pending_scope:
                    # A scene reset invalidates text observed before it, including events waiting for GPU recovery.
                    changed = None
                    continue
                if changed is None or time.monotonic() - changed_at < 0.25:
                    continue
                if time.monotonic() < retry_at:
                    continue
                if not self.client.session or self.client.engine.status()['state'] != 'ready':
                    continue
                try:
                    text = self.read()
                    if self.user.GetClipboardSequenceNumber() != changed:
                        continue  # Clipboard changed between sequence observation and OpenClipboard.
                    self.client.set_clipboard_error(None)
                    retry_at, retry_delay = 0, 0.25
                    if not text or not text.strip():
                        changed = None
                        continue
                    if len(text) > 2000:
                        raise ClientError('INPUT_TOO_LONG', '剪贴板原文超过 2000 字符，请拆分。')
                    session = self.client.session
                    self.client.submit({'request_id': 'clip-' + uuid.uuid4().hex, 'session_id': session['session_id'],
                        'epoch': session['epoch'], 'sequence': session['sequence'] + 1, 'source_text': text,
                        'source_kind': 'clipboard', 'speaker': None, 'captured_at': now(), 'complete': True, 'stream': True})
                    self.client.set_clipboard_error(None)
                    changed = None
                except ClientError as error:
                    self.client.set_clipboard_error(error.json())
                    changed = None
                except OSError:
                    self.client.set_clipboard_error({'code': 'CLIPBOARD_BUSY', 'message': '剪贴板被占用，正在重试。', 'retryable': True}, 'notice')
                    retry_at = time.monotonic() + retry_delay
                    retry_delay = min(retry_delay * 2, 2)
                except Exception:
                    logging.exception('Clipboard input processing failed')
                    self.client.set_clipboard_error({'code': 'CLIPBOARD_ERROR', 'message': '剪贴板处理失败，本条未提交；请检查后台日志后重试。', 'retryable': True})
                    changed = None

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)
