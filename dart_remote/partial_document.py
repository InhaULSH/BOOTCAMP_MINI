"""Source viewer fallback: independently verify complete local XML fragments.

Financial extraction still uses original_document.parsed and its full-document
preservation check. This module never returns a recovered tree to that path.
"""
from bisect import bisect_right
from difflib import SequenceMatcher
from functools import lru_cache
from html import escape
import hashlib
import re
import xml.etree.ElementTree as ET
from .xml_source import LEX,decode,sanitize,reference_text,compact

VERSION='local-source-v1'

@lru_cache(maxsize=4)
def fragments(raw):
    source,_=decode(raw)
    # Never interpret DTDs or external entities, even outside the selected view.
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b',source,re.I):
        raise ValueError('외부 선언이 있는 XML은 부분 원문으로 표시하지 않습니다.')
    stacks={t:[] for t in ('TABLE','TR','P','TITLE','SUBTITLE')};spans=[];text_runs=[];position=0
    for m in LEX.finditer(source):
        if m.start()>position:text_runs.append((position,m.start()))
        position=m.end()
        token=m.group();tag=re.match(r'<(/?)([A-Za-z_][\w.:-]*)',token)
        if not tag or tag[2] not in stacks:continue
        name=tag[2]
        if tag[1]:
            if stacks[name]:spans.append((stacks[name].pop(),m.end(),name))
        elif not token.rstrip().endswith('/>'):stacks[name].append(m.start())
    if position<len(source):text_runs.append((position,len(source)))
    verified=[];newlines=[m.start() for m in re.finditer('\n',source)]
    # Validate larger units first; do not duplicate cells from an intact table.
    covered=[]
    for a,b,tag in sorted(spans,key=lambda x:(0 if x[2]=='TABLE' else 1 if x[2]=='TR' else 2,x[0])):
        if any(left<=a and b<=right for left,right in covered):continue
        try:
            fixed,repairs=sanitize(source[a:b]);node=ET.fromstring(fixed)
            text=''.join(node.itertext())
            if compact(reference_text(fixed))!=compact(text):continue
        except (ValueError,ET.ParseError):continue
        if not compact(text):continue
        covered.append((a,b))
        verified.append(dict(start=a,end=b,tag=tag,xml=fixed,text=text,
            line_start=bisect_right(newlines,a)+1,line_end=bisect_right(newlines,b-1)+1,
            repairs=len(repairs)))
    # If a local block is malformed, retain independent plain character-data runs.
    # Reject markup-like or attribute-like leftovers; never recover their syntax.
    runs=[]
    for left,right in text_runs:
        start=left
        for bad in re.finditer(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]',source[left:right]):
            end=left+bad.start()
            if start<end:runs.append((start,end))
            start=left+bad.end()
        if start<right:runs.append((start,right))
    for a,b in runs:
        if any(left<=a and b<=right for left,right in covered):continue
        text=source[a:b]
        if '<' in text or '>' in text or re.search(r'[A-Z_]+\s*=',text):continue
        try:
            fixed,repairs=sanitize('<P>'+text+'</P>');node=ET.fromstring(fixed)
            visible=''.join(node.itertext())
            if compact(reference_text(fixed))!=compact(visible) or not compact(visible):continue
        except (ValueError,ET.ParseError):continue
        verified.append(dict(start=a,end=b,tag='TEXT',xml=fixed,text=visible,
            line_start=bisect_right(newlines,a)+1,line_end=bisect_right(newlines,b-1)+1,repairs=len(repairs)))
    return tuple(sorted(verified,key=lambda x:x['start']))


def view(raw,quote,section='',heading='',summary=''):
    from .original_document import normalized,choose_occurrence
    units=fragments(raw);needle=normalized(quote)
    if not needle:raise ValueError('표시할 근거 문장이 없습니다.')
    matches=[]
    # Exact matches are preferred; partial matches never imply the full quote is verified.
    for i,u in enumerate(units):
        text=normalized(u['text'])
        for m in re.finditer(re.escape(needle),text):matches.append((i,m.start(),len(needle),True))
    if not matches:
        minimum=min(len(needle),max(20,int(len(needle)*.25)))
        if len(needle)<20:raise ValueError('부분 근거를 확인하기에는 문장이 너무 짧습니다.')
        for i,u in enumerate(units):
            text=normalized(u['text'])
            # Only literal, substantial shared text can anchor a partial excerpt.
            match=SequenceMatcher(None,needle,text,autojunk=False).find_longest_match()
            if match.size>=minimum:matches.append((i,match.b,match.size,False))
        if matches:
            largest=max(x[2] for x in matches);matches=[x for x in matches if x[2]==largest]
    if not matches:raise ValueError('정상적으로 읽을 수 있는 구간에서 근거 위치를 확인하지 못했습니다. DART 원문 링크를 이용하세요.')
    if len(matches)>1:
        selected=choose_occurrence(quote,summary,section,heading,
            tuple('XML '+str(units[i]['line_start'])+'행: '+units[i]['text'] for i,_,_,_ in matches))
    else:selected=0
    index,start,length,exact=matches[selected];hit=units[index]
    chosen=[hit];budget=len(hit['text'])
    # Neighbour context is allowed only when the intervening source consists of markup/whitespace.
    # Missing or corrupt text is never silently joined to create a contiguous passage.
    source,_=decode(raw)
    for direction in (-1,1):
        position=index+direction
        while 0<=position<len(units) and budget<2000:
            candidate=units[position];boundary=chosen[0] if direction<0 else chosen[-1]
            gap=source[candidate['end']:boundary['start']] if direction<0 else source[boundary['end']:candidate['start']]
            try:gap_text=compact(reference_text(sanitize(gap)[0]))
            except ValueError:break
            if gap_text:break
            if budget+len(candidate['text'])>2000:break
            if direction<0:chosen.insert(0,candidate)
            else:chosen.append(candidate)
            budget+=len(candidate['text']);position+=direction
    tags={'TABLE':'table','TR':'tr','TD':'td','TH':'th','TE':'td','TU':'td','P':'p',
          'TITLE':'h3','SUBTITLE':'h3','BR':'br','PBR':'br','SUP':'sup','SUB':'sub','B':'strong','I':'em'}
    def unit_html(unit):
        cursor=0;marked=False
        target=(start,start+length) if unit is hit else None
        def text(value):
            nonlocal cursor,marked
            out=[];active=False
            for char in value or '':
                size=len(normalized(char));inside=target and (cursor<target[1] and cursor+size>target[0] if size else target[0]<cursor<target[1])
                if bool(inside)!=active:
                    if active:out.append('</mark>')
                    if inside:out.append('<mark'+(' id="evidence-target"' if not marked else '')+'>');marked=True
                    active=bool(inside)
                out.append(escape(char));cursor+=size
            if active:out.append('</mark>')
            return ''.join(out)
        def render(node):
            tag=tags.get(node.tag.upper(),'div');attrs=''
            if tag in ('td','th'):
                for key in ('rowspan','colspan'):
                    value=node.get(key.upper(),node.get(key,'1'))
                    if value.isdigit() and 1<=int(value)<=1000:attrs+=' '+key+'="'+value+'"'
            content=text(node.text)
            for child in node:content+=render(child)+text(child.tail)
            return '<br>'+content if tag=='br' else '<'+tag+attrs+'>'+content+'</'+tag+'>'
        html=render(ET.fromstring(unit['xml']))
        if unit['tag']=='TR':html='<table>'+html+'</table>'
        label=f"原XML {unit['line_start']}-{unit['line_end']}행".replace('原XML','원본 XML')
        if unit['tag']=='TR':label+=' · 표에서 검증된 행만 표시'
        return '<p class="source-range">'+escape(label)+'</p>'+html
    heading_text=' · '.join(x for x in (section,heading) if x) or '검증된 원문 구간'
    note='문서 전체 중 검증된 구간만 표시합니다. 생략된 내용과 공시 전문은 DART 원문 링크에서 확인하세요.'
    if not exact:note+=' 근거 문장의 일부만 위치가 확인되어 해당 부분만 강조했습니다.'
    body='<h2>'+escape(heading_text)+'</h2><p>'+escape(note)+'</p>'+''.join(unit_html(u) for u in chosen)
    html="""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><style>body{font:15px/1.8 sans-serif;margin:24px}table{border-collapse:collapse}td,th{border:1px solid #bbc;padding:7px}mark{background:#e3edf9}p{white-space:pre-wrap}</style></head><body>"""+body+'</body></html>'
    return dict(document_html=html,highlight_matched=True,highlight_complete=exact,
        partial_document=True,original_note=note,original_xml_sha256=hashlib.sha256(raw).hexdigest(),
        source_ranges=[dict(start_char=u['start'],end_char=u['end'],line_start=u['line_start'],line_end=u['line_end'],kind=u['tag']) for u in chosen],
        xml_repairs=sum(u['repairs'] for u in chosen))
