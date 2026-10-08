"""Official KRX API adapter; exact index selection and resumable JSON cache."""
import json
import os
import time
from datetime import datetime,timedelta,timezone,date
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from .settings import DATA_ROOT,load_env
from .dart_client import save_json

URL='https://data-dbg.krx.co.kr/svc/apis/idx/krx_dd_trd'
NAME='KRX 반도체'

def korea_today():
    return datetime.now(timezone(timedelta(hours=9))).date()

def key_value():
    load_env()
    key=os.getenv('KRX_API','').strip()
    if not key:raise RuntimeError('BOOTCAMP_MINI/.env에 승인된 KRX_API를 설정하세요. KRX 시리즈 일별시세정보 서비스 승인도 필요합니다.')
    return key

def fetch_day(day,key,name=NAME,response_cache=None):
    path=Path(response_cache)/ (day.isoformat()+'.json') if response_cache else None
    # One daily response contains every KRX-series index. Reuse it across sectors.
    payload=json.loads(path.read_text(encoding='utf-8')) if path and path.exists() else None
    request=Request(URL+'?'+urlencode({'basDd':day.strftime('%Y%m%d')}),headers={'AUTH_KEY':key,'Accept':'application/json'})
    for attempt in range(3):
        if payload is not None:break
        try:
            with urlopen(request,timeout=25) as response:payload=json.load(response)
            break
        except HTTPError as error:
            if error.code in (401,403):
                raise RuntimeError(f'KRX API HTTP {error.code}: KRX가 인증·접근을 거절했습니다. 인증키 발급 승인과 KRX 시리즈 일별시세정보 서비스 이용 승인을 각각 확인하세요. 승인 대기·이용기간 만료·키 오류는 코드나 재시도로 해결되지 않습니다. 기존 자료는 보존됩니다.') from None
            if error.code not in (429,500,502,503,504) or attempt==2:
                raise RuntimeError(f'KRX API HTTP {error.code}: 기존 자료와 완료된 날짜 캐시는 보존됩니다.') from None
        except (URLError,TimeoutError):
            if attempt==2:raise RuntimeError('KRX API 연결 실패. 기존 자료는 보존됩니다.') from None
        except (ValueError,UnicodeError):
            raise RuntimeError('KRX API JSON 응답 오류. 기존 자료는 보존됩니다.') from None
        time.sleep(2**attempt)
    if not isinstance(payload,dict) or not isinstance(payload.get('OutBlock_1'),list):
        raise RuntimeError('KRX API 응답 구조 오류. 인증키·서비스 승인 상태를 확인하세요.')
    if path and payload['OutBlock_1']:save_json(path,payload)
    rows=payload['OutBlock_1']
    if not rows:return None  # Holiday or data not published yet; recent days are retried.
    matches=[r for r in rows if str(r.get('IDX_NM','')).strip()==name]
    if len(matches)!=1:
        raise RuntimeError(f'KRX API 응답에 {name} 항목이 없거나 중복됩니다. 이 API의 지수 제공 범위를 확인해야 합니다.')
    row=matches[0]
    try:
        actual=datetime.strptime(row['BAS_DD'].replace('-','').replace('/',''),'%Y%m%d').date()
        close=float(str(row['CLSPRC_IDX']).replace(',',''))
    except (KeyError,ValueError,TypeError):raise RuntimeError(f'{name} 날짜·종가 형식 오류.') from None
    import math
    if actual!=day or not math.isfinite(close) or close<=0:
        raise RuntimeError('KRX API 기준일 또는 종가 검증 실패. 기존 자료는 보존됩니다.')
    return dict(date=actual.isoformat(),value=close)

def collect_history(as_of=None,cache=None,name=NAME):
    today=as_of or korea_today();end=today-timedelta(days=1);start=end-timedelta(days=365*3)
    key=key_value();path=Path(cache) if cache else DATA_ROOT/('krx_api/index_days.json' if name==NAME else 'krx_api/'+name.replace(' ','_')+'_days.json')
    saved=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if saved.get('index')!=name:saved=dict(index=name,days={})
    days=saved['days'];calendar=[];day=end
    while day>=start:
        if day.weekday()<5:calendar.append(day)
        day-=timedelta(days=1)
    pending=[d for d in calendar if d.isoformat() not in days or d>=end-timedelta(days=7)]
    for i,day in enumerate(pending):
        point=fetch_day(day,key,name,response_cache=DATA_ROOT/'krx_api/daily_responses')
        days[day.isoformat()]=point
        save_json(path,saved)  # Resume initial three-year backfill without losing completed requests.
        if i==0 or (i+1)%50==0:print(f'{name} API 날짜 수집 {i+1}/{len(pending)} · {day}',flush=True)
        time.sleep(.12)
    days={d:r for d,r in days.items() if start.isoformat()<=d<=end.isoformat()}
    saved['days']=days;save_json(path,saved)
    return [r for d,r in sorted(days.items()) if r is not None]

if __name__=='__main__':
    import argparse,sys
    parser=argparse.ArgumentParser(description='KRX 인증 및 지수 제공 여부 단일 조회 검사')
    parser.add_argument('--name',default=NAME,help='API의 정확한 지수명 (예: KRX 헬스케어)')
    parser.add_argument('--date',type=date.fromisoformat,default=korea_today()-timedelta(days=1))
    args=parser.parse_args()
    try:
        result=fetch_day(args.date,key_value(),args.name)
        print(f'KRX API 정상 · {result["date"]} {args.name} 확인' if result else '인증·응답 정상 · 해당 날짜 자료 없음 (휴장·미게시 여부 확인)')
    except RuntimeError as error:
        print(str(error));sys.exit(1)
