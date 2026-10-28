"""Optional Wallpaper Engine stop/play lease. Commands never change wallpaper settings."""
import ctypes,json,logging,os,re,subprocess,tempfile,threading,time,uuid
from ctypes import wintypes as w
from pathlib import Path
from data_tools import DatabaseLease,DataInUseError

MAIN={'wallpaper32.exe','wallpaper64.exe'}
RENDERERS=MAIN|{'webwallpaper32.exe','webwallpaper64.exe'}

class WindowsWallpaper:
    supported=os.name=='nt'
    def _processes(self):
        if not self.supported:return []
        k=ctypes.WinDLL('kernel32',use_last_error=True)
        class Entry(ctypes.Structure):
            _fields_=[('size',w.DWORD),('usage',w.DWORD),('pid',w.DWORD),('heap',ctypes.c_size_t),('module',w.DWORD),
                ('threads',w.DWORD),('parent',w.DWORD),('priority',w.LONG),('flags',w.DWORD),('exe',w.WCHAR*260)]
        k.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD];k.CreateToolhelp32Snapshot.restype=w.HANDLE
        k.Process32FirstW.argtypes=k.Process32NextW.argtypes=[w.HANDLE,ctypes.POINTER(Entry)]
        k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
        k.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD)]
        k.GetProcessTimes.argtypes=[w.HANDLE,*([ctypes.POINTER(w.FILETIME)]*4)]
        k.CloseHandle.argtypes=[w.HANDLE]
        handle=k.CreateToolhelp32Snapshot(2,0)
        if handle in (None,ctypes.c_void_p(-1).value):raise OSError('Process snapshot unavailable')
        entries=[];entry=Entry();entry.size=ctypes.sizeof(entry)
        try:
            present=k.Process32FirstW(handle,ctypes.byref(entry))
            while present:
                if entry.exe.lower() in RENDERERS:
                    process=k.OpenProcess(0x1000,False,entry.pid)
                    if process:
                        try:
                            buffer=ctypes.create_unicode_buffer(32768);length=w.DWORD(len(buffer))
                            times=[w.FILETIME() for _ in range(4)]
                            if k.QueryFullProcessImageNameW(process,0,buffer,ctypes.byref(length)) and k.GetProcessTimes(process,*[ctypes.byref(t) for t in times]):
                                entries.append({'pid':int(entry.pid),'executable':buffer.value,
                                    'created':str((times[0].dwHighDateTime<<32)|times[0].dwLowDateTime)})
                        finally:k.CloseHandle(process)
                present=k.Process32NextW(handle,ctypes.byref(entry))
        finally:k.CloseHandle(handle)
        return entries
    def _memory(self):
        pdh=ctypes.WinDLL('pdh');query=w.HANDLE();counter=w.HANDLE()
        class Number(ctypes.Union):_fields_=[('large',ctypes.c_longlong),('double',ctypes.c_double),('long',w.LONG)]
        class Value(ctypes.Structure):_fields_=[('status',w.DWORD),('number',Number)]
        class Item(ctypes.Structure):_fields_=[('name',w.LPWSTR),('value',Value)]
        pdh.PdhOpenQueryW.argtypes=[w.LPCWSTR,ctypes.c_size_t,ctypes.POINTER(w.HANDLE)]
        pdh.PdhAddEnglishCounterW.argtypes=[w.HANDLE,w.LPCWSTR,ctypes.c_size_t,ctypes.POINTER(w.HANDLE)]
        pdh.PdhCollectQueryData.argtypes=[w.HANDLE];pdh.PdhCloseQuery.argtypes=[w.HANDLE]
        pdh.PdhGetFormattedCounterArrayW.argtypes=[w.HANDLE,w.DWORD,ctypes.POINTER(w.DWORD),ctypes.POINTER(w.DWORD),ctypes.c_void_p]
        if pdh.PdhOpenQueryW(None,0,ctypes.byref(query)):raise OSError('GPU process counter unavailable')
        try:
            if pdh.PdhAddEnglishCounterW(query,r'\GPU Process Memory(*)\Dedicated Usage',0,ctypes.byref(counter)) or pdh.PdhCollectQueryData(query):
                raise OSError('GPU process counter unavailable')
            size=w.DWORD();count=w.DWORD()
            code=pdh.PdhGetFormattedCounterArrayW(counter,0x400,ctypes.byref(size),ctypes.byref(count),None)&0xffffffff
            if code!=0x800007d2 or not size.value:raise OSError('GPU process counter has no data')
            buffer=ctypes.create_string_buffer(size.value)
            if pdh.PdhGetFormattedCounterArrayW(counter,0x400,ctypes.byref(size),ctypes.byref(count),buffer):raise OSError('GPU process counter read failed')
            items=ctypes.cast(buffer,ctypes.POINTER(Item));memory={}
            for i in range(count.value):
                item=items[i];match=re.search(r'(?:^|_)pid_(\d+)(?:_|$)',item.name or '')
                if match and item.value.status in (0,1):
                    pid=int(match[1]);memory[pid]=memory.get(pid,0)+max(0,item.value.number.large)/(1024*1024)
            return memory
        finally:pdh.PdhCloseQuery(query)
    def inspect(self):
        entries=self._processes();main=[p for p in entries if Path(p['executable']).name.lower() in MAIN]
        if len(main)!=1:return None
        snapshot=main[0];folder=Path(snapshot['executable']).parent
        if not (folder/'config.json').is_file():return None
        memory=self._memory()
        snapshot['gpu_mib']=sum(memory.get(p['pid'],0) for p in entries if Path(p['executable']).parent==folder)
        return snapshot
    def matches(self,snapshot):
        return any(all(p.get(k)==snapshot.get(k) for k in ('pid','created','executable')) for p in self._processes())
    def command(self,snapshot,operation):
        if operation not in ('stop','play') or Path(snapshot['executable']).name.lower() not in MAIN:raise ValueError('Unsupported wallpaper command')
        if not self.matches(snapshot):raise OSError('Wallpaper process changed')
        subprocess.run([snapshot['executable'],'-control',operation],cwd=Path(snapshot['executable']).parent,
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=5,check=True)

class WallpaperController:
    def __init__(self,adapter=None,journal=None):
        self.adapter=adapter or WindowsWallpaper()
        # Shared per-user location prevents different portable clients controlling the same wallpaper.
        base=Path(os.environ.get('LOCALAPPDATA') or tempfile.gettempdir())/'GalTranslClient'
        self.journal=Path(journal) if journal else base/'wallpaper-relief.json'
        self.lock=threading.RLock();self.lease=None;self.held=None;self.enabled=True
        self.closed=False
        self.state='idle';self.message='占用显存过大的壁纸可能暂时关闭，翻译结束后自动恢复。'
        self.retry_at=0;self.retries=0
    def status(self):
        with self.lock:return {'available':self.adapter.supported,'enabled':self.enabled,'state':self.state,'held':self.held is not None,
            'message':self.message,'wallpaper_gpu_mib':round(self.held['gpu_mib']) if self.held else None}
    def configure(self,enabled):
        if type(enabled) is not bool:raise ValueError('Wallpaper policy must be boolean')
        with self.lock:self.enabled=enabled
    def _notice(self,state,message):self.state=state;self.message=message
    def _unlock(self):
        if self.lease:self.lease.close();self.lease=None
    def _write(self,snapshot):
        self.journal.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.journal.with_name(self.journal.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            with temporary.open('x',encoding='utf-8') as stream:
                json.dump({'version':1,'snapshot':snapshot},stream);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,self.journal)
        finally:temporary.unlink(missing_ok=True)
    @staticmethod
    def _valid(record):
        s=record.get('snapshot') if isinstance(record,dict) and record.get('version')==1 else None
        return isinstance(s,dict) and type(s.get('pid')) is int and s['pid']>0 and isinstance(s.get('created'),str) and s['created'].isdigit() \
            and isinstance(s.get('executable'),str) and Path(s['executable']).name.lower() in MAIN \
            and type(s.get('gpu_mib')) in (int,float) and 0<=s['gpu_mib']<1048576
    def recover(self):
        with self.lock:
            if self.closed or self.held or not self.journal.exists():return
            try:
                self.lease=DatabaseLease(self.journal)
                record=json.loads(self.journal.read_text(encoding='utf-8'))
                if not self._valid(record):raise ValueError('Invalid wallpaper recovery record')
                self.held=record['snapshot'];self.restore()
            except DataInUseError:self._notice('busy','其他客户端正在管理壁纸，当前客户端不重复控制。')
            except Exception:
                self._notice('restore_failed','壁纸恢复记录暂时不可用，未执行控制；请检查客户端日志。');logging.exception('Wallpaper journal recovery failed')
                if self.held is None:self._unlock()
    def acquire(self,pressure,cancelled=lambda:False):
        with self.lock:
            if self.closed or cancelled():return False
            if self.held:return self.state=='stopped'
            if not self.enabled or not pressure or not self.adapter.supported:return False
            self.recover()
            if self.held or self.journal.exists():return False
            try:
                snapshot=self.adapter.inspect()
                if cancelled():return False
                if snapshot is None:
                    self._notice('not_running','没有检测到运行中的 Wallpaper Engine，壁纸保持现状。');return False
                if snapshot['gpu_mib']<1024:
                    self._notice('light','壁纸显存占用较低，保持运行。');return False
                self.lease=DatabaseLease(self.journal)
                self._write(snapshot) # Persist intent before an external command can take effect.
                self.held=snapshot;self.retries=0
                if cancelled():
                    self.journal.unlink(missing_ok=True);self.held=None;self._unlock();return False
                self.adapter.command(snapshot,'stop')
                self._notice('stopped','高占用壁纸已临时停止，翻译结束后自动恢复。');return True
            except DataInUseError:self._notice('busy','其他客户端正在管理壁纸，当前客户端不重复控制。')
            except Exception:
                logging.exception('Wallpaper stop unavailable')
                if self.held:self.restore()
                if self.held is None:self._notice('unavailable','自动壁纸控制暂不可用，模型按现有预算运行。')
            if self.held is None:self._unlock()
            return False
    def restore(self):
        with self.lock:
            if self.closed or not self.held:return
            try:
                if self.adapter.matches(self.held):self.adapter.command(self.held,'play')
                self.journal.unlink(missing_ok=True);self.held=None;self._unlock();self.retries=0
                self._notice('restored','本次临时停止的壁纸已恢复；已退出的壁纸应用不会被重新启动。')
            except Exception:
                self.retries+=1;self.retry_at=time.monotonic()+5
                self._notice('restore_failed','壁纸自动恢复暂时失败，客户端将有界重试；恢复记录已保留。')
                logging.exception('Wallpaper restore failed')
    def tick(self):
        with self.lock:
            if self.state=='restore_failed' and self.held and self.retries<3 and time.monotonic()>=self.retry_at:self.restore()
    def close(self):
        with self.lock:
            if self.closed:return
            self.restore();self._unlock() # Failed restore remains durable for next launch.
            self.held=None;self.closed=True
