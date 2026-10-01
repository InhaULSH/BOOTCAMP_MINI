"""Serve only allowlisted public assets on loopback. Never expose .env/raw data."""
import argparse
import json
from urllib.parse import urlsplit,parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from snapdart.config import ROOT

ROUTES = {
    '/': ('web/index.html', 'text/html; charset=utf-8'),
    '/app.js': ('web/app.js', 'text/javascript; charset=utf-8'),
    '/style.css': ('web/style.css', 'text/css; charset=utf-8'),
    '/api/reports': (None, 'application/json; charset=utf-8'),
}

class Handler(BaseHTTPRequestHandler):
    def send_json(self,value):
        data=json.dumps(value,ensure_ascii=False).encode('utf-8')
        self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if urlsplit(self.path).path == '/api/sectors':
            from snapdart_data.catalog import sectors
            return self.send_json([dict(id=s.id,name=s.name,index_code=s.index_code) for s in sectors()])
        if urlsplit(self.path).path in ('/api/search','/api/financial'):
            from snapdart_data.repository import Repository
            try:
                q=parse_qs(urlsplit(self.path).query);repo=Repository(q.get('sector',[None])[0])
                code=q.get('code',[None])[0];year=int(q['year'][0]) if 'year' in q else None
                report_type=q.get('report_type',[None])[0]
                if urlsplit(self.path).path=='/api/search':
                    rows,status=repo.search(q.get('q',[''])[0],code,year,report_type,int(q.get('top_k',['5'])[0]));return self.send_json(dict(chunks=rows,retrieval=status))
                if not code or not year:raise ValueError('기업과 연도를 지정하세요.')
                return self.send_json(repo.financial(code,year,report_type or 'FY',q.get('basis',['CFS'])[0],q.get('value_type',[None])[0]))
            except (KeyError,ValueError):return self.send_error(400,'Invalid data query')
        if urlsplit(self.path).path == '/api/revenue-source':
            from snapdart.financial_source import revenue_source
            try:
                query=parse_qs(urlsplit(self.path).query)
                data=json.dumps(revenue_source(query.get('code',[''])[0],int(query.get('year',['0'])[0]),query.get('key',['revenue'])[0],sector_id=query.get('sector',[None])[0]),ensure_ascii=False).encode('utf-8')
            except (KeyError,ValueError,OSError):
                self.send_error(404,'Revenue source unavailable');return
            self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
            self.end_headers();self.wfile.write(data);return
        if urlsplit(self.path).path == '/api/source':
            from snapdart.citations import source_excerpt
            try:
                ref=parse_qs(urlsplit(self.path).query).get('ref',[''])[0]
                data=json.dumps(source_excerpt(ref,parse_qs(urlsplit(self.path).query).get('sector',[None])[0]),ensure_ascii=False).encode('utf-8')
            except KeyError:
                self.send_error(404,'Unknown citation');return
            except (OSError,ValueError):
                self.send_error(503,'Source unavailable or anchor mismatch');return
            self.send_response(200)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers();self.wfile.write(data);return
        route = ROUTES.get(self.path.split('?')[0])
        if route is None:
            self.send_error(404)
            return
        path = ROOT / route[0] if route[0] else None
        if self.path.split('?')[0] != '/api/reports' and not path.exists():
            self.send_error(503, 'Run python -m snapdart.analyze first')
            return
        if self.path.split('?')[0] == '/api/reports':
            from snapdart.dashboard import load_view
            try:data = json.dumps(load_view(parse_qs(urlsplit(self.path).query).get('sector',[None])[0]), ensure_ascii=False).encode('utf-8')
            except (KeyError,ValueError):return self.send_error(400,'Unknown sector')
        else:
            data = path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', route[1])
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8501)
    parser.add_argument('--no-market-refresh',action='store_true',help='저장된 시세로 시작; 외부 시세 조회 생략')
    args = parser.parse_args()
    if not args.no_market_refresh:
        from snapdart.market import refresh_prices
        refresh_prices()
    print(f'SnapDART: http://127.0.0.1:{args.port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
