"""Route current MySQL BGE search; retain explicit keyword compatibility."""
import os
import re
import numpy as np

def terms(query):
    words=list(dict.fromkeys(re.findall(r'[A-Za-z][A-Za-z0-9-]*|[가-힣]{2,}',query.lower())))
    aliases={'ai':['인공지능'],'capex':['설비투자','유형자산'],'hbm':['고대역폭'],'현금흐름':['영업활동현금흐름'],'연구개발':['개발']}
    return list(dict.fromkeys(words+[a for word in words for a in aliases.get(word,[])]))

def rank(query,rows,top_k,index_version):
    from .mysql_vectors import backend as selected_backend
    backend=selected_backend()
    if backend in ('numpy','faiss'):
        from .mysql_vectors import rank as mysql_rank
        return mysql_rank(query,rows,top_k,index_version,backend)
    if backend!='keyword':raise ValueError('이 검색 경로는 keyword/numpy/faiss를 지원합니다.')
    if not rows:return [],backend+'-no-evidence'
    if len(rows)>int(os.getenv('SEARCH_MAX_CANDIDATES','30000')):raise ValueError('검색 범위를 기업·기간으로 좁히세요.')
    words=terms(query)
    lexical=np.asarray([sum(min(5,r['chunk_text'].lower().count(t)) for t in words)/max(1,len(words)) for r in rows])
    chosen=[i for i in np.argsort(-lexical,kind='stable') if lexical[i]>0][:top_k]
    return [(rows[i],float(lexical[i])) for i in chosen],'mysql-keyword-only'
