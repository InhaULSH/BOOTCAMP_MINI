"""Bounded public-file reuse; callers still enforce their asset allowlist."""
import gzip
import hashlib
from .runtime_cache import Cache

_assets=Cache(max_entries=32,max_bytes=16*1024*1024)

def accepts_gzip(header):
    for item in header.lower().split(','):
        parts=item.strip().split(';')
        if parts[0]=='gzip':
            try:return all(float(p.strip()[2:])>0 for p in parts[1:] if p.strip().startswith('q='))
            except ValueError:return False
    return False

def public_asset(path,compress=False):
    def stamp():
        s=path.stat();return (s.st_mtime_ns,s.st_ctime_ns,s.st_size,s.st_ino)
    for _ in range(3):
        before=stamp()
        def load():
            raw=path.read_bytes()
            body=gzip.compress(raw,compresslevel=3,mtime=0) if compress and len(raw)>=1024 else raw
            return body,'"'+hashlib.sha256(body).hexdigest()+'"',body is not raw
        value=_assets.get((str(path),compress),before,load,size=lambda v:len(v[0]))
        if before==stamp():return value
    raise RuntimeError('Public file changed during read')
