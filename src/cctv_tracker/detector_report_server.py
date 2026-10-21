"""Read-only loopback preview of one private, generated comparison HTML file."""
import argparse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path


def make_server(directory,port=8774):
    document=(Path(directory)/'review.html').resolve(strict=True)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def do_GET(self):
            hosts={f'localhost:{self.server.server_port}',f'127.0.0.1:{self.server.server_port}'}
            allowed=self.headers.get('Host') in hosts and self.headers.get('Origin') in {None,*(f'http://{h}' for h in hosts)}
            status=200 if allowed and self.path in {'/','/review.html'} else 404 if allowed else 403
            data=document.read_bytes() if status==200 else b'Not available'
            self.send_response(status)
            self.send_header('Content-Type','text/html; charset=utf-8' if status==200 else 'text/plain')
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads=True
    return server


def serve_report(directory,port=8774):
    with make_server(directory,port) as server:
        print(f'Private detector review: http://127.0.0.1:{server.server_port}',flush=True)
        try:server.serve_forever()
        except KeyboardInterrupt:pass


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',required=True,type=Path)
    parser.add_argument('--port',type=int,default=8774)
    args=parser.parse_args()
    serve_report(args.directory,args.port)
