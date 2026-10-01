"""Loss-audited XML text extraction, number occurrences and non-overlapping chunks.

Only standard-library dependencies. Originals are never rewritten. Number rows
are source occurrences, NOT automatically verified financial/accounting facts.
"""
from bisect import bisect_right
from collections import Counter
import hashlib
from html.entities import html5
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


# Tokenize markup with quoted attribute values intact. CDATA and comments must
# never undergo ampersand escaping. Unknown '<' remains text and is escaped.
LEX = re.compile(r'<!--[\s\S]*?-->|<!\[CDATA\[[\s\S]*?\]\]>|<\?[\s\S]*?\?>|</?[A-Za-z_][\w.:-]*(?:[^<>\"\']|\"[^\"]*\"|\'[^\']*\')*>')
ENTITY = re.compile(r'&(?:#[xX][0-9a-fA-F]+;|#\d+;|[A-Za-z][A-Za-z0-9]*;)?')
BUILTIN = {'amp': '&', 'lt': '<', 'gt': '>', 'quot': '"', 'apos': "'"}
BLOCK = {'P', 'TITLE', 'SUBTITLE', 'TD', 'TH', 'TE', 'TU', 'TR'}
CELL = {'TD', 'TH', 'TE', 'TU'}
NUMBER = re.compile(r'(?<![\d,])[-+−△▲]?\d+(?:,\d{3})*(?:\.\d+)?')
UNIT = re.compile(r'^\s*(%|퍼센트|조\s*원|억\s*원|백만\s*원|천\s*원|원|달러|천주|주|만\s*개|개|대|톤|명|배|년|월|일)')


def compact(text):
    return re.sub(r'\s+', '', text)


def plain(text):
    return re.sub(r'\s+', ' ', text).strip()


def jsonline(stream, obj):
    stream.write(json.dumps(obj, ensure_ascii=False) + '\n')


def sanitize(source):
    """Return minimally repaired XML and a source-offset change ledger.

    DTDs/entities are not loaded; ambiguous declarations and invalid XML control
    characters are quarantined rather than silently deleted.
    """
    changes = []
    newlines = [m.start() for m in re.finditer('\n', source)]

    def log(offset, old, new, reason):
        changes.append(dict(offset=offset, line=bisect_right(newlines, offset)+1,
                            before=old, after=new, reason=reason))

    def replace_text(text, base, attribute=False):
        def entity(m):
            raw = m.group()
            name = raw[1:-1]
            if raw.endswith(';') and (name in BUILTIN or name.startswith('#')):
                return raw  # Invalid codepoints are rejected by the strict parser.
            decoded = html5.get(name + ';') if raw.endswith(';') else None
            if decoded is not None:
                value = ''.join('&#%d;' % ord(c) for c in decoded)
                reason = 'HTML named character reference to XML numeric reference'
            else:
                value = '&amp;' + raw[1:]
                reason = 'literal ampersand escaped'
            log(base+m.start(), raw, value, reason)
            return value
        # Apply substitutions together so ledger offsets always refer to source.
        pattern = re.compile(ENTITY.pattern + r'|<')
        def sub(m):
            if m.group() == '<':
                log(base+m.start(), '<', '&lt;', 'literal less-than escaped')
                return '&lt;'
            return entity(m)
        return pattern.sub(sub, text)

    parts = []; pos = 0
    for match in LEX.finditer(source):
        gap = source[pos:match.start()]
        if '<!' in gap:
            raise ValueError('Unsupported declaration/DTD or unclosed comment/CDATA; manual review required')
        parts.append(replace_text(gap, pos))
        token = match.group()
        if token.startswith(('<!--', '<![CDATA[', '<?')):
            parts.append(token)
        elif re.fullmatch(r'<[A-Za-z]+\s+[가-힣][가-힣\s]*>', token):
            # Observed issuer text: "제11회 <ACI 세미나>". This cannot be
            # a valid attribute list; preserve the complete visible phrase.
            value='&lt;'+token[1:-1]+'&gt;'
            log(match.start(),token,value,'literal Korean angle-bracket phrase escaped')
            parts.append(value)
        else:
            # Repair attributes only; leave tag names/delimiters untouched.
            parts.append(re.sub(r'\"[^\"]*\"|\'[^\']*\'',
                                lambda m: m.group()[0] + replace_text(m.group()[1:-1], match.start()+m.start()+1, True) + m.group()[-1], token))
        pos = match.end()
    if '<!' in source[pos:]:
        raise ValueError('Unclosed declaration')
    parts.append(replace_text(source[pos:], pos))
    return ''.join(parts), changes


def reference_text(source):
    """Independent lexical character-data stream (no tree construction)."""
    def unescape(text):
        def sub(m):
            value = m.group()[1:-1]
            if value.startswith(('#x', '#X')): return chr(int(value[2:], 16))
            if value.startswith('#'): return chr(int(value[1:]))
            return BUILTIN.get(value, m.group())
        return ENTITY.sub(sub, text)
    pieces = []; pos = 0
    for m in LEX.finditer(source):
        pieces.append(unescape(source[pos:m.start()]))
        if m.group().startswith('<![CDATA['): pieces.append(m.group()[9:-3])
        pos = m.end()
    pieces.append(unescape(source[pos:]))
    return ''.join(pieces)


def extract(source):
    fixed, repairs = sanitize(source)
    # ElementTree never loads external DTDs; sanitizer rejects declarations.
    root = ET.fromstring(fixed)
    reference = compact(reference_text(fixed))
    if reference != compact(''.join(root.itertext())):
        raise ValueError('Lexical text and parsed tree disagree')
    paths = {}; tables = {}; cells = {}; headings = {}; serial = 0

    def index(node, path, table=None, row=None):
        nonlocal serial
        paths[node] = path
        tag = node.tag.upper()
        if tag == 'TABLE':
            serial += 1; table = str(serial); row = None
            tables[table] = dict(table_id=table, path=path, cells=[])
        if tag == 'TR' and table:
            row = path
        if tag in CELL and table:
            info = dict(table_id=table, row_path=row or '', cell_path=path,
                        rowspan=node.get('ROWSPAN', node.get('rowspan', '1')),
                        colspan=node.get('COLSPAN', node.get('colspan', '1')),
                        text=plain(''.join(node.itertext())))
            cells[node] = info; tables[table]['cells'].append(info)
        counts = Counter()
        for child in node:
            counts[child.tag] += 1
            index(child, path+'/'+child.tag+f'[{counts[child.tag]}]', table, row)
    index(root, '/'+root.tag+'[1]')
    row_groups = {}
    for info in cells.values():
        row_groups.setdefault((info['table_id'],info['row_path']),[]).append(info)
    for group in row_groups.values():
        for ordinal,info in enumerate(group,1):
            info['source_cell_order']=ordinal
            info['row_text']=' | '.join(c['text'] for c in group)
    blocks = []; active = None; parts = []; section = ''; heading = ''

    def flush():
        nonlocal parts
        text = plain(''.join(parts)); parts = []
        if text:
            blocks.append(dict(**active, text=text))

    def emit(text, owner, cell):
        nonlocal active
        if not text: return
        key = paths[owner]
        if active is None or active['xml_path'] != key:
            if active is not None: flush()
            active = dict(xml_path=key, kind='cell' if cell else ('heading' if owner.tag.upper() in {'TITLE','SUBTITLE'} else 'paragraph'),
                          section=section, heading=heading,
                          table_id=cell['table_id'] if cell else '',
                          row_path=cell['row_path'] if cell else '',
                          cell_path=cell['cell_path'] if cell else '',
                          table_row_text=cell['row_text'] if cell else '',
                          table_cell_order=cell['source_cell_order'] if cell else '')
        parts.append(text)

    def walk(node, owner=None, cell=None):
        nonlocal section, heading
        tag = node.tag.upper()
        if tag in {'TITLE', 'SUBTITLE'}:
            heading = plain(''.join(node.itertext()))
            if re.match(r'^[IVX]+\s*\.', heading): section = heading
        cell = cells.get(node, cell)
        if tag in BLOCK or owner is None: owner = node
        if tag in {'BR', 'PBR'}: emit(' ', owner, cell)
        emit(node.text, owner, cell)
        for child in node:
            walk(child, owner, cell)
            emit(child.tail, owner, cell)
    walk(root)
    if active is not None: flush()
    if reference != compact(''.join(b['text'] for b in blocks)):
        raise ValueError('Block extraction lost or reordered character data')
    return fixed, repairs, blocks, list(tables.values()), dict(
        text_characters=len(reference), text_coverage_exact=True,
        xml_elements=sum(1 for _ in root.iter()),
        image_elements=[dict(tag=n.tag, attributes=n.attrib) for n in root.iter()
                        if n.tag.upper() in {'IMAGE','IMG','PICTURE'}])


def decode(raw):
    for encoding in ('utf-8-sig','euc-kr'):
        try:return raw.decode(encoding),encoding
        except UnicodeDecodeError:pass
    raise ValueError('Unsupported encoding; refusing silent text loss')

WORDS = re.compile(r'[가-힣A-Za-z]')

def table_rows(table):
    """Resolve span coordinates without inventing period/account semantics."""
    groups={}
    for cell in table['cells']: groups.setdefault(cell['row_path'],[]).append(cell)
    occupied={}; result=[]
    for row_index,(path,cells) in enumerate(groups.items()):
        col=0; items=[]
        for cell in cells:
            while (row_index,col) in occupied: col+=1
            rs=int(cell['rowspan']);cs=int(cell['colspan'])
            if not (1<=rs<=1000 and 1<=cs<=1000): raise ValueError('Invalid table span')
            item=dict(cell_path=cell['cell_path'],text=cell['text'],row=row_index,
                      column=col,rowspan=rs,colspan=cs)
            for r in range(row_index,row_index+rs):
                for c in range(col,col+cs):
                    if (r,c) in occupied: raise ValueError('Overlapping table spans')
                    occupied[r,c]=item
            items.append(item);col+=cs
        result.append(dict(row_index=row_index,row_path=path,cells=items))
    # Retain carried labels separately; never manufacture duplicated values.
    for row in result:
        row['carried_labels']=list(dict.fromkeys(v['text'] for (r,c),v in occupied.items()
              if r==row['row_index'] and v['row']<r and WORDS.search(v['text'])))
    return result
