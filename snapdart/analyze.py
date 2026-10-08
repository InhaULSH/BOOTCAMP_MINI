"""Build sector reports from the current SQL and filing-vector databases."""
def build(use_llm=False, force=False, sector_id=None, codes=None, years=None):
    from snapdart.data_access.pipeline import build as build_db
    if sector_id:return build_db(sector_id,use_llm,force,codes,years)
    from snapdart.data_access.catalog import sectors
    registered=sectors(all_sectors=True)
    if not registered:raise ValueError('분석 가능한 섹터가 없습니다.')
    print('분석 대상 전체 섹터: '+', '.join(s.name for s in registered),flush=True)
    results=[];failures=[]
    for item in registered:
        print(f'{item.name} 분석 시작',flush=True)
        try:results.append(build_db(item.id,use_llm,force,codes,years))
        except Exception as error:
            failures.append(item.name)
            print(f'{item.name} 분석 실패: {error}',flush=True)
    if failures:raise RuntimeError('다른 섹터 처리는 완료했으나 실패한 섹터가 있습니다: '+', '.join(failures))
    return results

if __name__ == '__main__':
    import argparse
    from .config import load_env
    load_env()
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--llm', action='store_true', help='Gemini API로 분석 생성')
    mode.add_argument('--refresh-llm', action='store_true', help='Gemini 분석 캐시를 재사용하지 않고 다시 생성')
    mode.add_argument('--offline', action='store_true', help='API 호출 없이 규칙 기반 보고서 생성')
    parser.add_argument('--sector',help='MySQL 섹터 이름 또는 지수 코드; 생략 시 모든 섹터')
    parser.add_argument('--companies',nargs='+',help='종목코드 또는 기업명; 생략 시 해당 섹터 전체')
    parser.add_argument('--years',nargs='+',type=int,help='생략 시 DB에 적재된 전체 연도')
    parser.add_argument('--prompt-version',choices=['new','old'],default='new',help='프롬프트 및 근거 평가 버전')
    args = parser.parse_args()
    import os
    os.environ['LLM_PROMPT_VERSION']=args.prompt_version
    use_llm = not args.offline and (args.llm or args.refresh_llm)
    build(use_llm, force=args.refresh_llm, sector_id=args.sector,codes=args.companies,years=args.years)
