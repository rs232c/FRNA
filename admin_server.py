from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
import json
import os
import sqlite3

class AdminHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        if path.startswith('/admin/'):
            zipcode = path.split('/')[2] if len(path.split('/')) > 2 else '02720'
            if path.endswith('/trash'):
                self.serve_file('trash.html')
            else:
                self.serve_file('admin.html')
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        zipcode = parsed.path.split('/')[2] if len(parsed.path.split('/')) > 2 else '02720'

        if parsed.path.endswith('/trash'):
            self.handle_trash(zipcode)
        elif parsed.path.endswith('/restore'):
            self.handle_restore(zipcode)
        else:
            self.send_response(404)
            self.end_headers()

    def handle_trash(self, zipcode):
        data = self.read_json()
        id = data.get('id')
        if id:
            conn = sqlite3.connect('fallriver_news.db')
            c = conn.cursor()
            c.execute("UPDATE articles SET trashed = 1 WHERE id = ?", (id,))
            conn.commit()
            conn.close()
            self.send_json({"success": True})
        else:
            self.send_json({"error": "No ID"}, 400)

    def handle_restore(self, zipcode):
        data = self.read_json()
        id = data.get('id')
        if id:
            conn = sqlite3.connect('fallriver_news.db')
            c = conn.cursor()
            c.execute("UPDATE articles SET trashed = 0 WHERE id = ?", (id,))
            conn.commit()
            conn.close()
            self.send_json({"success": True})
        else:
            self.send_json({"error": "No ID"}, 400)

    def read_json(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length else b'{}'
        return json.loads(body)

    def serve_file(self, filename):
        filepath = os.path.join('website_output', filename)
        if os.path.exists(filepath):
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            with open(filepath, 'rb') as f:
                self.wfile.write(f.read())
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'File not found')

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, *args):
        pass

if __name__ == '__main__':
    HTTPServer(('127.0.0.1', 8000), AdminHandler).serve_forever()