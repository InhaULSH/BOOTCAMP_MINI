import unittest
from unittest.mock import patch
from dart_remote import original_document as od
from dart_remote.partial_document import view,fragments
from dart_remote.capex_validation import resolve
from dart_remote.account_semantics import capex_signature,CASHFLOW_NAMES

class PartialDocumentTests(unittest.TestCase):
    def broken(self):
        return b'<DOCUMENT><P>Valid evidence about growth and demand.</P><TABLE><TR><TE ENG="x"broken="">bad</TE></TR></TABLE></DOCUMENT>'
    def test_unrelated_corruption_does_not_hide_valid_paragraph(self):
        raw=self.broken()
        with self.assertRaises(ValueError):od.parsed(raw)
        result=od.render(raw,'Valid evidence about growth and demand.')
        self.assertTrue(result['highlight_matched']);self.assertTrue(result['highlight_complete'])
        self.assertIn('evidence-target',result['document_html'])
        self.assertNotIn('ENG=',result['document_html'])
        self.assertTrue(result['source_ranges']);self.assertIn('원본 XML',result['document_html'])
    def test_only_safe_rows_of_bad_table_are_shown(self):
        raw=b'<DOCUMENT><TABLE><TR><TE>Reliable statement about business trends.</TE><TE>12</TE></TR><TR><TE ENG="x"broken="">UNVERIFIED_CELL\x01</TE></TR></TABLE></DOCUMENT>'
        result=view(raw,'Reliable statement about business trends.')
        self.assertIn('<table>',result['document_html']);self.assertIn('표에서 검증된 행만',result['document_html'])
        self.assertNotIn('\x01',result['document_html'])
        self.assertEqual(result['source_ranges'][0]['kind'],'TR')
    def test_partial_quote_marks_only_verified_content(self):
        raw=b'<DOCUMENT><P>A substantial verified portion of the original evidence.</P><P x="y"oops="">UNVERIFIED ENDING\x01</P></DOCUMENT>'
        result=view(raw,'A substantial verified portion of the original evidence.UNVERIFIED ENDING')
        self.assertFalse(result['highlight_complete']);self.assertIn('일부만',result['original_note'])
        self.assertNotIn('\x01',result['document_html'])
    def test_intact_table_preserves_rows_and_spans(self):
        raw=b'<DOCUMENT><TABLE><TR><TE COLSPAN="2">Actual table evidence is preserved.</TE></TR><TR><TE>10</TE><TE>20</TE></TR></TABLE><P x="y"oops="">broken</P></DOCUMENT>'
        result=view(raw,'Actual table evidence is preserved.')
        self.assertEqual(result['source_ranges'][0]['kind'],'TABLE')
        self.assertIn('colspan="2"',result['document_html']);self.assertIn('20',result['document_html'])
    def test_valid_text_before_bad_control_character_is_preserved(self):
        raw=b'<DOCUMENT><P>Substantial original passage can be verified.\x01Broken remaining section.</P></DOCUMENT>'
        result=view(raw,'Substantial original passage can be verified.')
        self.assertTrue(result['highlight_complete']);self.assertNotIn('\x01',result['document_html'])
        self.assertEqual(result['source_ranges'][0]['kind'],'TEXT')
    def test_plain_text_survives_broken_local_tag(self):
        raw=b'<DOCUMENT><P x="y"oops="">Substantial plain original evidence can still be verified.</P></DOCUMENT>'
        result=view(raw,'Substantial plain original evidence can still be verified.')
        self.assertTrue(result['highlight_complete'])
        self.assertEqual(result['source_ranges'][0]['kind'],'TEXT')
    def test_external_declarations_and_missing_anchor_rejected(self):
        with self.assertRaises(ValueError):view(b'<!DOCTYPE x><x><P>Evidence</P></x>','Evidence')
        with self.assertRaises(ValueError):view(self.broken(),'Unrelated sentence with entirely distinct terminology')
    def test_active_content_is_never_executed(self):
        raw=b'<DOCUMENT><P onclick="evil()">Verified words<script>alert(1)</script> for business evidence.</P></DOCUMENT>'
        result=view(raw,'Verified wordsalert(1) for business evidence.')
        self.assertNotIn('<script',result['document_html']);self.assertNotIn('onclick',result['document_html'])
    def test_gaps_are_not_joined(self):
        raw=b'<DOCUMENT><P>First verified evidence about business trends.</P><P x="y"oops="">HEIGHT="123"&bad;missing</P><P>Last independently verified paragraph.</P></DOCUMENT>'
        result=view(raw,'First verified evidence about business trends.')
        self.assertNotIn('Last independently',result['document_html'])
    def test_duplicate_locations_use_existing_selector(self):
        raw=b'<DOCUMENT><P>Repeated actual business evidence.</P><P>Repeated actual business evidence.</P></DOCUMENT>'
        with patch.object(od,'choose_occurrence',return_value=1) as choose:
            result=view(raw,'Repeated actual business evidence.')
        choose.assert_called_once();self.assertGreater(result['source_ranges'][1]['start_char'] if len(result['source_ranges'])>1 else result['source_ranges'][0]['start_char'],0)

class AccountSemanticTests(unittest.TestCase):
    def fact(self,t,value,code,name):
        return value,[dict(fs_div='CFS',currency='KRW',rcept_no=t,active_rcept_no=t,
          period_start='2023-01-01',period_end='2023-'+('06-30' if t=='H1' else '09-30'),
          review_required=0,data_version='v',is_calculated=0,capex_method='direct_account',
          source_account_ids=[code],source_account_names=[name])]
    def test_exact_ppe_total_aliases_are_comparable(self):
        entries={('H1','cumulative'):self.fact('H1',268841723598,'-표준계정코드 미사용-','유형자산의 취득'),
          ('Q3','cumulative'):self.fact('Q3',495152029870,'ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities','유형자산의 취득')}
        self.assertEqual(resolve(lambda t,k:entries.get((t,k),(None,[])),2023,'CFS',3)[0],226310306272)
    def test_disposal_and_components_not_equated(self):
        row=self.fact('H1',1,'-표준계정코드 미사용-','유형자산의 처분')[1][0]
        self.assertNotEqual(capex_signature(row),('PPE_ACQUISITION_TOTAL',))
        row['source_account_names']=['유형자산의 취득'];row['capex_method']='component_fallback'
        self.assertNotEqual(capex_signature(row),('PPE_ACQUISITION_TOTAL',))
    def test_flow_before_tax_not_alias(self):
        self.assertIn('영업활동순현금흐름',CASHFLOW_NAMES)
        self.assertNotIn('영업으로부터 창출된 현금흐름',CASHFLOW_NAMES)

class CashflowMappingTests(unittest.TestCase):
    def test_exact_net_flow_and_before_tax_are_separated(self):
        from dart_remote.repository import Repository
        repo=object.__new__(Repository)
        net=dict(sj_div='CF',currency='KRW',standard_account_nm='영업활동순현금흐름',
          account_id='-표준계정코드 미사용-',value=217262743078)
        before=dict(net,standard_account_nm='영업으로부터 창출된 현금흐름',value=245707981285)
        self.assertEqual(repo.metric([net,before],'operating_cashflow')[0],217262743078)
        self.assertEqual(repo.metric([before],'operating_cashflow'),(None,[]))
        wrong=dict(net,account_id='dart_NetCashflowsFromUsedInOperations')
        self.assertEqual(repo.metric([wrong],'operating_cashflow'),(None,[]))
    def test_conflicting_aliases_are_not_silently_selected(self):
        from dart_remote.repository import Repository
        repo=object.__new__(Repository)
        row=dict(sj_div='CF',currency='KRW',standard_account_nm='영업활동순현금흐름',account_id='-표준계정코드 미사용-',value=1)
        with self.assertRaisesRegex(ValueError,'충돌'):repo.metric([row,dict(row,value=2)],'operating_cashflow')
