from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'opendart'
YEARS = list(range(2021, 2026))
COMPANIES = [
    dict(code='005930', name='삼성전자', sector='종합 반도체·전자', semiconductor=True, description='메모리, 시스템반도체와 파운드리를 비롯해 모바일·가전 사업을 운영합니다. 재무지표는 전사 기준입니다.'),
    dict(code='000660', name='SK하이닉스', sector='메모리 반도체', semiconductor=True, description='DRAM과 NAND Flash를 생산하며 HBM 등 고부가 메모리 제품을 공급합니다.'),
    dict(code='042700', name='한미반도체', sector='반도체 후공정 장비', semiconductor=True, description='반도체 패키징 장비와 TC 본더 등 후공정 장비를 공급합니다.'),
    dict(code='036930', name='주성엔지니어링', sector='반도체 증착 장비', semiconductor=True, description='반도체 증착 장비와 디스플레이·태양광 관련 장비 사업을 운영합니다.'),
    dict(code='240810', name='원익IPS', sector='반도체 공정 장비', semiconductor=True, description='반도체 증착·열처리 등 공정 장비와 디스플레이 장비를 공급합니다.'),
]


def load_env():
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('\"\''))

