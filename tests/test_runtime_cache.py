import concurrent.futures
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from dart_remote.runtime_cache import Cache,request_scope,request_value,cached_project,_project_cache
from dart_remote import artifacts,catalog

class RuntimeCacheTests(unittest.TestCase):
    def setUp(self):
        _project_cache.clear();artifacts._json_cache.clear();artifacts._home_cache.clear()
        from dart_remote.runtime_cache import _catalog_cache
        _catalog_cache.clear()
    def test_copy_expiration_and_bounded_eviction(self):
        cache=Cache(max_entries=2,max_bytes=4);calls=[]
        def load():calls.append(1);return {'a':[]}
        a=cache.get('a',1,load,size=2);a['a'].append(1)
        self.assertEqual(cache.get('a',1,load,size=2),{'a':[]});self.assertEqual(len(calls),1)
        cache.get('a',2,load,ttl=0,size=2);cache.get('a',2,load,size=2)
        self.assertEqual(len(calls),3)
        cache.get('b',1,load,size=2);cache.get('c',1,load,size=2)
        self.assertNotIn('a',cache.entries);self.assertEqual(cache.bytes,4)
    def test_single_flight_and_exceptions_are_not_cached(self):
        cache=Cache();calls=[]
        def load():calls.append(1);time.sleep(.03);return [1]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            values=list(pool.map(lambda _:cache.get('same',1,load),range(4)))
        self.assertEqual(values,[[1]]*4);self.assertEqual(len(calls),1)
        with self.assertRaises(ValueError):cache.get('bad',1,lambda:(_ for _ in ()).throw(ValueError()))
        self.assertNotIn('bad',cache.entries)
    def test_request_scope_isolation_and_cleanup(self):
        calls=[]
        def load():calls.append(1);return [1]
        @request_scope
        def run():
            a=request_value('k',load);a.append(2)
            return request_value('k',load)
        self.assertEqual(run(),[1]);self.assertEqual(run(),[1]);self.assertEqual(len(calls),2)
    def test_artifact_reread_on_atomic_replace_and_no_mutation(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(artifacts,'ROOT',Path(folder)),patch.dict(os.environ,{'SERVICE_GCS_BUCKET':''}):
            artifacts.put_artifact('s','report',{'value':[1]})
            with patch.object(artifacts.json,'loads',wraps=json.loads) as decode:
                a=artifacts.get_artifact('s','report');a['value'].append(99)
                self.assertEqual(artifacts.get_artifact('s','report'),{'value':[1]});self.assertEqual(decode.call_count,1)
                artifacts.put_artifact('s','report',{'value':[2]})
                self.assertEqual(artifacts.get_artifact('s','report'),{'value':[2]});self.assertEqual(decode.call_count,2)
    def test_quota_reads_bypass_cache(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(artifacts,'ROOT',Path(folder)),patch.dict(os.environ,{'SERVICE_GCS_BUCKET':''}):
            artifacts.put_artifact('_system','quota',{'events':[]})
            with patch.object(artifacts.json,'loads',wraps=json.loads) as decode:
                artifacts.read_versioned('_system','quota');artifacts.read_versioned('_system','quota')
                self.assertEqual(decode.call_count,2)
    def test_project_invalidation_on_files_and_catalog_version(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(artifacts,'ROOT',Path(folder)),patch.dict(os.environ,{'SERVICE_GCS_BUCKET':'','UI_CACHE_SECONDS':'30'}):
            calls=[];sectors=[SimpleNamespace(id='s',version='v1')]
            def load(selected):calls.append(1);return {'sectors':[{'id':'s'}],'companies':[]}
            cached_project(load,None,sectors);cached_project(load,None,sectors);self.assertEqual(len(calls),1)
            artifacts.put_artifact('s','market',{'price':2})
            cached_project(load,None,sectors);self.assertEqual(len(calls),2)
            cached_project(load,None,[SimpleNamespace(id='s',version='v2')]);self.assertEqual(len(calls),3)
    def test_unavailable_response_not_cached(self):
        calls=[]
        def load(selected):calls.append(1);return {'sectors':[{'status':'unavailable'}]}
        cached_project(load,'s',[]);cached_project(load,'s',[]);self.assertEqual(len(calls),2)
    def test_batched_catalog_preserves_membership_hash_and_scope_reuse(self):
        import hashlib
        members=[dict(corp_code='c',effective_from=None,effective_to=None,source_as_of='2026-10-01')]
        def rows(sql,params=None):
            if 'data_versions' in sql:return [dict(validated=1,data_version='v',index_version='i')]
            if 'krx_indices' in sql:return [dict(index_code='KRX_SEMI',index_name='반도체',display_name='반도체',official_index_code=None)]
            return [dict(members[0],index_code='KRX_SEMI',is_operational=1)]
        @request_scope
        def run():return catalog.sectors(),catalog.sectors()
        with patch.dict(os.environ,{'SNAPDART_SECTORS':'','CATALOG_CACHE_SECONDS':'0'}),patch.object(catalog.db,'rows',side_effect=rows) as read:
            first,second=run();self.assertEqual(first,second);self.assertEqual(read.call_count,3)
            expected=hashlib.sha256(json.dumps(members,sort_keys=True).encode()).hexdigest()
            self.assertEqual(first[0].data_version,'v:'+expected)
            run();self.assertEqual(read.call_count,6)

    def test_catalog_reuse_expiration_config_and_cli_bypass(self):
        from dart_remote.runtime_cache import scoped_catalog,_catalog_cache
        calls=[]
        def load():calls.append(1);return [{'value':len(calls)}]
        @request_scope
        def run(stamp=1):return scoped_catalog('c',stamp,load)
        with patch.dict(os.environ,{'CATALOG_CACHE_SECONDS':'30'}):
            a=run();a[0]['value']=9
            self.assertEqual(run(),[{'value':1}]);self.assertEqual(len(calls),1)
            run(2);self.assertEqual(len(calls),2)
            scoped_catalog('c',2,load);self.assertEqual(len(calls),3)
            with patch('dart_remote.runtime_cache.time.monotonic',return_value=time.monotonic()+31):run(2)
            self.assertEqual(len(calls),4)
        with patch.dict(os.environ,{'CATALOG_CACHE_SECONDS':'0'}):run();run()
        self.assertEqual(len(calls),6)
    def test_sql_reuse_is_request_only_and_binary_not_cached(self):
        from dart_remote import db
        @request_scope
        def run():
            a=db.rows('SELECT 1',{'v':1});a[0]['v'].append(2)
            return db.rows('SELECT 1',{'v':1}),db.rows('SELECT 1',{'v':2})
        with patch.object(db,'_rows',side_effect=lambda *a,**k:[{'v':[1]}]) as read:
            self.assertEqual(run(),([{'v':[1]}],[{'v':[1]}]));self.assertEqual(read.call_count,2)
            run();self.assertEqual(read.call_count,4)
        @request_scope
        def binary():db.rows('SELECT raw_xml');db.rows('SELECT raw_xml')
        with patch.object(db,'_rows',return_value=[{'raw_xml':b'raw'}]) as read:
            binary();self.assertEqual(read.call_count,2)
    def test_home_summary_copies_and_reloads_changed_file(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(artifacts,'ROOT',Path(folder)),patch.dict(os.environ,{'SERVICE_GCS_BUCKET':''}):
            artifacts.put_artifact('s','report',{'report_prompt_version':'new','companies':[{'code':'1'}],'big_unused':['detail']*100})
            artifacts.put_artifact('s','market',{'index':{'name':'index','change':2,'history':[]}})
            with patch.object(artifacts,'get_artifact',wraps=artifacts.get_artifact) as read:
                first=artifacts.home_summary('s');first['entries'].append('wrong')
                self.assertEqual(artifacts.home_summary('s')['entries'],['s:1']);self.assertEqual(read.call_count,3)
                self.assertNotIn('big_unused',first)
                artifacts.put_artifact('s','report',{'report_prompt_version':'new','companies':[{'code':'2'}]})
                self.assertEqual(artifacts.home_summary('s')['entries'],['s:2']);self.assertEqual(read.call_count,6)
    def test_catalog_concurrent_requests_load_once(self):
        from dart_remote.runtime_cache import scoped_catalog
        calls=[]
        def load():calls.append(1);time.sleep(.02);return ['same']
        @request_scope
        def run(_):return scoped_catalog('parallel',1,load)
        with patch.dict(os.environ,{'CATALOG_CACHE_SECONDS':'30'}),concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(list(pool.map(run,range(4))),[['same']]*4)
        self.assertEqual(len(calls),1)
