"""Project paths and environment loading without opening any sector database."""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]

def load_env():
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('\"\''))

load_env()
DATA_ROOT = Path(os.getenv('SNAPDART_DATA_ROOT', str(ROOT / 'data'))).resolve()
