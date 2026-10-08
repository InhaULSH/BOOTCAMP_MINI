"""Original XML storage adapter and safe, table-preserving HTML source viewer."""
from functools import lru_cache
from html import escape
from pathlib import Path
import hashlib
import os
import re
import unicodedata
import xml.etree.ElementTree as ET
from .xml_source import decode, sanitize, reference_text, compact

def normalized(value):
    return ''.join(unicodedata.normalize('NFKC',c) for c in value if not c.isspace())

def read_xml(receipt,chunk_id=None,data_version=None):
    """Read the exact upstream file; never guess the main/attachment by receipt."""
    if not re.fullmatch(r'\d{14}',receipt):raise ValueError('접수번호 형식 오류')
    from . import db
    params={'r':receipt}
    if chunk_id:
        params['chunk']=chunk_id
        sql="""SELECT d.raw_xml,d.sha256,d.byte_size,d.rcept_no,d.data_version,d.document_id,
            m.data_version AS mapping_version,c.data_version AS chunk_version
            FROM chunk_source_documents m JOIN filing_source_documents d USING(document_id)
            JOIN chunk_metadata c ON c.chunk_id=m.chunk_id
            WHERE m.chunk_id=:chunk AND d.rcept_no=:r AND c.rcept_no=:r
            AND d.is_active=1 AND c.is_active=1"""
    else:
        sql='SELECT raw_xml,sha256,byte_size,rcept_no,data_version,document_id FROM filing_source_documents WHERE rcept_no=:r AND is_active=1'
    if data_version:
        params['version']=data_version
        sql+=' AND '+('d.' if chunk_id else '')+'data_version=:version'
    rows=db.rows(sql,params)
    if not rows:raise FileNotFoundError('해당 청크에 연결된 활성 원본 XML이 없습니다.')
    if len(rows)!=1:raise ValueError('원본 파일이 여러 개입니다. 정확한 chunk_id 연결이 필요합니다.')
    row=rows[0]
    if chunk_id and not row['data_version']==row['mapping_version']==row['chunk_version']:raise ValueError('원본·청크·연결 데이터 버전이 다릅니다.')
    raw=bytes(row['raw_xml'])
    if len(raw)!=row['byte_size'] or hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('원본 XML의 크기 또는 SHA-256 검증에 실패했습니다.')
    return raw

@lru_cache(maxsize=8)
def parsed(raw):
    source,_=decode(raw);fixed,repairs=sanitize(source)
    recovery_count=0
    try:root=ET.fromstring(fixed)
    except ET.ParseError:
        from lxml import etree
        parser=etree.XMLParser(encoding='utf-8',recover=True,resolve_entities=False,no_network=True,load_dtd=False,remove_comments=True,remove_pis=True)
        root=etree.fromstring(fixed.encode('utf-8'),parser)
        if root is None or compact(reference_text(fixed))!=compact(''.join(root.itertext())):
            raise ValueError('XML 복구 시 원문 텍스트 보존을 확인하지 못했습니다.') from None
        recovery_count=len(parser.error_log)
    return root,normalized(''.join(root.itertext())),len(repairs)+recovery_count

@lru_cache(maxsize=128)
def choose_occurrence(quote,summary,section,heading,candidates):
    """LLM grades actual occurrences; deterministic scoring selects the best one."""
    import json
    from .citation_selection import INSTRUCTION
    if (Path(__file__).resolve().parents[1]/'snapdart').is_dir():
        from snapdart import llm
    else:
        from cloudapp import llm
    rows=[dict(id='o'+str(i),context=context) for i,context in enumerate(candidates)]
    grade=llm.object_schema({k:dict(type='integer',minimum=0,maximum=4) for k in ('F','U','C','T')})
    item=llm.object_schema(dict(id=dict(type='string',enum=[r['id'] for r in rows]),grades=grade,
        suitable=dict(type='boolean'),irrelevant_content=dict(type='string',enum=['none','some','substantial']),
        redundancy=dict(type='string',enum=['none','some','substantial'])))
    schema=llm.object_schema(dict(assessments=dict(type='array',items=item)))
    def validate(value,allowed):
        assessments=value.get('assessments',[])
        if len(assessments)!=len(rows) or {a.get('id') for a in assessments}!={r['id'] for r in rows}:raise ValueError('모든 실제 원문 위치를 한 번씩 평가하세요.')
        for a in assessments:
            if any(type(a['grades'].get(k)) is not int or not 0<=a['grades'][k]<=4 for k in ('F','U','C','T')):raise ValueError('평가 등급 오류')
            if any(a.get(k) not in ('none','some','substantial') for k in ('irrelevant_content','redundancy')):raise ValueError('감점 등급 오류')
        return value
    context=dict(task='같은 근거 문장의 실제 원문 위치들을 주변 맥락에 따라 평가하세요.',summary=summary,quote=quote,section=section,heading=heading,evidence=rows)
    result=llm.request_report(context,rows,schema=schema,validator=validate,max_output_tokens=4096,temperature=0.0,
        instruction=INSTRUCTION+'\n이번 호출은 요약 생성이 아닌 원문 위치 비교 전용입니다. 모든 oN 후보의 주변 맥락이 요약 및 근거와 부합하는지 동일한 F/U/C/T 및 감점 기준으로 평가하세요. 문장 생성, tN 선택, 최소 근거 개수 조건은 이번 위치 비교에 적용하지 않습니다. 위치가 없으면 만들어내지 마세요.')
    eligible=[];penalty={'none':0,'some':5,'substantial':10}
    for a in result['report']['assessments']:
        g=a['grades'];score=25*(.4*g['F']+.3*g['U']+.2*g['C']+.1*g['T'])-penalty[a['irrelevant_content']]-penalty[a['redundancy']]
        if a['suitable'] and g['F']>=3 and g['C']>=3 and score>=75:eligible.append((score,-int(a['id'][1:])))
    if not eligible:raise ValueError('중복 원문 위치 중 적격 근거를 찾지 못했습니다.')
    return -max(eligible)[1]

def render(raw,quote,section='',heading='',summary=''):
    root,full,repairs=parsed(raw);needle=normalized(quote)
    positions=[m.start() for m in re.finditer(re.escape(needle),full)] if needle else []
    if len(positions)>1:
        # The same business introduction often also appears in company overview
        # and reference sections. Resolve with the DB's original section heading.
        ranges=[];cursor=0
        def locate(element):
            nonlocal cursor
            start=cursor;cursor+=len(normalized(element.text or ''))
            for child in element:
                locate(child);cursor+=len(normalized(child.tail or ''))
            titles=[normalized(''.join(c.itertext())) for c in element if c.tag.upper() in ('TITLE','SUBTITLE')]
            if titles and element.tag.upper().startswith('SECTION'):ranges.append((start,cursor,titles))
        locate(root)
        for label in (section,heading):
            label=normalized(label)
            scoped=[(a,b) for a,b,titles in ranges if label and label in titles]
            if scoped:
                matching=[p for p in positions if any(a<=p and p+len(needle)<=b for a,b in scoped)]
                if matching:positions=matching
    # Never highlight an arbitrary occurrence if the same sentence occurs twice.
    target=(positions[0],positions[0]+len(needle)) if len(positions)==1 else None
    # Locate the narrowest titled section containing the actual citation.
    cursor=0;sections=[];tables=[]
    def inspect(element):
        nonlocal cursor
        start=cursor;cursor+=len(normalized(element.text or ''))
        for child in element:
            inspect(child);cursor+=len(normalized(child.tail or ''))
        titles=[''.join(c.itertext()).strip() for c in element if c.tag.upper() in ('TITLE','SUBTITLE')]
        if titles and element.tag.upper().startswith('SECTION'):sections.append((start,cursor,titles[0]))
        if element.tag.upper()=='TABLE':tables.append((start,cursor))
    inspect(root)
    import bisect
    original=''.join(root.itertext());mapping=[0]
    for char in original:mapping.append(mapping[-1]+len(normalized(char)))
    if len(positions)>1:
        def candidate(p):
            start=bisect.bisect_left(mapping,p);end=bisect.bisect_left(mapping,p+len(needle))
            title=next((t for a,b,t in sorted(sections,key=lambda r:r[1]-r[0]) if a<=p and p+len(needle)<=b),'')
            return title+'\n'+original[max(0,start-500):min(len(original),end+500)]
        candidates=tuple(candidate(p) for p in positions)
        selected=choose_occurrence(quote,summary,section,heading,candidates)
        target=(positions[selected],positions[selected]+len(needle))
    if not target:
        return dict(document_html=None,original_xml_sha256=hashlib.sha256(raw).hexdigest(),
            highlight_matched=False,original_note='근거 위치를 유일하게 확인하지 못해 부분 원문을 표시하지 않았습니다. DART 원문 링크를 이용하세요.',xml_repairs=repairs)
    containers=[r for r in sections if r[0]<=target[0] and target[1]<=r[1]]
    scope=min(containers,key=lambda r:r[1]-r[0]) if containers else (0,len(full),heading or section or '근거 원문')
    # Budget counts original characters including whitespace, not HTML tags.
    left=bisect.bisect_left(mapping,scope[0]);right=bisect.bisect_left(mapping,scope[1])
    hit=bisect.bisect_left(mapping,target[0])
    budget=max(0,2000-len(scope[2]))
    start=max(left,min(hit-budget//2,right-budget));end=min(right,start+budget)
    window=(mapping[start],mapping[end])
    # Include an intersecting table in its entirety, even beyond the budget.
    for a,b in tables:
        if a<window[1] and window[0]<b:window=(min(window[0],a),max(window[1],b))
    offset=0;mark_count=0
    def text(value):
        nonlocal offset,mark_count
        if not value:return ''
        result=[];active=False;buffer=[]
        def flush():
            if buffer:result.append(escape(''.join(buffer)));buffer.clear()
        for char in value:
            length=len(normalized(char));hit=bool(target and length and offset<target[1] and offset+length>target[0])
            # Keep spaces inside a highlighted passage, but not outside its bounds.
            if not length:hit=bool(target and target[0]<offset<target[1])
            if hit!=active:
                flush()
                if active:result.append('</mark>')
                if hit:
                    result.append('<mark'+(' id="evidence-target"' if mark_count==0 else '')+'>');mark_count+=1
                active=hit
            if window[0]<=offset<window[1]:buffer.append(char)
            offset+=length
        flush()
        if active:result.append('</mark>')
        return ''.join(result)
    tags={'TABLE':'table','TR':'tr','TD':'td','TE':'td','TU':'td','TH':'th','THEAD':'thead','TBODY':'tbody','TFOOT':'tfoot','COLGROUP':'colgroup','COL':'col','P':'p','TITLE':'h2','SUBTITLE':'h3','BR':'br','PBR':'br','SPAN':'span','SUP':'sup','SUB':'sub','B':'strong','I':'em'}
    def node(element):
        tag=tags.get(element.tag.upper(),'div');attrs=''
        if tag in ('td','th'):
            for name in ('rowspan','colspan'):
                val=element.get(name.upper(),element.get(name,'1'))
                if val.isdigit() and 1<=int(val)<=1000:attrs+=f' {name}="{int(val)}"'
        start=offset
        content=text(element.text)
        for child in element:content+=node(child)+text(child.tail)
        if offset<=window[0] or start>=window[1]:return ''
        if tag=='br':return '<br>'+content
        if tag=='col':return '<col>'
        return '<'+tag+attrs+'>'+content+'</'+tag+'>'
    body=node(root)
    body='<p class="source-range">'+escape(scope[2]+' · 근거 주변 최대 2,000자, 포함된 표는 전체 표시')+'</p>'+body
    style='''body{font:15px/1.8 "Malgun Gothic",sans-serif;color:#253046;margin:28px;background:#fff}h2,h3{color:#182b49;margin:32px 0 14px}p{margin:10px 0;white-space:pre-wrap}table{border-collapse:collapse;max-width:100%;margin:20px 0;font-size:13px}td,th{border:1px solid #b9c3cd;padding:7px 10px;white-space:pre-wrap}th{background:#f1f4f7}mark{background:#fff0ac;color:inherit;border-radius:3px;padding:2px 0}'''
    html='<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><style>'+style+'</style></head><body>'+body+'</body></html>'
    return dict(document_html=html,original_xml_sha256=hashlib.sha256(raw).hexdigest(),highlight_matched=target is not None,
        original_note='' if target else '동일 문장이 여러 곳에 있거나 XML 원문과 일치하는 위치를 확인하지 못해 강조를 생략했습니다.',xml_repairs=repairs)

def document_view(receipt,quote,section='',heading='',summary='',chunk_id=None,data_version=None):
    try:return render(read_xml(receipt,chunk_id,data_version),quote,section,heading,summary)
    except (FileNotFoundError,ValueError,RuntimeError,ET.ParseError) as error:
        return dict(document_html=None,highlight_matched=False,original_note=str(error))
