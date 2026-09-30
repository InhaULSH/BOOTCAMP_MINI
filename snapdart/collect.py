"""Resumable OpenDART collection. Credentials never enter persisted URLs/logs."""
import io
import json
import os
import re
import time
import zipfile
from datetime import date
from urllib.request import urlopen, Request
from urllib.parse import urlencode
from xml.etree import ElementTree as ET
from .config import DATA, COMPANIES, YEARS, load_env

def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)

class DartClient:
    def __init__(self):
        load_env()
        self.key = os.getenv('OPENDART_API_KEY') or os.getenv('DART_API_KEY')
        if not self.key:
            raise RuntimeError('.env에 OPENDART_API_KEY를 설정하세요.')

    def request(self, endpoint, **params):
        url = 'https://opendart.fss.or.kr/api/' + endpoint + '?' + urlencode(dict(crtfc_key=self.key, **params))
        for attempt in range(4):
            try:
                with urlopen(Request(url, headers={'User-Agent': 'SnapDART-local/1.0'}), timeout=90) as response:
                    raw = response.read()
                time.sleep(.2)
                break
            except Exception:
                if attempt == 3:
                    raise RuntimeError(f'{endpoint}: 네트워크 요청 실패') from None
                time.sleep(2 ** attempt)
        if endpoint.endswith('.json'):
            result = json.loads(raw)
            if result.get('status') not in ('000', '013'):
                raise RuntimeError(f"OpenDART 오류 {result.get('status')}: {result.get('message')}")
            return result
        if not zipfile.is_zipfile(io.BytesIO(raw)):
            try:
                status = ET.fromstring(raw).findtext('status')
            except ET.ParseError:
                status = '응답 형식 오류'
            raise RuntimeError(f'{endpoint}: {status}')
        return raw

def select_filings(rows):
    selected = {}
    for row in rows:
        match = re.search(r'(사업|반기|분기)보고서\s*\((\d{4})\.(\d{2})\)', row['report_nm'])
        if not match or int(match[2]) not in YEARS:
            continue
        kind, year, month = match.groups()
        if (kind, month) not in [('사업','12'), ('반기','06'), ('분기','03'), ('분기','09')]:
            continue
        key = year + '-' + month
        if key not in selected or row['rcept_no'] > selected[key]['rcept_no']:
            selected[key] = dict(row, period=key)
    return sorted(selected.values(), key=lambda x: x['period'])

def collect():
    client = DartClient()
    DATA.mkdir(parents=True, exist_ok=True)
    codes_path = DATA / 'corpCode.zip'
    if not codes_path.exists():
        codes_path.write_bytes(client.request('corpCode.xml'))
    with zipfile.ZipFile(codes_path) as z:
        root = ET.fromstring(z.read(z.namelist()[0]))
    codes = {x.findtext('stock_code'): x.findtext('corp_code') for x in root.findall('list')}
    inventory = []
    for company in COMPANIES:
        folder = DATA / company['code']
        folder.mkdir(exist_ok=True)
        corp = codes[company['code']]
        rows = []
        page = 1
        while True:
            result = client.request('list.json', corp_code=corp, bgn_de='20210101', end_de=date.today().strftime('%Y%m%d'), pblntf_ty='A', last_reprt_at='Y', page_count=100, page_no=page)
            rows.extend(result.get('list', []))
            if page >= int(result.get('total_page', 1)):
                break
            page += 1
        filings = select_filings(rows)
        save_json(folder / 'filings.json', filings)
        for filing in filings:
            dest = folder / (filing['rcept_no'] + '.zip')
            if not dest.exists():
                dest.write_bytes(client.request('document.xml', rcept_no=filing['rcept_no']))
            print(f"{company['name']} {filing['period']} 저장", flush=True)
        for year in YEARS:
            dest = folder / f'financial_{year}.json'
            if dest.exists():
                continue
            result = client.request('fnlttSinglAcntAll.json', corp_code=corp, bsns_year=year, reprt_code='11011', fs_div='CFS')
            basis = 'CFS'
            if result.get('status') == '013':
                basis = 'OFS'
                result = client.request('fnlttSinglAcntAll.json', corp_code=corp, bsns_year=year, reprt_code='11011', fs_div='OFS')
            save_json(dest, dict(result, basis=basis))
        missing = [f'{y}-{m}' for y in YEARS for m in ('03','06','09','12') if f'{y}-{m}' not in {f['period'] for f in filings}]
        inventory.append(dict(company=company['name'], reports=len(filings), missing=missing))
        save_json(DATA / 'inventory.json', inventory)
    print(json.dumps(inventory, ensure_ascii=False), flush=True)

if __name__ == '__main__':
    collect()
