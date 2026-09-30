import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from snapdart.analyze import amount, growth, get_account, business_text, financials
from snapdart.collect import select_filings
from snapdart.llm import validate_summary

class PipelineTests(unittest.TestCase):
    def test_missing_and_negative_values(self):
        self.assertIsNone(amount('-'))
        self.assertEqual(amount('(1,230)'), -1230)
        self.assertEqual(amount('0'), 0)
        self.assertEqual(amount(0), 0)
        self.assertIsNone(growth(100, 0))
        self.assertIsNone(growth(100, None))
        self.assertAlmostEqual(growth(120, 100), 20)

    def test_latest_correction_and_business_year(self):
        rows = [dict(report_nm='사업보고서 (2025.12)', rcept_no='20260310000001'),
                dict(report_nm='[기재정정]사업보고서 (2025.12)', rcept_no='20260810000001'),
                dict(report_nm='사업보고서 (2020.12)', rcept_no='20210310000001'),
                dict(report_nm='분기보고서 (2025.09)', rcept_no='20251110000001')]
        result = select_filings(rows)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[-1]['rcept_no'], '20260810000001')

    def test_accounts_do_not_mix_sections_or_ambiguous_values(self):
        rows = [dict(sj_div='BS', account_id='ifrs-full_Revenue', thstrm_amount='999'),
                dict(sj_div='IS', account_id='ifrs-full_Revenue', thstrm_amount='100')]
        self.assertEqual(get_account(rows, 'revenue'), 100)
        rows.append(dict(sj_div='IS', account_id='ifrs-full_Revenue', thstrm_amount='200'))
        self.assertIsNone(get_account(rows, 'revenue'))
        self.assertIsNone(get_account([], 'capex'))

    def test_business_body_not_contents_or_cross_reference(self):
        source = '<DOC><TITLE>II. 사업의 내용</TITLE><P>목차</P><TITLE>III. 재무에 관한 사항</TITLE><P>II. 사업의 내용을 참조하십시오.</P><TITLE>II. 사업의 내용</TITLE><P>실제 사업 내용과 생산능력 확대 및 투자 계획 설명입니다.</P><TITLE>III. 재무에 관한 사항</TITLE><P>재무제표</P></DOC>'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'report.zip'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('report.xml', source)
            result = business_text(path)
        self.assertIn('실제 사업 내용', result)
        self.assertNotIn('목차', result)
        self.assertNotIn('재무제표', result)

    def test_basis_change_not_reported_as_growth(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for year, basis in [(2024,'OFS'), (2025,'CFS')]:
                (folder / f'financial_{year}.json').write_text(json.dumps(dict(basis=basis, list=[dict(sj_div='IS',account_id='ifrs-full_Revenue',thstrm_amount='100')])) )
            history = financials(folder)
        self.assertIsNone(history[-1]['revenue_growth'])

    def test_llm_malformed_response_rejected(self):
        with self.assertRaises(ValueError):
            validate_summary({'summary':'only summary'})
        value = {k:'입력된 공시 자료를 바탕으로 살펴본 해석입니다.' for k in ('summary','opportunity','risk')}
        self.assertEqual(validate_summary(value), value)

if __name__ == '__main__':
    unittest.main()
