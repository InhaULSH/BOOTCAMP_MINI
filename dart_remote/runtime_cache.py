"""Bounded process caches and request-scoped reuse; no upstream writes."""
import copy
import time
from collections import OrderedDict
from contextvars import ContextVar
from functools import wraps
from threading import RLock

_scope=ContextVar('dart_request_cache',default=None)

def request_scope(function):
    @wraps(function)
    def wrapped(*args,**kwargs):
        if _scope.get() is not None:return function(*args,**kwargs)
        token=_scope.set({})
        try:return function(*args,**kwargs)
        finally:
            import logging
            stats=_scope.get() or {}
            logging.getLogger(__name__).debug('Request data reads: SQL=%d, reused=%d',stats.get(('sql-count',),0),stats.get(('sql-hits',),0))
            _scope.reset(token)
    return wrapped

def request_value(key,loader):
    values=_scope.get()
    if values is None:return loader()
    if key not in values:values[key]=loader()
    return copy.deepcopy(values[key])

class Cache:
    def __init__(self,max_entries=32,max_bytes=64*1024*1024):
        self.entries=OrderedDict();self.lock=RLock();self.stripes=[RLock() for _ in range(32)]
        self.max_entries=max_entries;self.max_bytes=max_bytes;self.bytes=0
    def clear(self):
        with self.lock:self.entries.clear();self.bytes=0
    def get(self,key,stamp,loader,ttl=None,size=1,accept=lambda value:True):
        # Same-key misses are coalesced. Independent keys may load concurrently.
        with self.stripes[hash(key)%len(self.stripes)]:
            now=time.monotonic()
            with self.lock:
                item=self.entries.get(key)
                if item and item[0]==stamp and (item[1] is None or now<item[1]):
                    self.entries.move_to_end(key);return copy.deepcopy(item[2])
            value=loader()  # Never cache failures or unsuitable results.
            weight=size(value) if callable(size) else size
            if accept(value) and weight<=self.max_bytes:
                with self.lock:
                    old=self.entries.pop(key,None)
                    if old:self.bytes-=old[3]
                    self.entries[key]=(stamp,None if ttl is None else time.monotonic()+ttl,copy.deepcopy(value),weight)
                    self.bytes+=weight
                    while len(self.entries)>self.max_entries or self.bytes>self.max_bytes:
                        _,old=self.entries.popitem(last=False);self.bytes-=old[3]
            return value

_project_cache=Cache(max_entries=16)
_graph_cache=Cache(max_entries=128,max_bytes=16*1024*1024)

def cached_graph(loader,sector,company,years):
    """Reuse chart calculations independently of market/keyword presentation."""
    import os,json,hashlib
    from . import artifacts
    ttl=max(0,min(300,float(os.getenv('UI_CACHE_SECONDS','30'))))
    if not ttl or os.getenv('SERVICE_GCS_BUCKET'):return loader()
    path=artifacts.ROOT/artifacts._name(sector.id,'report','current')
    try:
        stat=path.stat();stamp=(stat.st_mtime_ns,stat.st_ctime_ns,stat.st_size,stat.st_ino)
    except FileNotFoundError:return loader()
    target=hashlib.sha256(repr(sorted((k,v) for k,v in os.environ.items() if k.startswith('MYSQL_'))).encode()).hexdigest()
    key=(str(artifacts.ROOT),target,repr(sector),json.dumps(company,sort_keys=True,ensure_ascii=False),tuple(years),'graph-v4-capex-proof')
    return _graph_cache.get(key,stamp,loader,ttl=ttl,size=lambda value:len(json.dumps(value,ensure_ascii=False).encode()))

def cached_project(function,selected,catalogue,company=None):
    import os,json
    from . import artifacts
    # GCS generations are checked by the artifact reader; do not hide them behind a local signature.
    ttl=max(0,min(300,float(os.getenv('UI_CACHE_SECONDS','30'))))
    load=lambda:function(selected,company) if company is not None else function(selected)
    if ttl==0 or os.getenv('SERVICE_GCS_BUCKET'):return load()
    stamps=[]
    for sector in catalogue:
        for kind,artifact_key in (('report','current'),('report','prompt-'+artifacts.report_version()),('market','current')):
            path=artifacts.ROOT/artifacts._name(sector.id,kind,artifact_key)
            try:
                stat=path.stat();stamp=(stat.st_mtime_ns,stat.st_ctime_ns,stat.st_size,stat.st_ino)
            except FileNotFoundError:stamp=None
            stamps.append((str(path),stamp))
    stamp=(repr(catalogue),tuple(stamps))
    key=(function.__module__,selected,company,str(artifacts.ROOT),artifacts.report_version())
    # Retried on next request if an unavailable sector was returned. Never cache an exception.
    return _project_cache.get(key,stamp,load,ttl=ttl,
        size=lambda value:len(json.dumps(value,ensure_ascii=False).encode('utf-8')),
        accept=lambda value:not any(s.get('status')=='unavailable' for s in value.get('sectors',[])))


_catalog_cache=Cache(max_entries=8,max_bytes=2*1024*1024)

def scoped_catalog(key,stamp,loader):
    """Only web request scopes reuse catalogues across requests; CLI stays fresh."""
    import os,json
    if _scope.get() is None:return loader()
    ttl=max(0,min(300,float(os.getenv('CATALOG_CACHE_SECONDS','30'))))
    if not ttl:return loader()
    return _catalog_cache.get(key,stamp,loader,ttl=ttl,
        size=lambda value:len(repr(value).encode('utf-8')))

def sql_value(key,loader):
    """Reuse identical small SQL results within one request, never across requests."""
    values=_scope.get()
    if values is None:return loader()
    slot=('sql',key)
    if slot in values:
        values[('sql-hits',)]=values.get(('sql-hits',),0)+1
        return copy.deepcopy(values[slot])
    values[('sql-count',)]=values.get(('sql-count',),0)+1
    result=loader()
    # Exclude vector/XML payloads and bound the request's additional memory.
    import json
    try:size=len(json.dumps(result,ensure_ascii=False).encode('utf-8'))
    except (TypeError,ValueError):return result
    used=values.get(('sql-bytes',),0)
    if size<=1024*1024 and used+size<=4*1024*1024:
        values[slot]=copy.deepcopy(result);values[('sql-bytes',)]=used+size
    return result
