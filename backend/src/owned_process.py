"""Create a suspended Windows child, assign kill-on-close Job, then resume."""
import ctypes
from ctypes import wintypes as w
import os
import subprocess
import time


class OwnedProcess:
    def __init__(self, args, cwd, logfile, env=None):
        self.returncode, self._handles = None, []
        if os.name != 'nt':
            self.child = subprocess.Popen(args, cwd=cwd, stdout=logfile, stderr=subprocess.STDOUT, env=env)
            self.pid = self.child.pid
            return
        import msvcrt
        self.kernel = k = ctypes.WinDLL('kernel32', use_last_error=True)
        class Startup(ctypes.Structure):
            _fields_ = [('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR), ('title', w.LPWSTR),
                *[(n, w.DWORD) for n in ('x', 'y', 'xs', 'ys', 'xc', 'yc', 'fill', 'flags')],
                ('show', w.WORD), ('reserved2size', w.WORD), ('reserved2', ctypes.c_void_p),
                ('stdin', w.HANDLE), ('stdout', w.HANDLE), ('stderr', w.HANDLE)]
        class ProcessInfo(ctypes.Structure):
            _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]
        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong), ('flags', w.DWORD),
                ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t), ('active', w.DWORD),
                ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ('read', 'write', 'other', 'read_bytes', 'write_bytes', 'other_bytes')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', IO), *[(n, ctypes.c_size_t) for n in ('process_mem', 'job_mem', 'peak_process', 'peak_job')]]
        specs = {
            'CreateJobObjectW': ([ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
            'SetInformationJobObject': ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
            'CreateProcessW': ([w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, w.BOOL, w.DWORD,
                ctypes.c_void_p, w.LPCWSTR, ctypes.POINTER(Startup), ctypes.POINTER(ProcessInfo)], w.BOOL),
            'AssignProcessToJobObject': ([w.HANDLE, w.HANDLE], w.BOOL), 'ResumeThread': ([w.HANDLE], w.DWORD),
            'GetExitCodeProcess': ([w.HANDLE, ctypes.POINTER(w.DWORD)], w.BOOL),
            'WaitForSingleObject': ([w.HANDLE, w.DWORD], w.DWORD), 'TerminateJobObject': ([w.HANDLE, w.UINT], w.BOOL),
            'TerminateProcess': ([w.HANDLE, w.UINT], w.BOOL), 'CloseHandle': ([w.HANDLE], w.BOOL)}
        for name, (argtypes, restype) in specs.items():
            getattr(k, name).argtypes, getattr(k, name).restype = argtypes, restype
        self.job = k.CreateJobObjectW(None, None)
        if not self.job:
            raise ctypes.WinError(ctypes.get_last_error())
        self._handles.append(self.job)
        limit = Extended()
        limit.basic.flags = 0x2000
        if not k.SetInformationJobObject(self.job, 9, ctypes.byref(limit), ctypes.sizeof(limit)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())
        info = ProcessInfo()
        environment = ctypes.create_unicode_buffer('\0'.join(f'{key}={value}' for key,value in sorted((env or os.environ).items())) + '\0\0')
        with open(os.devnull, 'rb') as null:
            out_h, in_h = msvcrt.get_osfhandle(logfile.fileno()), msvcrt.get_osfhandle(null.fileno())
            os.set_handle_inheritable(out_h, True)
            os.set_handle_inheritable(in_h, True)
            startup = Startup(cb=ctypes.sizeof(Startup), flags=0x100, stdin=in_h, stdout=out_h, stderr=out_h)
            try:
                ok = k.CreateProcessW(args[0], ctypes.create_unicode_buffer(subprocess.list2cmdline(args)),
                    None, None, True, 0x08000404, ctypes.cast(environment, ctypes.c_void_p), str(cwd), ctypes.byref(startup), ctypes.byref(info))
            finally:
                os.set_handle_inheritable(out_h, False)
                os.set_handle_inheritable(in_h, False)
        if not ok:
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())
        self.process, self.pid = info.process, info.pid
        self._handles.append(self.process)
        try:
            if not k.AssignProcessToJobObject(self.job, self.process) or k.ResumeThread(info.thread) == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
        except Exception:
            k.TerminateProcess(self.process, 1)
            self.close()
            raise
        finally:
            k.CloseHandle(info.thread)

    def poll(self):
        if hasattr(self, 'child'):
            self.returncode = self.child.poll()
        elif self.returncode is None and self.kernel.WaitForSingleObject(self.process, 0) == 0:
            code = w.DWORD()
            self.kernel.GetExitCodeProcess(self.process, ctypes.byref(code))
            self.returncode = code.value
        return self.returncode

    def wait(self, timeout=10):
        deadline = time.monotonic() + timeout
        while self.poll() is None:
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired('owned model process', timeout)
            time.sleep(0.05)
        return self.returncode

    def terminate(self):
        if hasattr(self, 'child'):
            self.child.terminate()
        else:
            self.kernel.TerminateJobObject(self.job, 1)

    def close(self):
        if hasattr(self, 'kernel'):
            for handle in self._handles:
                self.kernel.CloseHandle(handle)
            self._handles.clear()
