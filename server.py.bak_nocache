#!/usr/bin/env python3
"""
Allo Health Dashboard — local dev server.

Drop-in replacement for `python3 -m http.server 8083`.
Serves all static files exactly like http.server, plus adds:

  POST /api/refresh-clinic-data
      Runs scripts/build_clinic_data.py (with AWS_PROFILE=redshift-data)
      Streams stdout/stderr back as Server-Sent Events so the browser shows
      live progress, then sends a final "done" or "error" event.

Usage:
    cd /Users/alishaparveen/holistic-demand-dashboard
    python3 server.py            # runs on :8083 (same as before)
    python3 server.py --port 9000
"""

import argparse
import os
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
SCRIPT = ROOT / 'scripts' / 'build_clinic_data.py'
AWS_PROFILE = 'redshift-data'


class Handler(SimpleHTTPRequestHandler):

    def do_GET(self):
        if self.path == '/api/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b'{"status":"ok","server":"server.py"}')
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == '/api/refresh-clinic-data':
            self._run_refresh()
        else:
            self.send_error(404)

    def _run_refresh(self):
        """Run build_clinic_data.py and stream output as Server-Sent Events."""
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        def send(line: str):
            # SSE format: data: <payload>\n\n
            msg = f'data: {line}\n\n'
            try:
                self.wfile.write(msg.encode())
                self.wfile.flush()
            except BrokenPipeError:
                pass

        env = os.environ.copy()
        env['AWS_PROFILE'] = AWS_PROFILE

        try:
            proc = subprocess.Popen(
                [sys.executable, str(SCRIPT)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(ROOT),
                env=env,
            )
            for line in proc.stdout:
                send(line.rstrip('\n'))
            proc.wait()
            if proc.returncode == 0:
                send('__DONE__')
            else:
                send(f'__ERROR__ exit code {proc.returncode}')
        except Exception as e:
            send(f'__ERROR__ {e}')

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.end_headers()

    def log_message(self, fmt, *args):
        # Suppress /api/* noise; show everything else
        if '/api/' not in (args[0] if args else ''):
            super().log_message(fmt, *args)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8083)
    args = parser.parse_args()

    os.chdir(ROOT)
    server = ThreadingHTTPServer(('', args.port), Handler)
    print(f'Allo Health Dashboard → http://localhost:{args.port}')
    print(f'Refresh endpoint      → POST /api/refresh-clinic-data')
    print('Press Ctrl+C to stop.\n')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')


if __name__ == '__main__':
    main()
