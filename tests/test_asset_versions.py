import hashlib
import unittest
from unittest.mock import patch
from dart_remote import asset_versions as a, mysql_vectors as v
from dart_remote.original_document import read_xml

class AssetVersionTests(unittest.TestCase):
    def version(self):
        return dict(data_version='new',index_version='new-index',validated=1,
                    vector_sqlite_sha256='a'*64,faiss_sha256='b'*64)
    def test_reuse_requires_two_full_hashes_and_validated_release(self):
        with patch.object(a.db,'rows',return_value=[dict(data_version='old',index_version='old-index')]) as query:
            self.assertEqual(a.compatible_pairs(self.version()),[['new','new-index'],['old','old-index']])
        sql,params=query.call_args.args
        self.assertIn('validated=1',sql);self.assertEqual(params,dict(s='a'*64,f='b'*64))
        with patch.object(a.db,'rows') as query:
            self.assertEqual(a.compatible_pairs(dict(self.version(),faiss_sha256=None)),[['new','new-index']])
            query.assert_not_called()
    def test_unknown_unvalidated_source_version_fails(self):
        with patch.object(a.db,'rows',return_value=[]),self.assertRaises(ValueError):a.source_versions('unknown')
    def test_old_source_is_allowed_but_checksum_and_mapping_stay_strict(self):
        raw=b'<DOC>original</DOC>'
        row=dict(raw_xml=raw,sha256=hashlib.sha256(raw).hexdigest(),byte_size=len(raw),
                 data_version='old',mapping_version='old',chunk_version='new')
        with patch('dart_remote.original_document.source_versions',return_value=['new','old']):
            with patch.object(a.db,'rows',return_value=[row]):
                self.assertEqual(read_xml('20260312001230','chunk','new'),raw)
            for changed in [dict(row,sha256='bad'),dict(row,mapping_version='different')]:
                with patch.object(a.db,'rows',return_value=[changed]),self.assertRaises(ValueError):
                    read_xml('20260312001230','chunk','new')
    def test_contract_hash_disagreement_fails_before_reuse(self):
        meta=dict(model_name=v.MODEL,model_revision=v.REVISION,embedding_dimension=v.DIM,
                  normalize_embeddings=1,searchable_vector_count=1,faiss_ntotal=1,
                  sqlite_sha256='a'*64,faiss_sha256='c'*64)
        with patch.object(v.db,'rows',side_effect=[[self.version()],[meta]]),self.assertRaisesRegex(ValueError,'해시'):
            v.contract()
    def test_integrity_keeps_pair_and_identity_checks(self):
        with patch.object(v.db,'rows',return_value=[dict(n=2,unique_n=2,bad=0)]) as query:
            v._check_integrity(self.version(),dict(searchable_vector_count=2),[['new','new-index'],['old','old-index']])
        sql,params=query.call_args.args
        self.assertIn('e.vector_id<>m.vector_id',sql);self.assertIn('e.index_version=:ai1',sql)
        self.assertEqual(params['av1'],'old')
        with patch.object(v.db,'rows',return_value=[dict(n=2,unique_n=2,bad=1)]),self.assertRaises(ValueError):
            v._check_integrity(self.version(),dict(searchable_vector_count=2),[['new','new-index']])
    def test_graph_does_not_restore_missing_q4(self):
        from types import SimpleNamespace
        from dart_remote.graph_metrics import GraphData
        graph=GraphData(SimpleNamespace(sector=SimpleNamespace(membership_code='KRX_BANK')))
        with patch.object(graph,'value',return_value=(None,[])) as query:
            self.assertEqual(graph.flow('c',2025,4,'CFS','NET_INCOME'),(None,[]))
        # Missing quarters may now be checked against cumulative/annual inputs;
        # no amount may be invented when every input remains missing.
        self.assertEqual(query.call_args_list[0].args[-1],'quarterly')
    def test_ordinary_graph_does_not_rebuild_missing_q4(self):
        from types import SimpleNamespace
        from snapdart.ui_project import quarter_rows
        repo=SimpleNamespace(financial=lambda code,y,t,basis,kind:dict(revenue=None,operating_income=None,capex=None,operating_cashflow=None))
        rows=quarter_rows(repo,dict(code='c',history=[dict(year=2025,basis='OFS')]),[2025])
        self.assertEqual(len(rows),4);self.assertIsNone(rows[-1]['revenue']);self.assertEqual(rows[-1]['basis'],'OFS')
    def test_snapshot_accepts_old_hash_equivalent_vector_and_rejects_other(self):
        import tempfile,os
        from pathlib import Path
        import numpy as np
        matrix=np.zeros((1,v.DIM),dtype=np.float32);matrix[0,0]=1
        key=dict(count=1,data_version='new',index_version='new-index',asset_pairs=[['new','new-index'],['old','old-index']])
        row=dict(chunk_id='c',vector_id=1,content_hash='h',data_version='new',index_version='new-index',
                 embedding_model=v.MODEL,model_revision=v.REVISION,embedding_dimension=v.DIM,
                 embedding=matrix.tobytes(),embedding_id=1,embedding_version='old',embedding_index='old-index',
                 vector_model=v.MODEL,vector_revision=v.REVISION,vector_dimension=v.DIM)
        for index in ['old-index','wrong-index']:
            with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder,patch.dict(os.environ,{'DART_CACHE_DIR':folder}),patch.object(v,'_snapshot',None),patch.object(v,'contract',return_value=key),patch.object(v.db,'rows',side_effect=[[dict(n=1)],[dict(row,embedding_index=index)],[]]):
                if index=='old-index':
                    meta,loaded=v.snapshot(key);self.assertTrue(np.array_equal(loaded,matrix))
                else:
                    with self.assertRaises(ValueError):v.snapshot(key)

if __name__=='__main__':unittest.main()
