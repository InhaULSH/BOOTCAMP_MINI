"""Build a disposable MySQL-shaped fixture from original XML, without a DB.

This is test input preparation, not an alternative production ingestion pipeline.
Only representative natural-language chunks are embedded to bound CPU work.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def prepare(output, reuse_vectors=False):
    # Download and connection attempts are forbidden during fixture preparation.
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', BGE_M3_DEVICE='cpu')
    import numpy as np
    from dart_remote import db, mysql_vectors as vectors
    from dart_remote.original_document import parsed
    from dart_remote.xml_financials import extract_facts
    from dart_remote.citation_selection import passages
    from unittest.mock import patch

    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / 'xml').mkdir(exist_ok=True)
    previous=json.loads((output/'fixture.json').read_text(encoding='utf-8')) if reuse_vectors else None
    manifest = json.loads((ROOT / 'data/xml_origin/manifest.json').read_text(encoding='utf-8'))
    stocks = {'삼성전자': '005930', 'SK하이닉스': '000660', '한미반도체': '042700',
              '주성엔지니어링': '036930', '원익IPS': '240810'}
    companies = [dict(corp_code='TEST'+str(i), stock_code=stock, corp_name=name,
                      company_name=name, is_operational=1) for i, (name, stock) in enumerate(stocks.items())]
    chunks, documents, facts, audit = [], [], [], []
    sources = [r for r in manifest['documents'] if r['report_type'] == 'FY' or
               (r['year'] == 2025 and r['report_type'] == 'Q3')]
    queries = ['HBM 수요와 설비투자 확대 계획', '주요 사업 제품 고객 수요 시장 변화',
               '설비투자 생산능력 연구개발 양산', '경쟁 위험 가격 재고', 'HBM', '설비투자']
    with patch.object(db, 'rows', side_effect=AssertionError('테스트 준비 중 DB 접근 금지')):
        for source in sources:
            path = ROOT / 'data' / Path(source['path'].replace('\\', '/'))
            raw = path.read_bytes()
            receipt = source['rcept_no']
            shutil.copyfile(path, output / 'xml' / (receipt + '.xml'))
            root, _, repairs = parsed(raw)
            company = next(c for c in companies if c['company_name'] == source['company'])
            section, heading, natural = '', '', []
            for element in root.iter():
                tag = element.tag.upper()
                text = re.sub(r'\s+', ' ', ''.join(element.itertext())).strip()
                if tag in ('TITLE', 'SUBTITLE'):
                    if re.match(r'^(?:I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII)\.', text):
                        section = text
                    else:
                        heading = text
                if tag == 'P' and section.startswith('II.') and passages(text):
                    # Nonoverlapping subdivision of each paragraph, preserving offsets.
                    for start in range(0, len(text), 600):
                        block = text[start:start + 600]
                        if passages(block):
                            natural.append((section, heading, block, start))
            ranked = sorted(natural, key=lambda p: -sum(p[2].count(q) for q in
                            ('HBM', '수요', '투자', '생산', '고객', '제품')))
            # Two real chunks per report; this intentionally is not full-corpus evaluation.
            for section, heading, text, offset in ranked[:2]:
                digest = hashlib.sha256(text.encode()).hexdigest()
                chunks.append(dict(chunk_id='test-'+str(len(chunks)), vector_id=len(chunks),
                    corp_code=company['corp_code'], corp_name=company['company_name'],
                    year=source['year'], report_type=source['report_type'], rcept_no=receipt,
                    source_path=receipt+'.xml', section_name=section, subsection_name=heading,
                    chunk_text=text, paragraph_start=offset, content_hash=digest,
                    data_version='offline-xml-v1', index_version='offline-bge-v1',
                    embedding_model=vectors.MODEL, model_revision=vectors.REVISION,
                    embedding_dimension=vectors.DIM, is_active=1, is_searchable=1))
            extracted = []
            for basis in ('CFS', 'OFS'):
                mode = 'annual' if source['report_type'] == 'FY' else 'cumulative'
                values = extract_facts(raw, source['year'], source['report_type'], basis, mode,
                                       receipt, receipt)
                if source['report_type']=='Q3':
                    # Keep actual 3-month IS columns separately from cumulative
                    # CF columns; never derive quarters from annual totals.
                    quarterly=extract_facts(raw,source['year'],source['report_type'],basis,
                                            'quarterly',receipt,receipt)
                    values += [v for v in quarterly if v['value_type']=='quarterly']
                for value in values:
                    extracted.append(dict(value, corp_code=company['corp_code'], corp_name=company['company_name'],
                        year=source['year'], report_type=source['report_type'],
                        standard_account_nm={'revenue':'매출액','operating_income':'영업이익',
                         'operating_cashflow':'영업활동현금흐름','inventory':'재고자산','capex':'유형자산취득(CAPEX)'}[value['key']],
                        normalized_value=value['value'], is_calculated=0, is_active=1,
                        data_version='offline-xml-v1'))
            facts.extend(extracted)
            documents.append(dict(**source, corp_code=company['corp_code'], corp_name=company['company_name'],
                                  period=str(source['year'])+('-12' if source['report_type']=='FY' else '-09')))
            audit.append(dict(company=source['company'], year=source['year'], report_type=source['report_type'],
                              rcept_no=receipt, xml_sha256=hashlib.sha256(raw).hexdigest(),
                              repairs=repairs, eligible_blocks=len(natural), facts=len(extracted)))
            print(source['company'], source['year'], source['report_type'], 'facts', len(extracted), flush=True)
        texts = [' '.join((r['section_name'], r['subsection_name'], r['chunk_text'])).strip() for r in chunks]
        print('실제 BGE-M3 임베딩:', len(texts), '청크 +', len(queries), '질문', flush=True)
        if previous is not None:
            if previous['chunks']!=chunks or previous['queries']!=queries:
                raise ValueError('청크·질문이 변경되어 기존 테스트 벡터를 재사용할 수 없습니다.')
            with np.load(output/'vectors.npz',allow_pickle=False) as cached:
                matrix=cached['matrix'];question_vectors=cached['questions']
            if matrix.shape!=(len(chunks),vectors.DIM):raise ValueError('기존 테스트 벡터 형식 오류')
        else:
            matrix = vectors.encode(texts)
            question_vectors = vectors.encode(queries)
            np.savez(output / 'vectors.npz', matrix=matrix, questions=question_vectors)
        payload = dict(companies=companies, documents=documents, chunks=chunks, facts=facts,
                       queries=queries, audit=audit, model=vectors.MODEL, revision=vectors.REVISION,
                       embedding_dimension=vectors.DIM)
        (output / 'fixture.json').write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(dict(documents=len(documents), chunks=len(chunks), financial_facts=len(facts)), ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--reuse-vectors',action='store_true')
    args=parser.parse_args()
    prepare(args.output,args.reuse_vectors)
