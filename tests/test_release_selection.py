import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from dart_remote import release_selection as r,mysql_vectors as v
from dart_remote.repository import Repository

def version(name,index=None):
    return dict(data_version=name,index_version=index or name+'-index',validated=1,
                vector_sqlite_sha256='a'*64,faiss_sha256='b'*64,financial_sqlite_sha256='c'*64)

class ReleaseSelectionTests(unittest.TestCase):
    def setUp(self):
        r._presence.clear()
        self.env=patch.dict(os.environ,{'SERVICE_DATA_VERSION':''});self.env.start();self.addCleanup(self.env.stop)
    def query(self,sql,p=None):
        if 'is_current=1' in sql:return [version('registered')]
        if 'data_versions' in sql:return [version('physical')]
        return [{'n':1}]
    def test_default_stays_strict_current(self):
        with patch.object(r.db,'rows',side_effect=self.query) as read:
            selected=r.resolve()
        self.assertFalse(selected['explicit']);self.assertEqual(selected['selected']['data_version'],'registered')
        self.assertEqual(read.call_count,1)
    def test_pin_checks_presence_and_both_asset_hashes(self):
        with patch.dict(os.environ,{'SERVICE_DATA_VERSION':'physical'}),patch.object(r.db,'rows',side_effect=self.query) as read:
            selected=r.resolve()
        self.assertEqual(selected['selected']['data_version'],'physical');self.assertEqual(selected['registered']['data_version'],'registered')
        self.assertEqual(read.call_count,6);self.assertTrue(all(c.args[0].startswith('SELECT ') for c in read.call_args_list))
        self.assertEqual(read.call_args_list[-1].args[1]['i'],'physical-index')
    def test_no_fallback_on_missing_or_ambiguous_release(self):
        for releases in ([],[version('physical'),version('duplicate')]):
            with patch.dict(os.environ,{'SERVICE_DATA_VERSION':'physical'}),patch.object(r.db,'rows',side_effect=[[version('registered')],releases]):
                with self.assertRaises(ValueError):r.resolve()
        with patch.object(r.db,'rows',return_value=[version('a'),version('b')]):
            with self.assertRaises(RuntimeError):r.resolve()
    def test_hash_change_or_missing_table_rejected(self):
        for hashes in ({'faiss_sha256':'d'*64},{'vector_sqlite_sha256':None},{'financial_sqlite_sha256':'d'*64}):
            with patch.dict(os.environ,{'SERVICE_DATA_VERSION':'physical'}),patch.object(r.db,'rows',side_effect=[[version('registered')],[dict(version('physical'),**hashes)]]):
                with self.assertRaisesRegex(ValueError,'해시'):r.resolve()
        with patch.dict(os.environ,{'SERVICE_DATA_VERSION':'physical'}),patch.object(r.db,'rows',side_effect=[[version('registered')],[version('physical')],[{'n':1}],[{'n':1}],[{'n':0}]]):
            with self.assertRaisesRegex(ValueError,'coverage'):r.resolve()
    def test_cached_presence_never_hides_registration_changes(self):
        with patch.dict(os.environ,{'SERVICE_DATA_VERSION':'physical'}),patch.object(r.db,'rows',side_effect=self.query) as read:
            first=r.resolve();second=r.resolve();self.assertEqual(read.call_count,8)
        def changed(sql,p=None):return [version('registered-next')] if 'is_current=1' in sql else self.query(sql,p)
        with patch.dict(os.environ,{'SERVICE_DATA_VERSION':'physical'}),patch.object(r.db,'rows',side_effect=changed) as read:
            third=r.resolve();self.assertEqual(read.call_count,6)
        self.assertEqual(first['signature'],second['signature']);self.assertNotEqual(first['signature'],third['signature'])
    def test_explicit_index_metadata_without_current_flag_is_checked(self):
        selection=dict(registered=version('registered'),selected=version('physical'),explicit=True,signature='s')
        meta=dict(model_name=v.MODEL,model_revision=v.REVISION,embedding_dimension=v.DIM,normalize_embeddings=1,
                  searchable_vector_count=1,faiss_ntotal=1,sqlite_sha256='a'*64,faiss_sha256='b'*64)
        with patch('dart_remote.release_selection.resolve',return_value=selection),patch.object(v.db,'rows',return_value=[meta]) as read,patch.object(v,'compatible_pairs',return_value=[['physical','physical-index']]),patch.object(v,'_check_integrity') as check,patch.object(v,'_integrity',None):
            key=v.contract()
        self.assertNotIn('is_current=1',read.call_args.args[0]);check.assert_called_once()
        self.assertEqual(key['data_version'],'physical');self.assertEqual(key['registered_data_version'],'registered')
    def test_registered_change_invalidates_report_fingerprint(self):
        sector=SimpleNamespace(data_version='physical:members',index_version='i',membership_code='m',
            topics=(),terms=(),profiles={},companies_order=(),registered_data_version='registered',release_selection_signature='first')
        repo=Repository(sector);first=repo.fingerprint();sector.registered_data_version='registered-next'
        self.assertNotEqual(first,repo.fingerprint());self.assertEqual(repo.release_info()['query_data_version'],'physical')

    def test_financial_document_id_patch_has_narrow_content_contract(self):
        registered=dict(version('registered'),created_at='now',financial_sqlite_sha256='d'*64)
        run=dict(table_name='financial_metric_values_document_id',status='success',rows_inserted=0,
                 rows_deactivated=0,rows_updated=120,rows_source=120,finished_at='now')
        def replies(change=None):
            return [[{'data_version':'physical'}],[dict(run,**(change or {}))],[{'n':120,'bad':0}]]
        with patch.object(r.db,'rows',side_effect=replies()):
            self.assertEqual(r.financial_equivalence(registered,version('physical')),'document-id-only-patch')
        for change in ({'table_name':'financial_facts'},{'rows_inserted':1},{'rows_updated':119},{'status':'failed'}):
            with patch.object(r.db,'rows',side_effect=replies(change)),self.assertRaises(ValueError):
                r.financial_equivalence(registered,version('physical'))
        with patch.object(r.db,'rows',side_effect=[[{'data_version':'physical'}],[run],[{'n':120,'bad':1}]]),self.assertRaises(ValueError):
            r.financial_equivalence(registered,version('physical'))

if __name__=='__main__':unittest.main()
