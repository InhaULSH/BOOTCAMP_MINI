from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]



def load_env():
    for path in (ROOT / '.env',):
        if not path.exists():
            continue
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('\"\''))

load_env()
from snapdart_data.catalog import SERVICE,sector
from snapdart_data.repository import Repository
SERVICE_ROOT = SERVICE
YEARS = Repository().years()[-3:]
COMPANIES = [dict(code=c['stock_code'],name=c['company_name'],sector=sector().name,
    description='공시와 전사 재무 기반 분석') for c in Repository().companies()]

