"""Build sector reports from the current SQL and filing-vector databases."""
def build(use_llm=False, force=False, sector_id=None, codes=None, years=None):
    from snapdart_data.pipeline import build as build_db
    return build_db(sector_id,use_llm,force,codes,years)

if __name__ == '__main__':
    import argparse
    import os
    from .config import load_env
    load_env()
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--llm', action='store_true', help='LLM_PROVIDER로 선택한 모델의 분석 생성')
    mode.add_argument('--refresh-llm', action='store_true', help='선택한 LLM 분석 캐시를 재사용하지 않고 다시 생성')
    mode.add_argument('--offline', action='store_true', help='API 호출 없이 규칙 기반 보고서 생성')
    parser.add_argument('--sector',help='data_new의 섹터 폴더명')
    parser.add_argument('--companies',nargs='+',help='종목코드 또는 기업명; 생략 시 해당 섹터 전체')
    parser.add_argument('--years',nargs='+',type=int,help='생략 시 DB 최근 3개년')
    args = parser.parse_args()
    use_llm = not args.offline and (args.llm or args.refresh_llm)
    build(use_llm, force=args.refresh_llm, sector_id=args.sector,codes=args.companies,years=args.years)
