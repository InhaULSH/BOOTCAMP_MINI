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
from .config import load_env

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

