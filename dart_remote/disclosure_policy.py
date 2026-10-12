"""Disclosure replacement labels shared by financial extraction and chart UI."""
VERSION = 'selected-xml-v1'
WARNING = ('(추정) 재무정보의 접수번호가 달라 분석 대상으로 선택한 공시 XML의 수치를 사용했습니다. '
           '추정 계산값이 아닌 원문 추출값이며, 별도의 정정공시가 존재하여 최신 수치와 다를 수 있습니다.')

def label(row, previous_receipt):
    return dict(row, estimated=True, estimate_reason='receipt_mismatch',
                previous_receipt=previous_receipt, financial_warning=WARNING)

def annotate(row, field, sources):
    if any(s.get('estimated') for s in sources):
        row.setdefault('estimatedFields', {})[field] = WARNING
