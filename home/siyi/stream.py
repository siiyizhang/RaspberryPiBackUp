import io
import logging
import socketserver
from http import server
from threading import Condition
from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from picamera2.outputs import FileOutput
import os
import json
from datetime import datetime
import base64

# Configure logging with reduced output
logging.basicConfig(
    level=logging.WARNING,  # Changed from DEBUG to WARNING
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/microscope.log')  # Removed StreamHandler to reduce overhead
    ]
)

# Create media directory if it doesn't exist
MEDIA_DIR = '/var/www/html/media'
os.makedirs(MEDIA_DIR, exist_ok=True)

def read_html_file(filename):
    try:
        with open(filename, 'r') as file:
            return file.read()
    except FileNotFoundError:
        logging.error(f"HTML file not found: {filename}")
        raise

# Read HTML files
MAIN_PAGE = read_html_file('/var/www/html/index.html')

class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()

class StreamingHandler(server.BaseHTTPRequestHandler):
    # Disable logging of every request
    def log_message(self, format, *args):
        pass

    def _send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == '/':
            self.send_response(301)
            self.send_header('Location', '/index.html')
            self.end_headers()
        elif self.path == '/index.html':
            content = MAIN_PAGE.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                while True:
                    with output.condition:
                        output.condition.wait()
                        frame = output.frame
                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', len(frame))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')
            except Exception:
                pass  # Silently handle client disconnections
        elif self.path.startswith('/figures/'):
            try:
                file_path = '/var/www/html' + self.path
                with open(file_path, 'rb') as f:
                    self.send_response(200)
                    if self.path.endswith('.png'):
                        self.send_header('Content-Type', 'image/png')
                    content = f.read()
                    self.send_header('Content-Length', len(content))
                    self.end_headers()
                    self.wfile.write(content)
            except FileNotFoundError:
                self.send_error(404)
                self.end_headers()
        else:
            self.send_error(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/capture_for_ai':
            try:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f'ai_capture_{timestamp}.jpg'
                filepath = os.path.join(MEDIA_DIR, filename)
                
                picam2.capture_file(filepath)
                
                with open(filepath, 'rb') as f:
                    img_data = base64.b64encode(f.read()).decode('utf-8')
                    
                os.remove(filepath)
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self._send_cors_headers()
                self.end_headers()
                
                response_data = {
                    'status': 'success',
                    'image': img_data,
                    'timestamp': datetime.now().isoformat()
                }
                self.wfile.write(json.dumps(response_data).encode('utf-8'))
                
            except Exception as e:
                logging.error(f"Capture error: {str(e)}")
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self._send_cors_headers()
                self.end_headers()
                error_response = {
                    'status': 'error',
                    'message': str(e)
                }
                self.wfile.write(json.dumps(error_response).encode('utf-8'))
        else:
            self.send_error(404)
            self.end_headers()

class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

# Initialize camera
picam2 = Picamera2()
picam2.configure(picam2.create_video_configuration(main={"size": (1920, 1080)}))
output = StreamingOutput()
picam2.start_recording(JpegEncoder(), FileOutput(output))

try:
    address = ('', 8000)
    server = StreamingServer(address, StreamingHandler)
    logging.warning('Starting streaming server on port 8000')  # Changed from info to warning
    server.serve_forever()
finally:
    logging.warning('Stopping camera and server')  # Changed from info to warning
    picam2.stop_recording()
