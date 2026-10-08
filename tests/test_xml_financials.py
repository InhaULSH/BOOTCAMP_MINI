import unittest
from types import SimpleNamespace
from unittest.mock import patch
from dart_remote.repository import Repository
from dart_remote.xml_financials import extract_facts,number,source_view

def xml(unit='백만원',year=2024,basis='연결 ',extra=''):
    return f'''<DOCUMENT><TITLE>2-2. {basis}손익계산서</TITLE>
    <TABLE><TR><TD>제 56 기 {year}.01.01 부터 {year}.12.31 까지</TD></TR>
    <TR><TD>제 55 기 {year-1}.01.01 부터 {year-1}.12.31 까지</TD></TR>
    <TR><TD>(단위: {unit})</TD></TR></TABLE>
    <TABLE><TR><TH>계정</TH><TH>제56기</TH><TH>제55기</TH></TR>
    <TR><TD>매출액 (주29)</TD><TD>1,200</TD><TD>900</TD></TR>
    <TR><TD>영업이익(손실)</TD><TD>(20)</TD><TD>10</TD></TR>{extra}</TABLE></DOCUMENT>'''.encode()

class XMLFinancialTests(unittest.TestCase):
    def parse(self,raw=None,**kwargs):
        args=dict(year=2024,report_type='FY',basis='CFS',value_type='annual',receipt='20250301000001',document_id='doc')
        args.update(kwargs)
        return extract_facts(raw or xml(),**args)

    def test_year_unit_sign_and_cell_provenance(self):
        rows=self.parse();values={r['key']:r['value'] for r in rows}
        self.assertEqual(values,dict(revenue=1200000000,operating_income=-20000000))
        self.assertEqual(rows[0]['column_index'],1)
        self.assertEqual(rows[0]['document_id'],'doc')
        self.assertIn('background:#fff1aa',source_view(rows[0]))

    def test_eps_unit_does_not_change_statement_unit(self):
        rows=self.parse(xml(extra='<TR><TD>주당이익 (단위: 원)</TD><TD>100</TD><TD>90</TD></TR>'))
        self.assertEqual(rows[0]['value'],1200000000)

    def test_statement_caption_under_generic_heading(self):
        raw=xml(basis='').decode().replace('2-2. 손익계산서','4. 재무제표')
        raw=raw.replace('</TITLE>','</TITLE><TABLE><TR><TD>손 익 계 산 서</TD></TR></TABLE>')
        self.assertEqual(self.parse(raw.encode(),basis='OFS')[0]['value'],1200000000)

    def test_wrong_basis_period_and_unknown_unit_not_used(self):
        self.assertEqual(self.parse(basis='OFS'),[])
        self.assertEqual(self.parse(year=2025),[])
        self.assertEqual(self.parse(xml(unit='USD')),[])

    def test_h1_cumulative_and_three_month_values_remain_separate(self):
        raw=b'''<DOCUMENT><TITLE>'''+'연결 손익계산서'.encode()+b'''</TITLE><P>'''+'''제56기 반기 2024.01.01 부터 2024.06.30 까지 (단위: 원)'''.encode()+b'''</P><TABLE><TR><TH>'''+'''계정'''.encode()+b'''</TH><TH COLSPAN="2">'''+'''제56기'''.encode()+b'''</TH></TR><TR><TH/><TH>'''+'''3개월'''.encode()+b'''</TH><TH>'''+'''누적'''.encode()+b'''</TH></TR><TR><TD>'''+'''매출액'''.encode()+b'''</TD><TD>100</TD><TD>250</TD></TR></TABLE></DOCUMENT>'''
        self.assertEqual(self.parse(raw,report_type='H1',value_type='cumulative')[0]['value'],250)
        self.assertEqual(self.parse(raw,report_type='H1',value_type='quarterly')[0]['value'],100)

    def test_json_exists_blocks_xml_even_when_no_mapped_metric(self):
        r=Repository(SimpleNamespace(membership_code='test'))
        with patch.object(r,'facts',return_value=[]),patch.object(r,'json_financial_exists',return_value=True),patch('dart_remote.xml_financials.load') as load:
            f=r.financial('A',2024)
        load.assert_not_called();self.assertIsNone(f['revenue'])

    def test_partial_json_rows_do_not_trigger_fallback(self):
        r=Repository(SimpleNamespace(membership_code='test'))
        row=dict(sj_div='IS',currency='KRW',standard_account_nm='매출액',value=10)
        with patch.object(r,'facts',return_value=[row]),patch('dart_remote.xml_financials.load') as load:
            f=r.financial('A',2024)
        load.assert_not_called();self.assertEqual(f['revenue'],10)

    def test_absent_json_uses_xml_but_conflicting_values_stay_missing(self):
        r=Repository(SimpleNamespace(membership_code='test'))
        rows=self.parse();rows.append(dict(rows[0],value=999))
        with patch.object(r,'facts',return_value=[]),patch.object(r,'json_financial_exists',return_value=False),patch('dart_remote.xml_financials.load',return_value=(rows,'XML')) as load:
            f=r.financial('A',2024)
        load.assert_called_once();self.assertEqual(f['financial_source'],'xml')
        self.assertIsNone(f['revenue']);self.assertIn('충돌',f['financial_note'])

    def test_number_never_estimates_placeholder(self):
        self.assertIsNone(number('-',1));self.assertIsNone(number('100%',1))
