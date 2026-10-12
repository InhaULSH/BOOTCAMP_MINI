"""Successful full checks are shared only within one analysis invocation."""
from contextvars import ContextVar
from functools import wraps
from threading import RLock

_state=ContextVar('dart_analysis_validation',default=None)

def active():return _state.get() is not None

def scope(function):
    @wraps(function)
    def wrapped(*args,**kwargs):
        if active():return function(*args,**kwargs)
        token=_state.set(dict(lock=RLock(),checks={}))
        try:return function(*args,**kwargs)
        finally:_state.reset(token)
    return wrapped

def once(name,signature,check):
    state=_state.get()
    if state is None:return check()
    with state['lock']:
        old=state['checks'].get(name)
        if old is not None and old[0]==signature:return old[1]
        result=check()  # Failures never approve a signature.
        state['checks'][name]=(signature,result)
        return result

def submit(executor,function,*args):
    # Share this analysis's state, not a web request's SQL cache.
    state=_state.get()
    def run():
        token=_state.set(state)
        try:return function(*args)
        finally:_state.reset(token)
    return executor.submit(run)
