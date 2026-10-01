"""Exercise real local HTTP routes without external market or model requests."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import threading
from urllib.request import urlopen
from urllib.error import HTTPError
from urllib.parse import urlencode,quote
from app import Handler,ThreadingHTTPServer
from snapdart_data.pipeline import load_report

def main():
    report=load_report()
    sector=report['sector_id'];company=report['companies'][0];year=report['years'][-1]
    filing_ref=next(k for k,v in report['citations'].items() if v['source_kind']=='filing')
    financial_ref=next(k for k,v in report['citations'].items() if v['source_kind']=='financial')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    common=dict(sector=sector,code=company['code'],year=year)
    routes=['/','/app.js','/style.css','/api/sectors',
        '/api/reports?'+urlencode(dict(sector=sector)),
        '/api/financial?'+urlencode(common),
        '/api/search?'+urlencode(dict(common,q='설비투자',top_k=2)),
        '/api/source?'+urlencode(dict(sector=sector,ref=filing_ref)),
        '/api/source?'+urlencode(dict(sector=sector,ref=financial_ref)),
        '/api/revenue-source?'+urlencode(dict(common,key='revenue'))]
    try:
        for route in routes:
            with urlopen(base+route,timeout=30) as response:
                body=response.read();assert response.status==200 and body
                if route.startswith('/api/'):
                    value=json.loads(body)
                    if route.startswith('/api/reports'):assert len(value['companies'])==len(report['companies'])
        for route in ('/.env','/data_new/반도체/financial.db'):
            try:urlopen(base+quote(route),timeout=5)
            except HTTPError as error:assert error.code==404
            else:raise AssertionError('Private file became public')
        print(f'PASS: {len(routes)} real HTTP routes; {len(report["companies"])} companies; private files are not exposed.')
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)

if __name__=='__main__':main()
