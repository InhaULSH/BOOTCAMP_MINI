"""Official index closes and full-constituent market caps from one KRX response."""
import json
import math
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from dotenv import load_dotenv

URL='https://data-dbg.krx.co.kr/svc/apis/idx/krx_dd_trd'


def today_korea():
    return datetime.now(timezone(timedelta(hours=9))).date()


def numeric(value):
    result=float(str(value).replace(',', ''))
    if not math.isfinite(result):raise ValueError('유효하지 않은 KRX 수치')
    return result


def daily(day, cache_dir, refresh=False):
    path=Path(cache_dir)/(day.isoformat()+'.json')
    if path.exists() and not refresh:return json.loads(path.read_text(encoding='utf-8'))
    base=Path(__file__).resolve().parents[1]
    load_dotenv(base/'.env',override=False);load_dotenv(base.parent/'.env',override=False)
    key=os.getenv('KRX_API','').strip()
    if not key:raise RuntimeError('승인된 KRX_API 환경변수가 필요합니다.')
    request=Request(URL+'?'+urlencode({'basDd':day.strftime('%Y%m%d')}),headers={'AUTH_KEY':key,'Accept':'application/json'})
    for attempt in range(3):
        try:
            with urlopen(request,timeout=25) as response:payload=json.load(response)
            break
        except (HTTPError,URLError,TimeoutError) as error:
            if isinstance(error,HTTPError) and error.code in (401,403):
                raise RuntimeError(f'KRX 인증·서비스 승인 오류 HTTP {error.code}. 기존 자료를 유지합니다.') from None
            retryable=not isinstance(error,HTTPError) or error.code in (429,500,502,503,504)
            if not retryable or attempt==2:raise RuntimeError('KRX API 조회 실패. 기존 자료를 유지합니다.') from None
            time.sleep(2**attempt)
    if not isinstance(payload,dict) or not isinstance(payload.get('OutBlock_1'),list):raise RuntimeError('KRX API 응답 구조 오류')
    if payload['OutBlock_1']:
        path.parent.mkdir(parents=True,exist_ok=True)
        temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            temp.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8');temp.replace(path)
        finally:temp.unlink(missing_ok=True)
    return payload


def collect(names, cache_dir, as_of=None, refresh=False):
    """Return two actual sessions before today; never mix caps from another date/index."""
    names=list(dict.fromkeys(names));today=as_of or today_korea();points={name:[] for name in names}
    if not names:return {}
    for offset in range(1,32):
        day=today-timedelta(days=offset)
        if day.weekday()>=5:continue
        rows=daily(day,cache_dir,refresh)['OutBlock_1']
        if not rows:continue
        for name in names:
            if len(points[name])>=2:continue
            found=[r for r in rows if str(r.get('IDX_NM','')).strip()==name]
            if len(found)!=1:raise RuntimeError(f'KRX API에 {name}이 없거나 중복됩니다.')
            row=found[0]
            try:
                actual=datetime.strptime(str(row['BAS_DD']).replace('-',''),'%Y%m%d').date()
                close=numeric(row['CLSPRC_IDX']);raw_cap=str(row['MKTCAP']).replace(',','')
                cap=int(raw_cap)
                if actual!=day or close<=0 or cap<=0:raise ValueError()
            except (KeyError,ValueError,TypeError):raise RuntimeError(f'{name} 기준일·종가·전체 시가총액 검증 실패') from None
            points[name].append(dict(date=day.isoformat(),value=close,cap=cap))
        if all(len(p)==2 for p in points.values()):break
    if any(len(p)<2 for p in points.values()):raise RuntimeError('전일까지의 두 거래일 KRX 자료가 필요합니다.')
    result={}
    for name,(current,previous) in points.items():
        result[name]=dict(name=name+' 지수',source='KRX OPEN API',stale=False,
            history=[dict(date=p['date'],value=p['value']) for p in (previous,current)],
            price=current['value'],traded_at=current['date'],previous_traded_at=previous['date'],
            change=(current['value']/previous['value']-1)*100,point_change=current['value']-previous['value'],
            constituent_market_cap=current['cap'],market_cap_traded_at=current['date'],
            market_cap_source='KRX OPEN API MKTCAP',market_cap_scope='all_index_constituents',
            price_basis='previous_session_close')
    return result


def merge(old, current, code):
    cutoff=current['traded_at']
    history={r['date']:r['value'] for r in old.get('history',[]) if r['date']<=cutoff}
    history.update({r['date']:r['value'] for r in current['history']})
    return dict(current,code=code,history=[dict(date=d,value=v) for d,v in sorted(history.items())])
