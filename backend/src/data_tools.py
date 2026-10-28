"""SQLite snapshots and stopped-client restore; never copies incomplete WAL files."""
import argparse
from contextlib import contextmanager
import ctypes
import os
from pathlib import Path
import sqlite3
import sys
import uuid

class DataInUseError(RuntimeError):pass

class DatabaseLease:
    def __init__(self,path):
        self.file=None
        lock=Path(str(Path(path).resolve())+'.lock');lock.parent.mkdir(parents=True,exist_ok=True)
        stream=lock.open('a+b')
        try:
            if stream.tell()==0:stream.write(b'0');stream.flush()
            stream.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.file=stream
        except (OSError,IOError) as error:
            stream.close();raise DataInUseError('该数据库已有客户端使用；请关闭该客户端后重试。') from error
    def close(self):
        if self.file is not None:self.file.close();self.file=None
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

def readonly(path):
    path=Path(path).resolve()
    if not path.is_file():raise FileNotFoundError(path)
    return sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)

def validate(connection):
    if connection.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('数据库完整性检查失败。')
    tables={r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'profiles','history','settings'}<=tables:raise ValueError('文件不是客户端数据库。')

def backup_database(source,destination):
    source=Path(source).resolve();destination=Path(destination).resolve()
    if source==destination:raise ValueError('备份不能覆盖原数据库。')
    destination.parent.mkdir(parents=True,exist_ok=True)
    # Reserve a new file exclusively; failed snapshots never replace older backups.
    with destination.open('xb'):pass
    try:
        original=readonly(source);output=None
        try:
            output=sqlite3.connect(destination)
            validate(original);original.backup(output);validate(output)
        finally:
            if output is not None:output.close()
            original.close()
    except Exception:
        destination.unlink(missing_ok=True);raise
    return destination

@contextmanager
def exclusive_target(path):
    # Detect even legacy clients which do not hold DatabaseLease. Share DELETE
    # permits atomic replace while denying SQLite readers/writers on Windows.
    if os.name=='nt' and Path(path).exists():
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
        kernel.CreateFileW.restype=ctypes.c_void_p;kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.CreateFileW(str(path),0x80000000,4,None,3,128,None)
        if handle==ctypes.c_void_p(-1).value:raise DataInUseError('数据库仍被其他进程打开，请先停止客户端。')
        try:yield
        finally:kernel.CloseHandle(handle)
    else:yield

def restore_database(snapshot,target):
    snapshot=Path(snapshot).resolve();target=Path(target).resolve()
    if snapshot==target:raise ValueError('恢复来源不能是目标本身。')
    target.parent.mkdir(parents=True,exist_ok=True)
    with DatabaseLease(target):
        # Refuse stale journals rather than merging them into a restored file.
        if any(Path(str(target)+suffix).exists() for suffix in ('-wal','-shm','-journal')):
            raise DataInUseError('目标存在活动或未清理日志，请先正常关闭客户端。')
        temporary=target.with_name(target.name+'.restore-'+uuid.uuid4().hex)
        try:
            backup_database(snapshot,temporary)
            # MoveFileEx cannot replace a file while our own read handle is
            # open. Keep DatabaseLease throughout, release the legacy-open
            # probe, then use atomic replace (SQLite Windows handles also deny
            # rename if an older client races to open in this short interval).
            with exclusive_target(target):pass
            os.replace(temporary,target)
        finally:temporary.unlink(missing_ok=True)
    return target

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('backup','restore'))
    parser.add_argument('source',type=Path);parser.add_argument('destination',type=Path);args=parser.parse_args()
    result=backup_database(args.source,args.destination) if args.action=='backup' else restore_database(args.source,args.destination)
    print('完成：'+str(result))
if __name__=='__main__':main()
