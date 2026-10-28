"""Read-only Windows process CPU and working-set sampling for acceptance logs."""
import ctypes
from ctypes import wintypes as w
import os
import time


class ProcessMetrics:
    def __init__(self):self.previous={}
    def sample(self,pid):
        if os.name!='nt' or not pid:return None
        k=ctypes.WinDLL('kernel32',use_last_error=True);p=ctypes.WinDLL('psapi',use_last_error=True)
        class Memory(ctypes.Structure):
            _fields_=[('cb',w.DWORD),('faults',w.DWORD)]+[(n,ctypes.c_size_t) for n in
                ('peak','working','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile','private')]
        k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
        k.CloseHandle.argtypes=[w.HANDLE];k.CloseHandle.restype=w.BOOL
        k.GetProcessTimes.argtypes=[w.HANDLE,*[ctypes.POINTER(w.FILETIME)]*4];k.GetProcessTimes.restype=w.BOOL
        p.GetProcessMemoryInfo.argtypes=[w.HANDLE,ctypes.POINTER(Memory),w.DWORD];p.GetProcessMemoryInfo.restype=w.BOOL
        handle=k.OpenProcess(0x410,False,pid)
        if not handle:return {'pid':pid,'unavailable':True}
        try:
            m=Memory(cb=ctypes.sizeof(Memory));created=w.FILETIME();exited=w.FILETIME();kernel=w.FILETIME();user=w.FILETIME()
            if not p.GetProcessMemoryInfo(handle,ctypes.byref(m),m.cb) or not k.GetProcessTimes(handle,ctypes.byref(created),ctypes.byref(exited),ctypes.byref(kernel),ctypes.byref(user)):
                return {'pid':pid,'unavailable':True}
            number=lambda f:(f.dwHighDateTime<<32)|f.dwLowDateTime
            cpu=(number(kernel)+number(user))/10_000_000;at=time.monotonic();identity=(pid,number(created))
            before=self.previous.get(identity);self.previous[identity]=(at,cpu)
            utilization=(cpu-before[1])/(at-before[0])*100 if before and at>before[0] else None
            return {'pid':pid,'working_set_mib':round(m.working/1048576,2),'private_mib':round(m.private/1048576,2),
                'cpu_core_percent':round(utilization,2) if utilization is not None else None,
                'cpu_total_percent':round(utilization/max(1,os.cpu_count()),2) if utilization is not None else None}
        finally:k.CloseHandle(handle)
