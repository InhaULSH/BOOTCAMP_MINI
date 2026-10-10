"""팀원용 DART 중앙 MySQL 조회 모듈 (읽기 전용 계정 dart_backend).

준비 (팀원 PC):
    pip install pymysql pandas python-dotenv

같은 폴더(또는 실행 위치)에 .env 파일을 만들고 아래 값을 넣는다. .env는 Git에 올리지 않는다.
    MYSQL_HOST=192.168.0.232
    MYSQL_PORT=3306
    MYSQL_DATABASE=dart_big_in
    MYSQL_USER=dart_backend
    MYSQL_PASSWORD=<데이터 담당자에게 1:1로 받은 비밀번호>

사용 예:
    from dart_db_client import list_companies, get_financials, get_capex
    list_companies()
    get_financials("삼성전자", 2024, "FY", ["매출액", "영업이익"])
    get_capex("주성엔지니어링", 2024)

주의:
    - 이 모듈은 재무·텍스트 조회와 키워드(LIKE) 검색만 한다.
      질문과 비슷한 문단을 찾는 '의미 검색'은 dart_semantic_search.py를 사용한다.
    - 금액 단위는 원(KRW). value는 계산값/직접값 중 올바른 값이 이미 선택돼 있다.
    - report_type: Q1(1분기), H1(반기), Q3(3분기), FY(사업보고서)
"""
from __future__ import annotations

import os

import pandas as pd
import pymysql
from dotenv import load_dotenv

load_dotenv()

REPORT_ORDER = "FIELD(report_type, 'Q1', 'H1', 'Q3', 'FY')"


def get_connection() -> pymysql.connections.Connection:
    return pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.getenv("MYSQL_DATABASE", "dart_big_in"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
    )


def query(sql: str, params: tuple | list | None = None) -> pd.DataFrame:
    """임의 SELECT 실행. 값은 반드시 params(%s)로 넘긴다."""
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(sql, params)
        return pd.DataFrame(cursor.fetchall())


# ---------------------------------------------------------------------------
# 기본 조회
# ---------------------------------------------------------------------------
def list_companies() -> pd.DataFrame:
    """운영 기업 목록 (corp_name, corp_code, stock_code)."""
    return query("SELECT corp_name, corp_code, stock_code FROM companies "
                 "WHERE is_operational = 1 ORDER BY corp_name")


def list_standard_accounts() -> pd.DataFrame:
    """24개 표준계정 목록."""
    return query("SELECT standard_account_nm, category, period_nature "
                 "FROM standard_accounts ORDER BY display_order")


def get_financials(
    corp_name: str,
    year: int,
    report_type: str = "FY",
    accounts: list[str] | None = None,
    value_type: str | None = None,
) -> pd.DataFrame:
    """24개 표준계정 기준 재무 값.

    value_type: annual(연간) / cumulative(누적) / quarterly(분기 단독) / point_in_time(시점 잔액)
    """
    sql = ("SELECT corp_name, year, report_type, sj_div, standard_account, value_type, value, "
           "is_calculated, value_source, calculation_method, rcept_no "
           "FROM standardized_financials WHERE corp_name = %s AND year = %s AND report_type = %s")
    params: list = [corp_name, year, report_type]
    if accounts:
        sql += " AND standard_account IN (" + ", ".join(["%s"] * len(accounts)) + ")"
        params += accounts
    if value_type:
        sql += " AND value_type = %s"
        params.append(value_type)
    return query(sql + " ORDER BY standard_account, sj_div, value_type", params)


def get_quarterly_trend(corp_name: str, account: str, years: list[int] | None = None) -> pd.DataFrame:
    """분기 단독값(value_type='quarterly') 추이. 예: get_quarterly_trend('삼성전자', '매출액')."""
    sql = ("SELECT year, report_type, sj_div, value, is_calculated FROM standardized_financials "
           "WHERE corp_name = %s AND standard_account = %s AND value_type = 'quarterly'")
    params: list = [corp_name, account]
    if years:
        sql += " AND year IN (" + ", ".join(["%s"] * len(years)) + ")"
        params += years
    return query(sql + f" ORDER BY year, {REPORT_ORDER}", params)


def get_capex(corp_name: str, year: int | None = None) -> pd.DataFrame:
    """CAPEX(유형자산 취득). cash_outflow_amount=양수 지출 규모, quarterly 행은 calculated_value 사용."""
    sql = ("SELECT c.corp_name, x.year, x.report_type, x.value_type, x.value_source, "
           "x.cash_outflow_amount, x.calculated_value, x.is_calculated, x.calculation_method, "
           "x.source_account_names, x.review_required, x.rcept_no "
           "FROM capex_facts x JOIN companies c USING (corp_code) "
           "WHERE c.corp_name = %s AND x.is_active = 1")
    params: list = [corp_name]
    if year is not None:
        sql += " AND x.year = %s"
        params.append(year)
    return query(sql + f" ORDER BY x.year, FIELD(x.report_type, 'Q1', 'H1', 'Q3', 'FY'), x.value_type", params)


def get_coverage(corp_name: str | None = None) -> pd.DataFrame:
    """기업×연도×보고서별 데이터 존재 여부."""
    sql = ("SELECT c.corp_name, v.year, v.report_type, v.rcept_no, v.financial_exists, v.fs_div, "
           "v.filing_exists, v.embedding_exists, v.capex_status, v.status, v.reason "
           "FROM coverage v JOIN companies c USING (corp_code)")
    params: list = []
    if corp_name:
        sql += " WHERE c.corp_name = %s"
        params.append(corp_name)
    return query(sql + " ORDER BY c.corp_name, v.year, FIELD(v.report_type, 'Q1', 'H1', 'Q3', 'FY')", params)


# ---------------------------------------------------------------------------
# 공시 원문 (키워드 검색만 가능, 의미 검색은 데이터 담당자 PC의 Python 함수 필요)
# ---------------------------------------------------------------------------
def search_filing_text(
    keyword: str,
    corp_name: str | None = None,
    year: int | None = None,
    report_type: str | None = None,
    limit: int = 10,
) -> pd.DataFrame:
    """공시 청크 본문 키워드 검색(LIKE). 정확한 단어가 들어간 문단만 찾는다."""
    sql = ("SELECT chunk_id, corp_name, year, report_type, rcept_no, section_name, subsection_name, "
           "LEFT(chunk_text, 300) AS preview FROM chunk_metadata "
           "WHERE is_active = 1 AND is_searchable = 1 AND chunk_text LIKE %s")
    params: list = [f"%{keyword}%"]
    for column, value in (("corp_name", corp_name), ("year", year), ("report_type", report_type)):
        if value is not None:
            sql += f" AND {column} = %s"
            params.append(value)
    sql += " ORDER BY vector_id LIMIT %s"
    params.append(int(limit))
    return query(sql, params)


def get_chunk(chunk_id: str) -> dict | None:
    """청크 1개의 전체 본문과 출처."""
    frame = query("SELECT chunk_id, corp_name, year, report_type, rcept_no, section_name, "
                  "subsection_name, chunk_text FROM chunk_metadata WHERE chunk_id = %s", [chunk_id])
    return None if frame.empty else frame.iloc[0].to_dict()


def list_filing_sections(rcept_no: str) -> pd.DataFrame:
    """공시 1건의 목차(섹션)와 섹션별 청크 수."""
    return query("SELECT section_name, subsection_name, COUNT(*) AS chunks FROM chunk_metadata "
                 "WHERE rcept_no = %s AND is_active = 1 GROUP BY section_name, subsection_name "
                 "ORDER BY MIN(vector_id)", [rcept_no])


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    print(list_companies())
    print(get_financials("삼성전자", 2024, "FY", ["매출액", "영업이익"]))
    print(get_capex("원익IPS", 2024).head())
