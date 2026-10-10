"""Resolve unchanged filing assets across financial releases, without DB writes.

Only validated releases with BOTH the same vector SQLite and FAISS hashes
may share vectors/source XML. Financial facts always use the current release.
"""
import re
from . import db

def compatible_pairs(version):
    current=(version['data_version'],version['index_version'])
    hashes=[version.get(k) for k in ('vector_sqlite_sha256','faiss_sha256')]
    if not all(isinstance(h,str) and re.fullmatch(r'[0-9a-fA-F]{64}',h) for h in hashes):
        return [list(current)]  # Missing hashes never authorize an old release.
    rows=db.rows('''SELECT data_version,index_version FROM data_versions
        WHERE validated=1 AND vector_sqlite_sha256=:s AND faiss_sha256=:f
        ORDER BY data_version,index_version''',dict(s=hashes[0],f=hashes[1]))
    return [list(p) for p in sorted({current}|{(r['data_version'],r['index_version']) for r in rows})]

def source_versions(data_version):
    rows=db.rows('SELECT * FROM data_versions WHERE data_version=:v AND validated=1',dict(v=data_version))
    if len(rows)!=1:raise ValueError('원본 조회 기준 버전이 검증되지 않았습니다.')
    return sorted({p[0] for p in compatible_pairs(rows[0])})

def version_filter(column,versions,params):
    keys=[]
    for i,version in enumerate(versions):
        name='asset_v'+str(i);params[name]=version;keys.append(':'+name)
    return column+' IN ('+','.join(keys)+')'
