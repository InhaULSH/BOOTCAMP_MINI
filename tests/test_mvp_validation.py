import unittest
from unittest.mock import patch
from types import SimpleNamespace
from dart_remote import citation_selection_new2 as selection
from dart_remote.generation import generate_all
from tests import test_new2_financial_evidence as fixtures

class MVPValidationTests(unittest.TestCase):
 def setUp(self):
  self.mode=patch.dict('os.environ',{'INSIGHT_VALIDATION_MODE':'mvp'});self.mode.start();self.addCleanup(self.mode.stop)
  self.f=fixtures.FinancialEvidenceTests();self.f.setUp()
 def value(self):
  return self.f.value('2025년 매출액은 999억원입니다.',[self.f.fact('revenue',2025)['id']])
 def test_numeric_mismatch_is_advisory(self):
  v=self.value();selection.validate(v,self.f.evidence,1,3)
  self.assertEqual(v['validation_mode'],'mvp');self.assertTrue(v['validation_warnings'])
 def test_low_grade_is_allowed_without_inventing_grade(self):
  v=self.value();v['sentences'][1]['assessments'][0]['grades']['F']=1
  selection.validate(v,self.f.evidence,1,3)
  a=v['sentences'][1]['assessments'][0]
  self.assertEqual(a['grades']['F'],1);self.assertIsNone(a['score'])
 def test_missing_assessment_omits_unlocated_prose(self):
  v=self.value();v['sentences'][1]['assessments']=[]
  selection.validate(v,self.f.evidence,1,3)
  self.assertEqual(len(v['sentences']),1)
 def test_unknown_reference_still_rejected(self):
  v=self.value();v['sentences'][0]['refs']=['invented']
  with self.assertRaises(ValueError):selection.validate(v,self.f.evidence,1,3)
 def test_one_failure_does_not_abort_sector(self):
  r=dict(companies=[],years=[2025],citations={},ai_insights={},wordcloud={})
  def bad(*a,**kw):raise RuntimeError('invalid response')
  generate_all(r,SimpleNamespace(),bad)
  self.assertEqual(r['ai_insights']['2025']['sentences'],[])
 def test_strict_mode_can_be_restored(self):
  with patch.dict('os.environ',{'INSIGHT_VALIDATION_MODE':'strict'}),self.assertRaises(ValueError):
   selection.validate(self.value(),self.f.evidence,1,3)
