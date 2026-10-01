"""Preview grounded SQL/vector context, or explicitly request a short LLM answer."""
import argparse,json
from .config import load_env
from snapdart_data.query import Query,retrieve
from snapdart_data import prompts

def main():
    load_env();p=argparse.ArgumentParser()
    p.add_argument('--sector');p.add_argument('--company');p.add_argument('--year',type=int)
    p.add_argument('--report-type',default='FY');p.add_argument('--value-type')
    p.add_argument('--question',required=True);p.add_argument('--intent',choices=['financial','filing','hybrid'],default='hybrid')
    p.add_argument('--llm',action='store_true');args=p.parse_args()
    result=retrieve(Query(args.question,args.sector,args.company,args.year,args.report_type,value_type=args.value_type,intent=args.intent))
    if args.llm:
        from . import llm
        evidence=[dict(id='t'+str(i),year=r['year'],company=r['company'],text=r['text']) for i,r in enumerate(result['retrieved_chunks'],1)]
        for i,row in enumerate(result['financial_data'],1):
            clean={k:v for k,v in row.items() if k!='financial_sources'}
            evidence.append(dict(id='f'+str(i),year=row['year'],values=clean))
        if not evidence:raise RuntimeError('관련 근거가 없습니다.')
        schema=llm.object_schema({'answer':llm.TEXT,'refs':dict(type='array',items=llm.TEXT,minItems=1)})
        ids={r['id'] for r in evidence}
        def validate(v,e):
            if not isinstance(v.get('answer'),str) or not v['answer'].strip() or not isinstance(v.get('refs'),list) or not v['refs'] or not set(v['refs'])<=ids:raise ValueError('답변 근거 오류')
            return v
        context=prompts.context(result['sector'],result['financial_data'],result['retrieved_chunks'],args.company)
        # Only public business text/numbers/provenance enter the request, not vectors or local paths.
        context['retrieved_chunks']=evidence;context['question']=args.question
        result['llm']=llm.request_report(context,evidence,schema=schema,instruction=prompts.COMMON+'\n질문에 답하는 1-2문장의 answer와 실제 근거 ID 배열 refs를 반환합니다.',validator=validate,max_output_tokens=500,temperature=1)['report']
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
