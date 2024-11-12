import io
import logging
import socketserver
from http import server
from threading import Condition
from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder, H264Encoder
from picamera2.outputs import FileOutput
import os
import json
from datetime import datetime
import time

# Create media directory if it doesn't exist
MEDIA_DIR = '/var/www/html/media'
os.makedirs(MEDIA_DIR, exist_ok=True)

def read_html_file(filename):
    with open(filename, 'r') as file:
        return file.read()

# Read both HTML files
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
    recording = False
    video_output = None
    video_encoder = None

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
        elif self.path == '/album':
            content = ALBUM_PAGE.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == '/media':
            # Return list of media files
            media_files = []
            for filename in os.listdir(MEDIA_DIR):
                filepath = os.path.join(MEDIA_DIR, filename)
                if os.path.isfile(filepath):
                    stats = os.stat(filepath)
                    media_files.append({
                        'filename': filename,
                        'date': stats.st_mtime * 1000,  # Convert to milliseconds
                        'type': 'video' if filename.endswith('.mp4') else 'image'
                    })
            
            content = json.dumps(media_files).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        elif self.path.startswith('/media/'):
            filename = os.path.join(MEDIA_DIR, os.path.basename(self.path))
            if os.path.isfile(filename):
                with open(filename, 'rb') as f:
                    content = f.read()
                self.send_response(200)
                if filename.endswith('.mp4'):
                    self.send_header('Content-Type', 'video/mp4')
                else:
                    self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', len(content))
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_error(404)
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
        elif self.path.startswith('/figures/'):
            try:
                with open(os.path.join('/var/www/html', self.path[1:]), 'rb') as file:
                    content = file.read()
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
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
        if self.path == '/capture':
            # Take a screenshot
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'capture_{timestamp}.jpg'
            filepath = os.path.join(MEDIA_DIR, filename)
            
            # Capture the current frame
            picam2.capture_file(filepath)
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'success'}).encode('utf-8'))
            
        elif self.path == '/record/start' and not StreamingHandler.recording:
            # Start recording
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'video_{timestamp}.mp4'
            filepath = os.path.join(MEDIA_DIR, filename)
                        
            # Configure H264 encoder with proper parameters
            StreamingHandler.video_encoder = H264Encoder(
                bitrate=10000000,  # 10Mbps for better quality
                repeat=False,      # Don't repeat headers
                iperiod=30        # Keyframe interval
            )
            
            # Configure output with proper container format
            StreamingHandler.video_output = FileOutput(filepath)
            
            # Start recording with the configured encoder and output
            picam2.start_recording(
                encoder=StreamingHandler.video_encoder,
                output=StreamingHandler.video_output,
                quality=Quality.VERY_HIGH  # Ensure high quality encoding
            )
            
            StreamingHandler.recording = True
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'started'}).encode('utf-8'))
            
        elif self.path == '/record/stop' and StreamingHandler.recording:
            try:
                # Properly stop the recording
                picam2.stop_recording()
                
                # Add a small delay to ensure the file is properly closed
                time.sleep(0.5)
                
                StreamingHandler.recording = False
                StreamingHandler.video_encoder = None
                StreamingHandler.video_output = None
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'stopped'}).encode('utf-8'))
                
            except Exception as e:
                logging.error(f"Error stopping recording: {str(e)}")
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))

        else:
            self.send_error(404)
            self.end_headers()

class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

# Initialize the camera
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
