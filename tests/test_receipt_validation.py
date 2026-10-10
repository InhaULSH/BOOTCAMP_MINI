import unittest
from unittest.mock import patch
from dart_remote.receipt_validation import tagged_facts,prove,validate,reconcile,Unverified

def raw(value='1,200',context='CFY2025dFY_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_ConsolidatedMember',corp='00688996',negated='N',unit='백만원',precision='-6'):
    return f'''<DOCUMENT><DOCUMENT-NAME ACODE="11011">사업보고서</DOCUMENT-NAME><COMPANY-NAME AREGCIK="{corp}">KB금융</COMPANY-NAME><P>(단위: {unit})</P><TABLE><TR><TE>순이자손익</TE><TE ACODE="ifrs-full_InterestRevenueExpense" ACONTEXT="{context}" ADECIMAL="{precision}" ANEGATED="{negated}">{value}</TE></TR></TABLE></DOCUMENT>'''.encode()

def metric(**kw):
    return dict(dict(corp_code='00688996',year=2025,report_type='FY',fs_div='CFS',scope='holding_consolidated',value_type='annual',value=1200000000,unit='KRW',review_status='approved',metric_code='NET_INTEREST_INCOME',source_account_id='ifrs-full_InterestRevenueExpense',source_rcept_no='20260619000667',active_rcept_no='20260324000835'),**kw)

class ReceiptValidationTests(unittest.TestCase):
    def docs(self,payload):return [(payload,dict(document_id='doc',sha256='hash',origin='mysql'))]
    def test_semantic_cell_and_provenance(self):
        identity,rows=tagged_facts(raw())
        self.assertEqual(identity['corp_code'],'00688996');self.assertEqual(rows[0]['value'],1200000000)
        self.assertEqual(rows[0]['table_index'],1)
        with patch('dart_remote.receipt_validation.documents',return_value=self.docs(raw())):
            evidence=prove(metric(),'20260324000835','v')
        self.assertEqual(evidence[0]['rcept_no'],'20260324000835')
    def test_wrong_company_period_basis_unit_or_value_rejected(self):
        for payload in (raw(corp='00000000'),raw(context='PFY2024dFY_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_ConsolidatedMember'),raw(context='CFY2025dFY_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_SeparateMember'),raw(unit='USD'),raw(value='1,201'),raw(precision='-3')):
            with self.subTest(payload=payload),patch('dart_remote.receipt_validation.documents',return_value=self.docs(payload)):
                with self.assertRaises(Unverified):prove(metric(),'20260324000835','v')
    def test_segment_context_not_whole_company(self):
        self.assertEqual(tagged_facts(raw(context='CFY2025dFY_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_ConsolidatedMember_segmentX'))[1],[])
    def test_negated_xbrl_sign_preserved(self):
        self.assertEqual(tagged_facts(raw(value='(1,200)',negated='Y'))[1][0]['value'],1200000000)
    def test_two_receipts_verified_and_upstream_unchanged(self):
        row=metric();original=dict(row)
        active=dict(corp_code=row['corp_code'],year=2025,report_type='FY',rcept_no=row['active_rcept_no'])
        with patch('dart_remote.receipt_validation.documents',return_value=self.docs(raw())):
            result=validate(row,active,'v',[])
        self.assertEqual({e['rcept_no'] for e in result['evidence']},{row['source_rcept_no'],row['active_rcept_no']})
        self.assertEqual(row,original)
    def test_unapproved_or_unknown_scope_not_validated(self):
        for row in (metric(review_status='pending'),metric(scope='unknown')):
            with self.assertRaises(Unverified):validate(row,{},'v',[])
    def test_q4_requires_all_inputs_and_formula(self):
        row=metric(value_type='quarterly',value=300000000,source_values={'FY':1200000000,'Q3':900000000})
        active=dict(corp_code=row['corp_code'],year=2025,report_type='FY',rcept_no=row['active_rcept_no'])
        prior=metric(report_type='Q3',value_type='cumulative',value=900000000,source_rcept_no='20251114000001',active_rcept_no='20251114000001')
        def docs(receipt,v):
            return self.docs(raw(value='900',context='CFY2025dTQA_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_ConsolidatedMember').replace(b'11011',b'11014')) if receipt==prior['source_rcept_no'] else self.docs(raw())
        with patch('dart_remote.receipt_validation.documents',side_effect=docs):
            self.assertEqual(len(validate(row,active,'v',[prior])['evidence']),3)
            with self.assertRaises(Unverified):validate(row,active,'v',[])
            with self.assertRaises(Unverified):validate(dict(row,value=1),active,'v',[prior])
    def test_reconcile_failure_keeps_gaps_and_matching_fast_path(self):
        matching=metric(source_rcept_no='20260324000835')
        with patch('dart_remote.receipt_validation.validate',side_effect=Unverified('mismatch')) as check,patch('dart_remote.receipt_validation.artifacts.put_artifact') as record:
            self.assertEqual(reconcile([matching,metric()],'v'),[matching]);self.assertEqual(check.call_count,1);self.assertEqual(record.call_args.args[2]['status'],'unverified')
    def test_numeric_conflicts_rejected(self):
        payload=raw().replace(b'</DOCUMENT>',raw(value='1,201').split(b'<TABLE>')[1].join([]) if False else b'</DOCUMENT>')
        with patch('dart_remote.receipt_validation.documents',return_value=self.docs(raw())+self.docs(raw(value='1,201'))):
            with self.assertRaises(Unverified):prove(metric(),'20260324000835','v')

    def test_q3_xml_document_code_with_exact_period(self):
        payload=raw(value='900',context='CFY2025dTQA_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_ConsolidatedMember').replace(b'11011',b'11013')
        with patch('dart_remote.receipt_validation.documents',return_value=self.docs(payload)):
            self.assertEqual(prove(metric(report_type='Q3',value_type='cumulative',value=900000000),'20251114000001','v')[0]['value'],900000000)
    def test_integrity_failure_rejects_xml(self):
        from dart_remote.receipt_validation import db_document
        db_document.cache_clear()
        with patch('dart_remote.receipt_validation.db.rows',return_value=[dict(raw_xml=raw())]):
            with self.assertRaises(Unverified):db_document('doc','v','wrong',len(raw()))
    def test_success_audit_retains_both_receipts(self):
        proof=dict(status='verified',evidence=[dict(rcept_no='20260619000667'),dict(rcept_no='20260324000835')])
        with patch('dart_remote.receipt_validation.validate',return_value=proof),patch('dart_remote.receipt_validation.artifacts.put_artifact') as save:
            result=reconcile([metric()],'v')
        self.assertEqual(result[0]['source_rcept_no'],'20260619000667')
        self.assertEqual(result[0]['receipt_validation'],proof)
        self.assertEqual(save.call_args.args[1],'proof')
