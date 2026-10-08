"""Bounded exact-request token counts; no estimates or API credentials stored."""
import hashlib
import json
import threading
from collections import OrderedDict

_lock=threading.Lock()
_counts=OrderedDict()


def cached_count(payload, model, fetch):
    key=hashlib.sha256(json.dumps([model,payload],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    with _lock:
        if key in _counts:
            _counts.move_to_end(key)
            return _counts[key]
    count=fetch()
    with _lock:
        _counts[key]=count
        while len(_counts)>256:_counts.popitem(last=False)
    return count
