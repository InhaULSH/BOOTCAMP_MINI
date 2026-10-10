"""Exercise the production server with real-XML fixtures and simulated Gemini.

Run only after offline_xml_fixture.py. All DB/HTTP boundaries are replaced;
retrieval, arithmetic, prompts, validation, generation, HTML and API code run.
The Linux invocation should use Docker --network none. No test data is durable.
"""
import argparse
import copy
import hashlib
import io
import json
import os
import platform
import sys
import tempfile
import unittest
from contextlib import ExitStack
from functools import cached_property
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'deploy'), str(ROOT)]
os.environ.update(NO_MARKET_REFRESH='1', UI_PREWARM='0', GEMINI_API_KEY='offline-test-key',
                  GEMINI_CONCURRENCY='4', PROMPT_VERSION='new')


def run(folder, result_path):
    import numpy as np
    from dart_remote import db, artifacts, mysql_vectors as vectors, citation_selection as selection
    from dart_remote import sources, original_document, wordcloud, token_counts
    from dart_remote.catalog import Sector
    from dart_remote.repository import Repository, REPORTS
    from dart_remote.response_validation import validate_money, cached_result, OUTPUT_NOTE
    from cloudapp import pipeline, llm, main, ui_project, dashboard
    from fastapi.testclient import TestClient

    folder = Path(folder)
    fixture = json.loads((folder / 'fixture.json').read_text(encoding='utf-8'))
    with np.load(folder / 'vectors.npz', allow_pickle=False) as values:
        matrix, questions = values['matrix'], values['questions']
    meta = fixture['chunks']
    sector = Sector('반도체', '반도체', 'KRX_SEMI', 'offline-xml-v1', 'offline-bge-v1', '5044',
                    topics=(fixture['queries'][0],))
    contract = dict(data_version=sector.data_version, index_version=sector.index_version,
                    count=len(meta), asset_pairs=[[sector.data_version, sector.index_version]])
    encoder = {q: v for q, v in zip(fixture['queries'], questions)}
    encoder.update({' '.join((r['section_name'], r['subsection_name'], r['chunk_text'])).strip(): v
                    for r, v in zip(meta, matrix)})
    published = {}
    http_requests, prompt_hashes = [], set()
    budget_calls = Mock()

    class FixtureRepository(Repository):
        def __init__(self, selected=None):
            if selected not in (None, sector, sector.id): raise KeyError('없는 테스트 섹터')
            self.sector = sector
        @cached_property
        def members(self): return copy.deepcopy(fixture['companies'])
        @cached_property
        def _all_facts(self): return copy.deepcopy(fixture['facts'])
        def years(self): return sorted({d['year'] for d in fixture['documents']})
        def json_financial_exists(self, code, year, report_type): return True
        def documents(self, code):
            corp = self.company(code)['corp_code']
            return [dict(d, receipt_no=d['rcept_no'], document_id=d['rcept_no'],
                         report_name=REPORTS[d['report_type']][1])
                    for d in fixture['documents'] if d['corp_code']==corp]
        def chunks(self, code=None, year=None, report_type=None, business_only=False):
            codes = code if isinstance(code, (list,tuple)) else [code] if code else []
            corps = {self.company(c)['corp_code'] for c in codes} if codes else None
            return [copy.deepcopy(r) for r in meta if (corps is None or r['corp_code'] in corps)
                    and (year is None or r['year']==year) and (report_type is None or r['report_type']==report_type)]
        def chunk(self, chunk_id): return copy.deepcopy(next(r for r in meta if r['chunk_id']==chunk_id))
        def coverage(self, code=None, year=None, report_type=None):
            return dict(constituent_count=5, operational_count=5, missing_chunk_companies=[],
                        unbuilt_companies=[], incomplete_reports=[])

    repo = FixtureRepository()

    def virtual_rows(sql, params=None):
        # This is a read-only in-memory boundary, NOT a live DB driver.
        params = params or {}
        if sql.startswith('SELECT chunk_id,section_name,subsection_name,chunk_text'):
            return [copy.deepcopy(r) for r in meta if r['chunk_id'] in params.values()]
        if 'raw_xml' in sql and 'filing_source_documents' in sql:
            receipt=params['r'];raw=(folder/'xml'/(receipt+'.xml')).read_bytes()
            return [dict(raw_xml=raw,sha256=hashlib.sha256(raw).hexdigest(),byte_size=len(raw),
                         rcept_no=receipt,data_version=sector.data_version,document_id=receipt,
                         mapping_version=sector.data_version,chunk_version=sector.data_version)]
        raise AssertionError('테스트에 정의되지 않은 DB 조회: '+sql[:100])

    def encode(texts):
        return np.asarray([encoder[text.strip()] for text in texts], dtype=np.float32)

    def apply_cloud(report, repository):
        # Keyword scoring is covered by existing regression tests. Here isolate
        # its output boundary to exercise downstream keyword RAG and validation.
        year=str(report['years'][-1])
        for scope in [report]+report['companies']:
            items=[]
            rows=repository.chunks(scope.get('code'),report['years'][-1])
            for keyword in ('HBM','설비투자'):
                count=sum(keyword in r['chunk_text'] for r in rows)
                items.append(dict(text=keyword,keyword=keyword,count=count,display_weight=max(1,count),is_hot=False))
            scope['wordcloud']={year:items}
        return report

    def valid_answer(evidence, count=1):
        candidates=[e for e in evidence if e['kind']=='filing' and e['passages']]
        e=candidates[-1];p=e['passages'][0]
        assessment=dict(id=e['id'],grades=dict(F=4,U=4,C=4,T=4),suitable=True,
            reason='입력의 실제 공시 문장이 직접 뒷받침합니다.',irrelevant_content='none',
            redundancy='none',passage_ids=[p['id']])
        return dict(sentences=[dict(text=e['company']+' 공시에서 확인한 내용: '+p['text'],
             refs=[e['id']],assessments=[copy.deepcopy(assessment)]) for _ in range(count)],insufficient_reason='')

    def response(request, **kwargs):
        payload=json.loads(request.data)
        http_requests.append(payload)
        instruction=payload['systemInstruction']['parts'][0]['text']
        prompt_hashes.add(hashlib.sha256(instruction.encode()).hexdigest())
        content=json.loads(payload['contents'][0]['parts'][0]['text'])
        if 'materials' in content: content=content['materials']
        value=valid_answer(content['evidence'])
        return io.BytesIO(json.dumps(envelope(value),ensure_ascii=False).encode())

    def envelope(value=None, finish='STOP'):
        candidate=dict(finishReason=finish)
        if value is not None:
            candidate['content']=dict(parts=[dict(text=json.dumps(value,ensure_ascii=False))])
        return dict(candidates=[candidate],usageMetadata=dict(promptTokenCount=100),modelVersion='simulated-gemini')

    suite=unittest.TestSuite()
    def case(name, function): suite.addTest(unittest.FunctionTestCase(function, description=name))
    def check(condition,message='assertion failed'):
        if not condition:raise AssertionError(message)
    def rejects(action,kind=ValueError):
        try:action()
        except kind:return
        raise AssertionError('예상한 '+kind.__name__+' 오류가 발생하지 않음')

    # Keep transient writes inside the requested result directory, including on
    # Windows where a restricted runner may not access the OS temp directory.
    runtime_parent=Path(result_path).resolve().parent
    runtime_parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='dart-xml-server-',dir=runtime_parent) as temporary, ExitStack() as stack:
        work=Path(temporary)
        os.environ['DART_CACHE_DIR']=str(work/'vectors')
        stack.enter_context(patch.object(db,'rows',side_effect=virtual_rows))
        stack.enter_context(patch.object(db,'engine',side_effect=AssertionError('실제 DB 연결 금지')))
        stack.enter_context(patch.object(db,'close',return_value=None))
        stack.enter_context(patch.object(main.db,'close',return_value=None))
        stack.enter_context(patch.object(artifacts,'ROOT',work/'artifacts'))
        for module in (pipeline,main,ui_project,sources):
            stack.enter_context(patch.object(module,'Repository',FixtureRepository))
        stack.enter_context(patch.object(vectors,'contract',return_value=contract))
        stack.enter_context(patch.object(vectors,'snapshot',return_value=(meta,matrix)))
        stack.enter_context(patch.object(vectors,'encode',side_effect=encode))
        stack.enter_context(patch.object(vectors,'_verified',None))
        stack.enter_context(patch.object(vectors,'_queries',dict(zip(fixture['queries'],questions))))
        stack.enter_context(patch.object(original_document,'source_versions',return_value=[sector.data_version]))
        stack.enter_context(patch.object(wordcloud,'apply',side_effect=apply_cloud))
        stack.enter_context(patch.object(llm,'count_input_tokens',return_value=100))
        stack.enter_context(patch.object(token_counts,'cached_count',side_effect=lambda p,m,count:count()))
        stack.enter_context(patch.object(llm.TOKEN_BUDGET,'reserve',budget_calls))
        stack.enter_context(patch.object(llm,'urlopen',side_effect=response))
        stack.enter_context(patch.object(llm.time,'sleep',return_value=None))
        stack.enter_context(patch.object(llm,'retry_delay',return_value=0))
        # Let missing production names fail, rather than mask deployment bugs.
        if hasattr(pipeline,'SERVICE'):stack.enter_context(patch.object(pipeline,'SERVICE',work/'artifacts'))
        stack.enter_context(patch.object(pipeline.db,'put_artifact',side_effect=lambda s,k,v:published.update({(s,k):copy.deepcopy(v)})))
        stack.enter_context(patch.object(pipeline.db,'get_artifact',side_effect=lambda s,k:copy.deepcopy(published.get((s,k)))))
        stack.enter_context(patch.object(main,'sectors',return_value=[sector]))
        stack.enter_context(patch.object(ui_project,'sectors',return_value=[sector]))

        evidence=[]
        for i,r in enumerate(meta[:8],1):
            ps=selection.passages(r['chunk_text'])
            evidence.append(dict(id='t'+str(i),kind='filing',company=r['corp_name'],year=r['year'],
                period=str(r['year'])+'-'+REPORTS[r['report_type']][0],text=r['chunk_text'],
                passages=[dict(p,id='t'+str(i)+'-p'+str(j)) for j,p in enumerate(ps,1)]))
        base=valid_answer(evidence)
        assessment=lambda v:v['sentences'][0]['assessments'][0]
        def validate(value):
            selection.validate(value,evidence,1,3)
            return validate_money(value,evidence)
        def variant(change):
            v=copy.deepcopy(base);change(v);return v

        case('BGE-M3 dimension/norm/version integrity',lambda:vectors.validate(meta,matrix,contract))
        case('BGE-M3 re-embedding model verification',lambda:vectors.verify_model(contract,meta,matrix))
        for method in ('numpy','faiss') if platform.system()!='Windows' else ('numpy',):
            def search(method=method):
                with patch.dict(os.environ,SEARCH_BACKEND=method):
                    hits,status=repo.search(fixture['queries'][0],'005930',2025,'FY',top_k=2)
                    check(len(hits)==2 and all(h['company']=='삼성전자' and h['year']==2025 for h in hits))
                    check(status['mode']==method+'-bge-m3-cosine',repr(status))
            case(method+' real cosine retrieval and filters',search)
        if platform.system()!='Windows':
            def parity():
                a=vectors.top_indices(matrix,questions[0],5,'numpy')
                b=vectors.top_indices(matrix,questions[0],5,'faiss')
                check([i for i,s in a]==[i for i,s in b])
                check(np.allclose([s for i,s in a],[s for i,s in b],atol=1e-6))
            case('FAISS / NumPy exact Top-K parity',parity)
        bad_matrix=matrix.copy();bad_matrix[0,0]=np.nan
        case('reject NaN vector',lambda:rejects(lambda:vectors.validate(meta,bad_matrix,contract)))
        case('reject wrong vector dimension',lambda:rejects(lambda:vectors.validate(meta,matrix[:,:3],contract)))
        case('reject duplicate vector ID',lambda:rejects(lambda:vectors.validate([meta[0]]*len(meta),matrix,contract)))
        case('reject wrong snapshot version',lambda:rejects(lambda:vectors.rank(fixture['queries'][0],meta,3,'wrong','numpy'),RuntimeError))
        case('reject empty cleaned query',lambda:rejects(lambda:vectors.rank('삼성전자',repo.chunks('005930'),3,sector.index_version,'numpy')))
        for count in (1,2,3):
            case('accept insight '+str(count)+' item(s)',lambda count=count:validate(valid_answer(evidence,count)))
        case('accept keyword one item',lambda:selection.validate(copy.deepcopy(base),evidence,1,2))
        case('accept explicit insufficient evidence',lambda:validate(dict(sentences=[],insufficient_reason='적격 근거가 부족합니다.')))
        changes={
            'null sentence':lambda v:v.update(sentences=[None]),
            'null assessments':lambda v:v['sentences'][0].update(assessments=None),
            'null grades':lambda v:assessment(v).update(grades=None),
            'boolean grade':lambda v:assessment(v)['grades'].update(F=True),
            'string grade':lambda v:assessment(v)['grades'].update(F='4'),
            'unsuitable evidence':lambda v:assessment(v).update(suitable=False),
            'selected low score':lambda v:assessment(v).update(grades=dict(F=2,U=2,C=2,T=2)),
            'unknown chunk ID':lambda v:v['sentences'][0].update(refs=['unknown']),
            'unknown passage ID':lambda v:assessment(v).update(passage_ids=['t999-p1']),
            'duplicate refs':lambda v:v['sentences'][0]['refs'].append(v['sentences'][0]['refs'][0]),
            'null text':lambda v:v['sentences'][0].update(text=None),
            'too many summary items':lambda v:v.update(sentences=v['sentences']*4),
            'empty without reason':lambda v:v.update(sentences=[],insufficient_reason=''),
            'null insufficient reason':lambda v:v.update(insufficient_reason=None),
        }
        for name,change in changes.items():
            case('reject '+name,lambda change=change:rejects(lambda:validate(variant(change))))
        case('ignore unused invalid grading',lambda:validate(variant(lambda v:v['sentences'][0]['assessments'].append(dict(id='unused',grades=None)))))
        case('accept score boundary 75',lambda:validate(variant(lambda v:assessment(v).update(grades=dict(F=3,U=3,C=3,T=3)))))

        # Real XML-derived monetary values, wrong-account/period/company variants.
        f=repo.financial('005930',2025)
        money_evidence=[dict(e,id=e['id']) for e in evidence]
        for year in (2024,2025):
            row=repo.financial('005930',year)
            money_evidence.append(dict(id='f'+str(year),kind='financial',company='삼성전자',year=year,
                                       report_type='FY',values=row))
        v=valid_answer(money_evidence)
        # Bind prose citation to Samsung's 2025 report so scope is unambiguous.
        e=next(e for e in money_evidence if e['kind']=='filing' and e['company']=='삼성전자' and e['year']==2025 and e['period'].endswith('-12'))
        v['sentences'][0]['refs']=[e['id']]
        def monetary(text):
            value=copy.deepcopy(v);value['sentences'][0]['text']=text
            return validate_money(value,money_evidence)
        check(f['revenue'] is not None,'Actual XML revenue extraction failed')
        case('accept actual XML revenue in won',lambda:monetary(f"삼성전자 2025년 연결 매출액은 {f['revenue']:,}원입니다."))
        def interim_money():
            row=repo.financial('005930',2025,'Q3')
            check(row['revenue'] is not None)
            # This is exactly how generate() emits an interim evidence object:
            # report_type is in values, rather than at the top level.
            inputs=money_evidence+[dict(id='f-q3',kind='financial',company='삼성전자',year=2025,values=row)]
            value=copy.deepcopy(v)
            value['sentences'][0]['text']=f"삼성전자 2025년 3분기 연결 매출액은 {row['revenue']:,}원입니다."
            validate_money(value,inputs)
        case('accept actual interim value in production evidence format',interim_money)
        def actual_quarter():
            direct=repo.financial('005930',2025,'Q3',value_type='quarterly')
            cumulative=repo.financial('005930',2025,'Q3')
            check(direct['revenue'] is not None and direct['revenue']!=cumulative['revenue'])
            rows=ui_project.quarter_rows(repo,dict(code='005930',history=[]),[2025])
            check(rows[2]['revenue']==direct['revenue'])
            check(rows[2]['operatingCashFlow'] is None,'Cumulative cashflow must not become a quarter')
        case('actual XML quarterly value reaches chart, cumulative CF remains missing',actual_quarter)
        for label,text in {
            'account':f"삼성전자 2025년 연결 영업이익은 {f['revenue']:,}원입니다.",
            'year':f"삼성전자 2024년 연결 매출액은 {f['revenue']:,}원입니다.",
            'basis':f"삼성전자 2025년 별도 매출액은 {f['revenue']:,}원입니다.",
            'period':f"삼성전자 2025년 반기 매출액은 {f['revenue']:,}원입니다.",
        }.items():case('reject monetary '+label+' mismatch',lambda text=text:rejects(lambda:monetary(text)))

        def transport(bodies, success, calls, compact=False):
            sent=[];iterator=iter(bodies)
            def send(request,**kwargs):
                sent.append(json.loads(request.data));body=next(iterator)
                return io.BytesIO(body if isinstance(body,bytes) else json.dumps(body).encode())
            before=budget_calls.call_count
            with patch.object(llm,'urlopen',side_effect=send):
                call=lambda:llm.request_report(dict(evidence=evidence),evidence,
                    schema=selection.schema(llm,1,3,evidence),
                    instruction=pipeline.prompt_profiles.active().instruction('insight')+'\n'+selection.INSTRUCTION+'\n'+OUTPUT_NOTE,
                    validator=lambda v,e:validate(v),max_output_tokens=8192)
                if success:call()
                else:rejects(call,RuntimeError)
            check(len(sent)==calls,repr(sent))
            check(budget_calls.call_count-before==calls,'Retry escaped quota reservation')
            if compact:
                repair=json.loads(sent[1]['contents'][0]['parts'][0]['text'])
                check(repair['correction']['compact_output'] is True)
                check(sent[1]['generationConfig']['maxOutputTokens']==8192)
        malformed=variant(lambda v:v['sentences'][0].update(refs=['unknown']))
        transports=[('STOP valid',[envelope(base)],True,1,False),
            ('invalid then corrected',[envelope(malformed),envelope(base)],True,2,False),
            ('invalid twice',[envelope(malformed),envelope(malformed)],False,2,False),
            ('MAX_TOKENS compact repair',[envelope(None,'MAX_TOKENS'),envelope(base)],True,2,True),
            ('MAX_TOKENS twice',[envelope(None,'MAX_TOKENS')]*2,False,2,False),
            ('SAFETY no retry',[envelope(None,'SAFETY')],False,1,False),
            ('no candidates no retry',[dict(candidates=[])],False,1,False),
            ('null candidate corrected',[dict(candidates=[None]),envelope(base)],True,2,False),
            ('null parts corrected',[dict(candidates=[dict(finishReason='STOP',content=dict(parts=None))]),envelope(base)],True,2,False),
            ('HTTP JSON retry',[b'{bad',envelope(base)],True,2,False)]
        for name,bodies,success,calls,compact in transports:
            case(name,lambda bodies=bodies,success=success,calls=calls,compact=compact:transport(bodies,success,calls,compact))

        def occurrence(change=None,success=True):
            actual=[e['text'] for e in evidence[:2]]
            grades=[dict(id='o'+str(i),grades=dict(F=4 if i==0 else 3,U=4 if i==0 else 3,C=4 if i==0 else 3,T=4 if i==0 else 3),
                         suitable=True,irrelevant_content='none',redundancy='none') for i in range(2)]
            value=dict(assessments=grades)
            if change:change(value)
            with patch.object(llm,'urlopen',side_effect=lambda *a,**kw:io.BytesIO(json.dumps(envelope(value)).encode())):
                call=lambda:original_document.choose_occurrence.__wrapped__(evidence[0]['passages'][0]['text'],
                        '실제 원문 후보의 평가', 'II. 사업의 내용','',tuple(actual))
                if success:check(call()==0)
                else:rejects(call,RuntimeError)
        case('duplicate source occurrence selects higher eligible score',occurrence)
        for name,change in {
            'null result':lambda v:v.update(assessments=None),
            'null candidate':lambda v:v['assessments'].__setitem__(0,None),
            'null grades':lambda v:v['assessments'][0].update(grades=None),
            'string suitable':lambda v:v['assessments'][0].update(suitable='true'),
        }.items():case('duplicate occurrence safely rejects '+name,lambda change=change:occurrence(change,False))

        def semantic_limit():
            value=copy.deepcopy(base)
            value['sentences'][0]['text']='공시에 없는 해외 신규 사업 진출을 이미 완료했습니다.'
            # Known limitation: passing IDs/scores cannot independently prove
            # the factual relationship between a generated claim and its quote.
            validate(value)
        case('documented limit: semantic hallucination may pass typed validation',semantic_limit)

        def broken_cache():
            path=work/'bad.json';path.write_text('{broken',encoding='utf-8')
            called=Mock(return_value={'report':copy.deepcopy(base)})
            cached_result(path,validate,called);check(called.call_count==1)
        case('corrupted cache regeneration',broken_cache)
        def build_report():
            report=pipeline.build(sector.id,use_llm=True,force=True)
            check(len(report['companies'])==5 and report['years']==[2023,2024,2025])
            check(len(http_requests)==18,'Expected sector/company + keyword jobs, got '+str(len(http_requests)))
            check(len(prompt_hashes)==3,'Must exercise actual insight/company/keyword prompts')
            check(len(published[(sector.id,'report')]['citations'])>0)
        case('full production report build, 18 jobs, 4 workers',build_report)
        def retain_report():
            if (sector.id,'report') not in published:raise AssertionError('Prior report missing')
            previous=copy.deepcopy(published[(sector.id,'report')])
            with patch.object(llm,'urlopen',side_effect=lambda *a,**kw:io.BytesIO(json.dumps(envelope(None,'SAFETY')).encode())):
                rejects(lambda:pipeline.build(sector.id,use_llm=True,force=True),RuntimeError)
            check(previous==published[(sector.id,'report')],'Failed build replaced existing report')
        case('failed build preserves previously published report',retain_report)

        def view(selected=None):return dashboard.build_view(pipeline.load_report(selected),{})
        stack.enter_context(patch.object(main,'load_view',side_effect=view))
        stack.enter_context(patch.object(ui_project,'load_view',side_effect=view))
        home=dict(indexName='KRX 반도체',entries=['반도체:'+c['stock_code'] for c in fixture['companies']],
                  indexSeries=[],indexReturnPct=None,tradedAt='',cap={},reportAvailable=True)
        stack.enter_context(patch.object(artifacts,'home_summary',return_value=home))
        client=stack.enter_context(TestClient(main.app))
        urls=['/healthz','/','/industry.html','/company.html','/api/sectors','/api/project',
              '/api/project?sector=반도체','/api/project?sector=반도체&code=005930',
              '/api/reports?sector=반도체','/api/financial?sector=반도체&code=005930&year=2025',
              '/api/search?sector=반도체&code=005930&year=2025&q=HBM&top_k=2']
        for url in urls:
            def fetch(url=url):
                value=client.get(url);check(value.status_code==200,url+' '+value.text[:300])
                if url.startswith('/api/project?'):
                    check(value.json()['companies'],'UI silently marked sector unavailable')
                    if url.endswith('code=005930'):
                        c=next(c for c in value.json()['companies'] if c['code']=='005930')
                        quarter=next(r for r in c['financials'] if r['period']=='2025 Q3')
                        check(quarter['metrics']['operating'] is not None,'Actual quarterly XML profit absent from chart')
            case('FastAPI '+url,fetch)
        def source_api():
            report=published[(sector.id,'report')]
            ref=next(iter(report['ai_insights']['2025']['sentences'][0]['source_refs']))
            value=client.get('/api/source',params=dict(ref=ref,sector=sector.id))
            check(value.status_code==200,value.text[:200]);data=value.json()
            check(data['highlight_matched'] is True and '<mark' in data['document_html'])
            check(data['blocks']==[])
        case('citation API exact XML link + highlighted bounded HTML',source_api)
        for url,code in [('/api/search?q=HBM&top_k=0',422),('/api/search?q=HBM&sector=없는섹터',404),
                         ('/api/source?ref=unknown&sector=반도체',404)]:
            case('FastAPI rejects '+url,lambda url=url,code=code:check(client.get(url).status_code==code))
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        summary=dict(environment=dict(system=platform.system(),python=platform.python_version()),
            fixture=dict(documents=len(fixture['documents']),chunks=len(meta),financial_facts=len(fixture['facts']),
                companies=len(fixture['companies']),years=repo.years(),model=fixture['model'],revision=fixture['revision']),
            tests=result.testsRun,failures=[dict(case=str(t),traceback=trace) for t,trace in result.failures],
            errors=[dict(case=t.shortDescription() or str(t),traceback=trace) for t,trace in result.errors],
            simulated_http_calls=len(http_requests),prompt_variants=len(prompt_hashes),
            real_db_connections=0,real_gemini_calls=0,temporary_data_retained=False,
            sample_xml_financial={k:f.get(k) for k in ('year','basis','revenue','operating_income','operating_cashflow','capex')})
        Path(result_path).parent.mkdir(parents=True,exist_ok=True)
        Path(result_path).write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        return result.wasSuccessful()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture',required=True)
    parser.add_argument('--report',required=True)
    args=parser.parse_args()
    sys.exit(0 if run(args.fixture,args.report) else 1)
