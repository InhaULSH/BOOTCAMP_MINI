import unittest
import xml.etree.ElementTree as ET
from snapdart_data.xml_source import sanitize, extract, compact


class PreprocessTests(unittest.TestCase):
    def test_minimal_repair_and_protected_regions(self):
        source='<DOC><!-- AT&T --><P A="A&B">AT&T &amp; S&P &nbsp; &unknown;</P><P><![CDATA[R&D < 3]]></P></DOC>'
        fixed, repairs, blocks, tables, checks=extract(source)
        self.assertIn('<!-- AT&T -->',fixed)
        self.assertIn('<![CDATA[R&D < 3]]>',fixed)
        self.assertNotIn('&amp;amp;',fixed)
        self.assertEqual(blocks[0]['text'],'AT&T & S&P &unknown;')
        self.assertEqual(blocks[1]['text'],'R&D < 3')
        self.assertTrue(checks['text_coverage_exact'])
        self.assertEqual(len(repairs),5)

    def test_all_text_and_table_structure(self):
        xml='<D>서문<TITLE>II. 사업의 내용</TITLE><P>가격 <B>10%</B> 하락<BR/>설명</P><TABLE><TR><TD ROWSPAN="2">매출</TD><TD><P>100</P></TD></TR><TR><TD>200</TD></TR></TABLE>마지막</D>'
        _,_,blocks,tables,_=extract(xml)
        self.assertEqual(compact(''.join(b['text'] for b in blocks)), '서문II.사업의내용가격10%하락설명매출100200마지막')
        self.assertEqual(len(tables[0]['cells']),3)
        self.assertEqual(tables[0]['cells'][0]['rowspan'],'2')
        self.assertEqual(sum(b['text']=='100' for b in blocks),1)

    def test_fail_closed(self):
        with self.assertRaises(ValueError): extract('<!DOCTYPE D [<!ENTITY secret SYSTEM "file:///a">]><D>&secret;</D>')
        with self.assertRaises(ET.ParseError): extract('<D><P>손상</D>')
        with self.assertRaises(ET.ParseError): extract('<D>문자\x01</D>')

    def test_literal_seminar_phrase(self):
        _,repairs,blocks,_,_=extract('<D><P>- 제11회 <ACI 세미나></P></D>')
        self.assertEqual(blocks[0]['text'],'- 제11회 <ACI 세미나>')
        self.assertEqual(len(repairs),1)




if __name__=='__main__': unittest.main()
