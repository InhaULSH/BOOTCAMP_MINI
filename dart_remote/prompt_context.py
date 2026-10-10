"""Per-request prompt selection without changing process-wide environment."""
from contextlib import contextmanager
from contextvars import ContextVar

_version=ContextVar('keyword_retry_prompt_version',default=None)

def active_version():return _version.get()

@contextmanager
def using_version(version):
    if version not in ('new','new2','old'):raise ValueError('지원하지 않는 프롬프트 버전입니다.')
    token=_version.set(version)
    try:yield
    finally:_version.reset(token)
