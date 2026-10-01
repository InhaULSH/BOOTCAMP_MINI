from dataclasses import dataclass
from pathlib import Path
import json
import os
import sqlite3

ROOT=Path(os.getenv('SNAPDART_DATA_ROOT',str(Path(__file__).resolve().parents[1]/'data_new'))).resolve()
SERVICE=ROOT/'service'

class ReadConnection(sqlite3.Connection):
    def __exit__(self,*args):
        try:return super().__exit__(*args)
        finally:self.close()

def connect(path):
    """Never create or mutate an input DB, including for a misspelled path."""
    connection=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,factory=ReadConnection)
    connection.row_factory=sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    return connection

@dataclass(frozen=True)
class Sector:
    id: str
    name: str
    folder: Path
    index_code: str|None=None
    companies_order: tuple=()
    topics: tuple=('주요 사업 제품 고객 수요 시장 변화', '설비투자 생산능력 공급 연구개발 양산', '경쟁 위험 불확실성 가격 재고')
    terms: tuple=()
    @property
    def financial(self):return self.folder/'financial.db'
    @property
    def filings(self):return self.folder/'filings.db'
    @property
    def report(self):return SERVICE/self.id/'reports.json'

def sectors(root=None):
    root=Path(root or ROOT)
    config_path=root/'sectors.json'
    config=json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
    output=[]
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or not (folder/'financial.db').is_file() or not (folder/'filings.db').is_file():continue
        settings=config.get(folder.name,{})
        # Folder names are IDs: never accept a user-supplied filesystem path.
        output.append(Sector(folder.name,settings.get('name',folder.name),folder,
            settings.get('index_code'),tuple(settings.get('companies_order',[])),
            tuple(settings.get('queries',Sector.__dataclass_fields__['topics'].default)),tuple(settings.get('terms',[]))))
    return output

def sector(value=None):
    choices=sectors()
    value=value or os.getenv('SNAPDART_SECTOR')
    if value:
        found=next((s for s in choices if s.id==value),None)
        if found:return found
        raise KeyError('등록되지 않은 섹터입니다.')
    if not choices:raise RuntimeError('data_new/<섹터>/financial.db와 filings.db가 필요합니다.')
    return choices[0]
