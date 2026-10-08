"""Provided client connection integration, preserving pooling and SQL parameters."""
import unittest
from unittest.mock import patch
from dart_remote import db,dart_db_client
class ClientTests(unittest.TestCase):
    def test_original_defaults_and_service_options(self):
        with patch.dict('os.environ',{'MYSQL_HOST':'host','MYSQL_USER':'user','MYSQL_PASSWORD':'secret','MYSQL_DATABASE':'db'}),patch.object(dart_db_client.pymysql,'connect') as connect:
            dart_db_client.get_connection(read_timeout=90)
            options=connect.call_args.kwargs
            self.assertEqual(options['host'],'host');self.assertEqual(options['database'],'db')
            self.assertEqual(options['read_timeout'],90);self.assertEqual(options['cursorclass'],dart_db_client.pymysql.cursors.DictCursor)
    def test_service_engine_uses_imported_client_factory(self):
        db.close()
        try:
            with patch.dict('os.environ',{'MYSQL_USER':'user','MYSQL_DATABASE':'db','CLOUD_SQL_INSTANCE':'','MYSQL_SSL_CA':''}),patch.object(db,'create_engine') as engine,patch.object(dart_db_client,'get_connection') as factory:
                db.engine();creator=engine.call_args.kwargs['creator'];creator()
                self.assertEqual(factory.call_args.kwargs['read_timeout'],90)
                self.assertEqual(factory.call_args.kwargs['cursorclass'],dart_db_client.pymysql.cursors.Cursor)
                self.assertTrue(engine.call_args.kwargs['pool_pre_ping'])
        finally:db.close()
