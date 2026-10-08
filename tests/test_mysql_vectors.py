import unittest
from unittest.mock import patch
import numpy as np
from dart_remote import mysql_vectors as v

class MySQLVectorTests(unittest.TestCase):
    def key(self):return dict(count=2,data_version='v',index_version='i')
    def rows(self):return [dict(chunk_id=str(i),vector_id=i,data_version='v',index_version='i',embedding_model=v.MODEL,model_revision=v.REVISION,embedding_dimension=v.DIM,content_hash=str(i),corp_name='기업',year=2024) for i in range(2)]
    def matrix(self):
        m=np.zeros((2,v.DIM),dtype=np.float32);m[0,0]=1;m[1,1]=1;return m
    def test_exact_numpy_no_keyword_gate(self):
        q=np.zeros(v.DIM,dtype=np.float32);q[1]=1
        self.assertEqual(v.top_indices(self.matrix(),q,5,'numpy'),[(1,1.0),(0,0.0)])
    def test_invalid_norm_nan_duplicate(self):
        v.validate(self.rows(),self.matrix(),self.key())
        for matrix in [self.matrix()*2,np.full((2,v.DIM),np.nan)]:
            with self.assertRaises(ValueError):v.validate(self.rows(),matrix,self.key())
        with self.assertRaises(ValueError):v.validate([self.rows()[0]]*2,self.matrix(),self.key())
    def test_model_contract_and_sync_guard(self):
        version=dict(data_version='v',index_version='i',validated=1)
        meta=dict(model_name=v.MODEL,model_revision=v.REVISION,embedding_dimension=v.DIM,normalize_embeddings=1,searchable_vector_count=2,faiss_ntotal=2,faiss_sha256='h')
        with patch.object(v,'_integrity',None),patch.object(v.db,'rows',side_effect=[[version],[meta],[dict(n=2,unique_n=2,bad=0)]]):self.assertEqual(v.contract()['count'],2)
        for check in [dict(n=2,unique_n=1,bad=0),dict(n=2,unique_n=2,bad=1)]:
            with patch.object(v,'_integrity',None),patch.object(v.db,'rows',side_effect=[[version],[meta],[check]]):
                with self.assertRaises(ValueError):v.contract()
        with patch.object(v.db,'rows',return_value=[dict(version,validated=0)]):
            with self.assertRaises(RuntimeError):v.contract()
    def test_changed_version_stops_search(self):
        with patch.object(v,'contract',return_value=self.key()):
            with self.assertRaises(RuntimeError):v.rank('q',[],5,'old','numpy')
    def test_model_verification_failure_is_fatal(self):
        with patch.object(v,'_verified',None),patch.object(v.db,'rows',return_value=[dict(chunk_id='0',section_name='s',subsection_name='',chunk_text='t'),dict(chunk_id='1',section_name='s',subsection_name='',chunk_text='t')]),patch.object(v,'encode',return_value=np.zeros((2,v.DIM),dtype=np.float32)):
            with self.assertRaises(ValueError):v.verify_model(self.key(),self.rows(),self.matrix())
    def test_candidate_version_and_no_threshold(self):
        key=self.key(); rows=self.rows(); m=self.matrix()
        with patch.object(v,'contract',return_value=key),patch.object(v,'snapshot',return_value=(rows,m)),patch.object(v,'verify_model'),patch.object(v,'encode',return_value=m[:1]),patch.object(v,'_queries',{}),patch.object(v,'model') as model:
            model.return_value.tokenizer.return_value={'input_ids':[1]}
            results,mode=v.rank('new query',rows,2,'i','numpy')
            self.assertEqual(len(results),2);self.assertEqual(mode,'numpy-bge-m3-cosine')
            with self.assertRaises(ValueError):v.rank('q',[dict(rows[0],content_hash='changed')],2,'i','numpy')
    def test_batched_evidence_keeps_each_period_topk(self):
        from types import SimpleNamespace
        from dart_remote.repository import Repository
        rows=[dict(chunk_id=str(i),year=y,report_type='FY') for i,y in enumerate([2023,2023,2023,2024,2024,2024])]
        fake=SimpleNamespace(sector=SimpleNamespace(topics=('q',),index_version='i'))
        # SimpleNamespace is unhashable; a plain object is the instance cache key.
        class Fake:pass
        repo=Fake();repo.sector=fake.sector
        repo.documents=lambda code:[dict(year=2023,report_type='FY'),dict(year=2024,report_type='FY')]
        repo.chunks=lambda code,**kwargs:rows
        repo.adapt=lambda row,score:dict(row,period=str(row['year']),retrieval_score=score)
        with patch.object(v,'backend',return_value='numpy'),patch.object(v,'rank',return_value=([(rows[i],float(6-i)) for i in [3,0,4,1,5,2]],'numpy')) as scorer:
            hits,status=Repository.select_evidence(repo,'c',2)
            self.assertEqual({h['chunk_id'] for h in hits},{'0','1','3','4'})
            self.assertEqual(status['periods'],2);self.assertEqual(scorer.call_count,1)
    def test_memory_cache_tracks_contract(self):
        with patch.object(v,'_snapshot',(self.key(),self.rows(),self.matrix())):
            meta,matrix=v.snapshot(self.key());self.assertEqual(len(meta),2)

if __name__=='__main__':unittest.main()
