"""Loopback-only annotation server; serves allowlisted exported files, not videos."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
from pathlib import Path
import secrets
from threading import Lock

from .dataset import frame_index, read_json, validate_labels, write_json


def make_server(dataset, port=8773):
    dataset = Path(dataset).resolve(strict=True)
    manifest = read_json(dataset/'manifest.json')
    validate_labels(manifest,read_json(dataset/'labels.json'))
    allowed = {'/'+frame['image']: dataset/frame['image'] for _,frame in frame_index(manifest).values()}
    for path in allowed.values():
        if not path.resolve(strict=True).is_relative_to(dataset):
            raise ValueError('Frame path escapes the dataset')
    token, lock = secrets.token_urlsafe(32), Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, content, mime='application/json'):
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length',str(len(content)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'nonce-"+token+"'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(content)

        def local(self):
            hosts = {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
            return self.headers.get('Host') in hosts and self.headers.get('Origin') in {None,*(f'http://{h}' for h in hosts)}

        def do_GET(self):
            if not self.local():
                return self.reply(403,b'{}')
            if self.path == '/':
                html = files('cctv_tracker').joinpath('resources/dataset-annotator.html').read_text(encoding='utf-8')
                return self.reply(200,html.replace('__TOKEN__',token).encode(),'text/html; charset=utf-8')
            if self.path == '/manifest':
                return self.reply(200,json.dumps(manifest).encode())
            if self.path == '/labels':
                with lock:
                    return self.reply(200,(dataset/'labels.json').read_bytes())
            if self.path in allowed:
                return self.reply(200,allowed[self.path].read_bytes(),'image/jpeg')
            return self.reply(404,b'{}')

        def do_PUT(self):
            if not self.local() or self.path != '/labels' or not secrets.compare_digest(self.headers.get('X-Annotation-Token',''),token):
                return self.reply(403,b'{}')
            try:
                length = int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 8*1024*1024 or self.headers.get_content_type() != 'application/json':
                    return self.reply(400,b'{"error":"Invalid payload"}')
                value = validate_labels(manifest,json.loads(self.rfile.read(length)))
                with lock:
                    current = read_json(dataset/'labels.json')
                    if current['revision'] != value['revision']:
                        return self.reply(409,b'{"error":"Labels changed in another tab. Reload before editing."}')
                    value['revision'] += 1
                    write_json(dataset/'labels.json',value)
                return self.reply(200,json.dumps({'revision':value['revision']}).encode())
            except (ValueError,KeyError,TypeError) as error:
                return self.reply(400,json.dumps({'error':str(error)}).encode())

    server = ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads = True
    return server


def serve_dataset(dataset,port):
    with make_server(dataset,port) as server:
        print(f'Private annotation tool: http://127.0.0.1:{server.server_port}',flush=True)
        print('Ctrl+C stops the tool. Saved labels remain in the dataset folder.',flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
