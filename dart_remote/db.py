"""Lazy, read-only remote MySQL pool; artifacts use a separate application store."""
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)
# Local deployment tests can share the workspace .env; Cloud Run still uses
# injected environment variables and does not include either file in its image.
load_dotenv(Path(__file__).resolve().parents[2] / '.env', override=False)
for target, source in {
    'MYSQL_HOST':'SQL_HOST_NAME', 'MYSQL_PORT':'SQL_PORT',
    'MYSQL_USER':'SQL_USER_NAME', 'MYSQL_DATABASE':'SQL_DEFAULT_SCHEMA',
    'MYSQL_PASSWORD':'SQL_PSWD',
}.items():
    if target not in os.environ and source in os.environ:
        os.environ[target] = os.environ[source]
_connector = None

def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', value):
        raise ValueError('허용되지 않은 테이블 이름입니다.')
    return '`' + value + '`'

def decoded(value):
    return json.loads(value) if isinstance(value, (str, bytes)) else value

@lru_cache(maxsize=1)
def engine():
    required = ('MYSQL_USER', 'MYSQL_DATABASE')
    if any(not os.getenv(k) for k in required):
        raise RuntimeError('MySQL 접속 환경변수를 설정하세요.')
    kwargs = dict(pool_size=int(os.getenv('DB_POOL_SIZE', '5')), max_overflow=0,
                  pool_pre_ping=True, pool_recycle=1800, pool_timeout=15)
    instance = os.getenv('CLOUD_SQL_INSTANCE')
    if instance:
        from google.cloud.sql.connector import Connector, IPTypes
        global _connector
        _connector = Connector(refresh_strategy='LAZY')
        ip = IPTypes[os.getenv('CLOUD_SQL_IP_TYPE', 'PUBLIC').upper()]
        def creator():
            return _connector.connect(instance, 'pymysql', user=os.environ['MYSQL_USER'],
                password=os.getenv('MYSQL_PASSWORD', ''), db=os.environ['MYSQL_DATABASE'], ip_type=ip)
        return create_engine('mysql+pymysql://', creator=creator, **kwargs)
    # Use the provided DART client factory, keeping the service's connection pool.
    from . import dart_db_client
    import pymysql
    args = dict(cursorclass=pymysql.cursors.Cursor, connect_timeout=15,
                read_timeout=90, write_timeout=30)
    if os.getenv('MYSQL_SSL_CA'):
        args.update(ssl_ca=os.environ['MYSQL_SSL_CA'], ssl_verify_cert=True, ssl_verify_identity=True)
    return create_engine('mysql+pymysql://', creator=lambda: dart_db_client.get_connection(**args), **kwargs)


def rows(sql, params=None):
    """Only SELECT statements; upstream data is never an application write store."""
    if not sql.lstrip().upper().startswith('SELECT '):raise ValueError('원격 저장소에는 SELECT 조회만 허용합니다.')
    from datetime import date,datetime
    from decimal import Decimal
    def clean(value):
        if isinstance(value,(date,datetime)):return value.isoformat()
        if isinstance(value,Decimal):return float(value)
        return value
    with engine().connect() as con:
        con.execute(text('START TRANSACTION READ ONLY'))
        try:return [{k:clean(v) for k,v in r.items()} for r in con.execute(text(sql),params or {}).mappings()]
        finally:con.rollback()

def close():
    global _connector
    if engine.cache_info().currsize:engine().dispose();engine.cache_clear()
    if _connector is not None:_connector.close();_connector=None
