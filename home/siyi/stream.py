import io
import logging
import socketserver
from http import server
from threading import Condition
from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder, H264Encoder
from picamera2.outputs import FileOutput
from picamera2.encoders import Quality
import os
import json
from datetime import datetime
import time
import subprocess
import base64
import logging
logging.basicConfig(level=logging.DEBUG)

# Create media directory if it doesn't exist
MEDIA_DIR = '/var/www/html/media'
os.makedirs(MEDIA_DIR, exist_ok=True)

def read_html_file(filename):
    with open(filename, 'r') as file:
        return file.read()

# Read HTML files
try:
    MAIN_PAGE = read_html_file('/var/www/html/index.html')
    ALBUM_PAGE = read_html_file('/var/www/html/album.html')
except FileNotFoundError as e:
    logging.error(f"HTML file not found: {e}")
    raise

class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()

class StreamingHandler(server.BaseHTTPRequestHandler):
    @classmethod
    def toggle_ap_mode(cls, enable=True):
        """Toggle AP mode on/off using system commands"""
        try:
            if enable:
                subprocess.run(['sudo', 'systemctl', 'start', 'hostapd'], check=True)
                subprocess.run(['sudo', 'systemctl', 'start', 'dnsmasq'], check=True)
                logging.info("AP mode enabled")
            else:
                subprocess.run(['sudo', 'systemctl', 'stop', 'hostapd'], check=True)
                subprocess.run(['sudo', 'systemctl', 'stop', 'dnsmasq'], check=True)
                logging.info("AP mode disabled")
        except Exception as e:
            logging.error(f"Error toggling AP mode: {str(e)}")
            raise

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
            except Exception as e:
                logging.warning(
                    'Removed streaming client %s: %s',
                    self.client_address, str(e))
        else:
            self.send_error(404)
            self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        
        if self.path == '/capture_for_ai':
            try:
                logging.debug('Starting image capture...')
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f'ai_capture_{timestamp}.jpg'
                filepath = os.path.join(MEDIA_DIR, filename)
                
                # Capture and save image
                logging.debug(f'Capturing to file: {filepath}')
                picam2.capture_file(filepath)
                
                # Convert to base64
                
                logging.debug('Converting to base64...')
                with open(filepath, 'rb') as f:
                    img_data = base64.b64encode(f.read()).decode('utf-8')
                
                # Send response
                logging.debug('Sending response...')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'status': 'success',
                    'image': img_data
                }).encode('utf-8'))
                
            except Exception as e:
                logging.error(f"Detailed capture error: {str(e)}", exc_info=True)
                self.send_error(500)
                self.end_headers()
        
        elif self.path == '/toggle_network':
            try:
                # Use your shell script directly
                logging.debug('Starting network toggle...')
                result = subprocess.run(['sudo', '~/wifi_toggle.sh'], 
                                 check=True,
                                 capture_output=True,
                                 text=True)
                logging.debug(f'Script output: {result.stdout}')
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'status': 'success'
                }).encode('utf-8'))
                
            except Exception as e:
                logging.error(f"Detailed network error: {str(e)}", exc_info=True)
                self.send_error(500)
                self.end_headers()
        
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
    server.serve_forever()
finally:
    picam2.stop_recording()
