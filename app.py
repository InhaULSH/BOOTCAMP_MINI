"""Serve only allowlisted public assets on loopback. Never expose .env/raw data."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from snapdart.config import ROOT

ROUTES = {
    '/': ('web/index.html', 'text/html; charset=utf-8'),
    '/app.js': ('web/app.js', 'text/javascript; charset=utf-8'),
    '/style.css': ('web/style.css', 'text/css; charset=utf-8'),
    '/api/reports': ('data/reports.json', 'application/json; charset=utf-8'),
}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = ROUTES.get(self.path.split('?')[0])
        if route is None:
            self.send_error(404)
            return
        path = ROOT / route[0]
        if not path.exists():
            self.send_error(503, 'Run python -m snapdart.analyze first')
            return
        if self.path.split('?')[0] == '/api/reports':
            from snapdart.dashboard import load_view
            data = json.dumps(load_view(), ensure_ascii=False).encode('utf-8')
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
    args = parser.parse_args()
    print(f'SnapDART: http://127.0.0.1:{args.port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
