import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from dart_remote import analysis_validation as a,mysql_vectors as v,release_selection as r
from dart_remote.runtime_cache import request_scope

class AnalysisValidationTests(unittest.TestCase):
    def test_success_shared_nested_but_new_analysis_rechecks(self):
        calls=[]
        @a.scope
        def nested():return a.once('check','s',lambda:calls.append(1))
        @a.scope
        def run():nested();nested()
        run();self.assertEqual(len(calls),1)
        run();self.assertEqual(len(calls),2);self.assertFalse(a.active())

    def test_failure_not_cached_and_scope_always_cleared(self):
        @a.scope
        def run():
            for _ in range(2):
                with self.assertRaises(ValueError):a.once('c','s',lambda:(_ for _ in ()).throw(ValueError()))
            self.assertNotIn('c',a._state.get()['checks'])
            raise RuntimeError()
        with self.assertRaises(RuntimeError):run()
        self.assertFalse(a.active())

    def test_workers_share_one_success_and_changes_recheck(self):
        calls=[]
        @a.scope
        def run():
            with ThreadPoolExecutor(max_workers=4) as pool:
                jobs=[a.submit(pool,a.once,'c','s',lambda:calls.append(1)) for _ in range(8)]
                for job in jobs:job.result()
            a.once('c','changed',lambda:calls.append(2))
        run();self.assertEqual(calls,[1,2])

    def test_metadata_reads_bypass_web_sql_cache(self):
        from dart_remote import db
        @request_scope
        @a.scope
        def run():db.rows('SELECT data_version FROM data_versions');db.rows('SELECT data_version FROM data_versions')
        with patch.object(db,'_rows',return_value=[]) as query:
            run();self.assertEqual(query.call_count,2)

    def test_presence_reused_after_30_seconds_but_new_run_is_fresh(self):
        selected=dict(data_version='v',index_version='i')
        @a.scope
        def run():
            r.check_presence(selected,'s')
            with patch.object(r.time,'monotonic',return_value=100000):r.check_presence(selected,'s')
        with patch.object(r.db,'rows',return_value=[{'n':1}]) as query:
            run();self.assertEqual(query.call_count,4)
            run();self.assertEqual(query.call_count,8)

    def test_contract_metadata_checked_each_time_full_join_once_per_signature(self):
        version=dict(data_version='v',index_version='i',validated=1)
        selection=dict(selected=version,registered=version,explicit=False,signature='release')
        meta=dict(model_name=v.MODEL,model_revision=v.REVISION,embedding_dimension=v.DIM,
                  normalize_embeddings=1,searchable_vector_count=1,faiss_ntotal=1,faiss_sha256='old')
        @a.scope
        def run():
            v.contract()
            with patch.object(v.time,'monotonic',return_value=100000):v.contract()
            meta['faiss_sha256']='changed';v.contract()
        with patch.object(r,'resolve',return_value=selection),patch.object(v.db,'rows',side_effect=lambda *args:[dict(meta)]) as query,patch.object(v,'compatible_pairs',return_value=[['v','i']]),patch.object(v,'_check_integrity') as check:
            run();self.assertEqual(query.call_count,3);self.assertEqual(check.call_count,2)
            run();self.assertEqual(check.call_count,3)

    def test_invalid_changed_model_stops_search(self):
        version=dict(data_version='v',index_version='i',validated=1)
        selection=dict(selected=version,registered=version,explicit=False,signature='release')
        meta=dict(model_name='wrong',model_revision=v.REVISION,embedding_dimension=v.DIM,normalize_embeddings=1)
        with patch.object(r,'resolve',return_value=selection),patch.object(v.db,'rows',return_value=[meta]),patch.object(v,'_check_integrity') as check,self.assertRaises(ValueError):
            a.scope(v.contract)()
        check.assert_not_called()

if __name__=='__main__':unittest.main()
