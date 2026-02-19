import os
import pickle
import logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

from signal import SIGINT, signal
from multiprocessing import Process, Queue, Lock

def handler(signalnum, frame):
    raise TypeError

signal(SIGINT, handler)

import http.server
import subprocess
import tempfile
import socketserver
import base64
import json
from bs4 import BeautifulSoup
import re
PORT = 19027

class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        log.info(f"Received POST request with content length {content_length}")
        response = process_data(post_data)
        log.info(f"Processed data, sending response with length {len(response)}")
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(response)

    def do_GET(self):
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b'GET requests are not supported')


def process_data(pdf_file_bytes):
    with tempfile.TemporaryDirectory(suffix="files-pdf", dir="/tmp") as tmpdir:
        pdf_file_path = os.path.join(tmpdir, "file.pdf")
        with open(pdf_file_path, "wb") as f:
            f.write(pdf_file_bytes)
        del pdf_file_bytes

        return pdf2html(pdf_file_path)


def pdf2html(pdf_file_path):
    workdir = os.path.dirname(pdf_file_path)
    # "--fallback", "1", "--zoom", "1.0", "--fit-width", "768", "--bg-format", "jpg",
    subprocess.check_call([
        "pdf2htmlEX",
        "--fit-width", "768",
        "--dest-dir", workdir,
        "--tounicode", "1",
        "--optimize-text", "1",
        "--embed-external-font", "1",
        "--process-type3", "1",
        "--no-drm", "1",
        pdf_file_path])
    os.remove(pdf_file_path)
    styles = []
    pages = []
    with open(os.path.join(workdir, "file.html"), "rb") as f:
        soup = BeautifulSoup(f, 'html.parser')
        for (i,style) in enumerate(soup.find_all('style')):
            log.info(f"Soup Style {i+1}")
            styles.append(str(style))

        for i, page in enumerate(soup.select("div#page-container>div")):
            log.info(f"Soup Page {i+1}")
            pages.append(str(page))

    width = 768.0
    height = 768.0
    for style in styles:
        # .w0{width:1024.000000px;}
        width1 = 0.0
        height1 = 0.0
        if m:=re.search(r"w0\{width:(\d+\.\d+)px;", style):
            width1 = float(m.group(1))
        if m:=re.search(r"h0\{height:(\d+\.\d+)px;", style):
            height1 = float(m.group(1))
        if width1 > 0.0 and height1 > 0.0:
            width = width1
            height = height1
            break

    return json.dumps({"styles": styles, "pages": pages, "page_count": len(pages), "page_width_px": width, "page_height_px": height},indent=2).encode('utf-8')

if __name__ == "__main__":
    with socketserver.ForkingTCPServer(("", PORT), CustomHandler) as httpd:
        print(f"Serving at port {PORT}, ready to handle POST requests")
        httpd.serve_forever()
