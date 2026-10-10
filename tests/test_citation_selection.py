import copy
import unittest
from unittest.mock import patch
from dart_remote import citation_selection as s
from dart_remote.original_document import render

class CitationSelectionTests(unittest.TestCase):
    def setUp(self):
        text='AI 서버의 수요 증가에 대응하여 생산능력 확대를 계획하고 있습니다.'
        self.evidence=[dict(id='t'+str(i),kind='filing',chunk_id='chunk'+str(i),text=text,passages=[dict(p,id='p'+str(i)) for p in s.passages(text)]) for i in (1,2,3)]
        assessments=[dict(id=e['id'],grades=dict(F=4,U=3,C=4,T=4),suitable=True,reason='직접 근거',irrelevant_content='none',redundancy='none',passage_ids=[e['passages'][0]['id']]) for e in self.evidence]
        self.value=dict(sentences=[dict(text='생산능력 확대가 계획되고 있습니다.',refs=['t1','t2'],assessments=assessments)],insufficient_reason='')

    def test_score_and_minimum_distinct_chunks(self):
        result=s.validate(self.value,self.evidence,1,2)
        self.assertEqual(result['sentences'][0]['assessments'][0]['score'],92.5)
        self.value['sentences'][0]['refs']=['t1']
        self.assertEqual(len(s.validate(self.value,self.evidence,1,2)['sentences']),1)
        self.value['sentences'][0]['refs']=[]
        with self.assertRaisesRegex(ValueError,'최소 1개'):s.validate(self.value,self.evidence,1,2)

    def test_low_direct_support_not_compensated_by_other_scores(self):
        self.value['sentences'][0]['assessments'][0]['grades']['F']=2
        with self.assertRaisesRegex(ValueError,'적격'):s.validate(self.value,self.evidence,1,2)

    def test_fabricated_offset_and_unseen_id_rejected(self):
        bad=copy.deepcopy(self.value);bad['sentences'][0]['assessments'][0]['passage_ids'][0]='invented'
        with self.assertRaisesRegex(ValueError,'원문'):s.validate(bad,self.evidence,1,2)
        bad=copy.deepcopy(self.value);bad['sentences'][0]['refs'][0]='t100'
        with self.assertRaisesRegex(ValueError,'ID'):s.validate(bad,self.evidence,1,2)

    def test_insufficient_evidence_has_explicit_reason(self):
        self.assertEqual(s.validate(dict(sentences=[],insufficient_reason='관련 공시 부족'),[],2,3)['sentences'],[])
        with self.assertRaises(ValueError):s.validate(dict(sentences=[],insufficient_reason=''),[],2,3)

    def test_exact_xml_highlight_tables_and_active_content_removed(self):
        raw='<DOCUMENT><P>AI 수요가 증가합니다.</P><TABLE><TR><TH>기업</TH><TH>매출액</TH></TR><TR><TD ROWSPAN="2">가</TD><TD>100</TD></TR></TABLE><SCRIPT>alert(1)</SCRIPT></DOCUMENT>'.encode()
        value=render(raw,'AI 수요가 증가합니다.')
        self.assertTrue(value['highlight_matched']);self.assertIn('<table>',value['document_html'])
        self.assertIn('rowspan="2"',value['document_html']);self.assertNotIn('<script',value['document_html'])
        self.assertIn('id="evidence-target"',value['document_html'])

    def test_ambiguous_xml_quote_not_arbitrarily_highlighted(self):
        with patch('dart_remote.original_document.choose_occurrence',return_value=1) as choose:
            result=render('<DOC><P>같은 문장</P><P>같은 문장</P></DOC>'.encode(),'같은 문장')
        self.assertTrue(result['highlight_matched']);choose.assert_called_once()
        self.assertEqual(result['document_html'].count('id="evidence-target"'),1)

    def test_repeated_sentence_resolved_by_original_subsection(self):
        raw='<DOC><SECTION-1><TITLE>II. 사업의 내용</TITLE><SECTION-2><TITLE>1. 사업의 개요</TITLE><P>같은 문장</P></SECTION-2><SECTION-2><TITLE>7. 기타 참고사항</TITLE><P>같은 문장</P></SECTION-2></SECTION-1></DOC>'.encode()
        result=render(raw,'같은 문장','II. 사업의 내용','1. 사업의 개요')
        self.assertTrue(result['highlight_matched'])
        self.assertEqual(result['document_html'].count('<mark'),1)

    def test_source_view_limits_to_smallest_titled_section(self):
        raw=('<DOC><SECTION-1><TITLE>사업</TITLE><SECTION-2><TITLE>수요</TITLE><P>수요가 증가합니다.</P></SECTION-2><SECTION-2><TITLE>위험</TITLE><P>별도 위험 설명</P></SECTION-2></SECTION-1></DOC>').encode()
        html=render(raw,'수요가 증가합니다.')['document_html']
        self.assertIn('수요가',html);self.assertNotIn('별도 위험',html)

    def test_long_section_is_bounded_but_intersecting_table_is_complete(self):
        raw=('<DOC><SECTION-1><TITLE>생산</TITLE><P>'+('가'*3000)+'근거문장'+('나'*3000)+'</P></SECTION-1></DOC>').encode()
        html=render(raw,'근거문장')['document_html']
        self.assertLessEqual(html.count('가')+html.count('나')+len('근거문장생산'),2000)
        self.assertIn('id="evidence-target"',html)
        raw=('<DOC><SECTION-1><TITLE>표</TITLE><TABLE><TR><TD>근거문장'+('가'*3000)+'</TD><TD>마지막 셀</TD></TR></TABLE></SECTION-1></DOC>').encode()
        html=render(raw,'근거문장')['document_html']
        self.assertIn('마지막 셀',html);self.assertEqual(html.count('가'),3000)

    def test_prose_gate_rejects_short_and_numeric_citations(self):
        self.assertFalse(s.natural_passage('수요가 늘어납니다.'))
        self.assertFalse(s.natural_passage('당사의 매출액은 전년 대비 25% 증가하였습니다.'))
        self.assertFalse(s.natural_passage('삼성전자 | 매출액 | 100000000000'))
        self.assertTrue(s.natural_passage('AI 서버의 수요 증가에 대응하여 생산능력 확대를 계획하고 있습니다.'))

    def test_duplicate_occurrences_use_llm_grades_and_computed_score(self):
        from dart_remote.original_document import choose_occurrence
        from snapdart import llm
        choose_occurrence.cache_clear()
        def request(context,evidence,**options):
            value=dict(assessments=[dict(id='o'+str(i),grades=dict(F=4,U=u,C=4,T=4),suitable=True,irrelevant_content='none',redundancy='none') for i,u in enumerate((2,4))])
            return dict(report=options['validator'](value,evidence))
        with patch.object(llm,'request_report',side_effect=request):
            self.assertEqual(choose_occurrence('같은 문장','수요 확대 설명','사업','수요',('맥락 가','맥락 나')),1)
        choose_occurrence.cache_clear()

    def test_issuer_angle_bracket_caption_preserves_visible_text(self):
        raw='<DOC><P>연구개발 조직을 설명합니다.</P><IMG-CAPTION ATOC="N"><Elevar Therapeutics, Inc. 연구개발 조직구성></IMG-CAPTION></DOC>'.encode()
        value=render(raw,'연구개발 조직을 설명합니다.')
        self.assertTrue(value['highlight_matched'])
        self.assertIn('&lt;Elevar Therapeutics, Inc. 연구개발 조직구성&gt;',value['document_html'])

    def test_mismatched_tag_recovery_requires_preserved_original_text(self):
        raw='<DOC><P>생산능력 확대를 위해 신규 설비 도입을 계획하고 있습니다.</SPAN></P></DOC>'.encode()
        value=render(raw,'생산능력 확대를 위해 신규 설비 도입을 계획하고 있습니다.')
        self.assertTrue(value['highlight_matched']);self.assertGreater(value['xml_repairs'],0)

    def test_product_names_in_unpaired_angle_brackets_are_text(self):
        raw='<DOC><P>주요 제품인 &lt;철강&gt;과 <STS> 제품의 생산을 확대하고 있습니다.</P></DOC>'.encode()
        value=render(raw,'주요 제품인 <철강>과 <STS> 제품의 생산을 확대하고 있습니다.')
        self.assertTrue(value['highlight_matched'])

    def test_reads_exact_mapped_mysql_file_and_checks_integrity(self):
        import hashlib
        from dart_remote.original_document import read_xml
        raw=b'<DOC>original</DOC>'
        row=dict(raw_xml=raw,sha256=hashlib.sha256(raw).hexdigest(),byte_size=len(raw),data_version='v',mapping_version='v',chunk_version='v')
        with patch('dart_remote.original_document.source_versions',return_value=['v']),patch('dart_remote.db.rows',return_value=[row]) as rows:
            self.assertEqual(read_xml('20260312001230','chunk','v'),raw)
        self.assertIn('chunk_source_documents',rows.call_args.args[0])
        self.assertEqual(rows.call_args.args[1],dict(r='20260312001230',chunk='chunk',version='v',asset_v0='v'))
        for key,val in [('sha256','bad'),('byte_size',1),('mapping_version','wrong')]:
            with patch('dart_remote.original_document.source_versions',return_value=['v']),patch('dart_remote.db.rows',return_value=[dict(row,**{key:val})]),self.assertRaises(ValueError):read_xml('20260312001230','chunk','v')

    def test_receipt_alone_cannot_guess_attachment(self):
        from dart_remote.original_document import read_xml
        with patch('dart_remote.db.rows',return_value=[{},{}]),self.assertRaisesRegex(ValueError,'여러 개'):read_xml('20260312001230')

if __name__=='__main__':unittest.main()
