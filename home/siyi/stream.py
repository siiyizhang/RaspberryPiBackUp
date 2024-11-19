import io
import logging
import socketserver
from http import server
from threading import Condition
from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder, H264Encoder
from picamera2.outputs import FileOutput
from picamera2.encoders import Quality  # Add this with other imports
import os
import json
from datetime import datetime
import time
import subprocess
import base64
import requests
from PIL import Image
import numpy as np

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
    
    @classmethod
    def toggle_ap_mode(cls, enable=True):
        """Toggle AP mode on/off using system commands"""
        try:
            if enable:
                subprocess.run(['sudo', 'systemctl', 'start', 'hostapd'], check=True)
                subprocess.run(['sudo', 'systemctl', 'start', 'dnsmasq'], check=True)
            else:
                subprocess.run(['sudo', 'systemctl', 'stop', 'hostapd'], check=True)
                subprocess.run(['sudo', 'systemctl', 'stop', 'dnsmasq'], check=True)
        except Exception as e:
            logging.error(f"Error toggling AP mode: {str(e)}")
            raise
        
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
        elif self.path.startswith('/css/'):
            try:
                with open(os.path.join('/var/www/html', self.path[1:]), 'rb') as file:
                    content = file.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/css')
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
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length < 0:
            self.send_error(400, "Content-Length header missing or invalid")
            return
    
        if self.path == '/capture':
            try:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f'capture_{timestamp}.jpg'
                filepath = os.path.join(MEDIA_DIR, filename)
                
                picam2.capture_file(filepath)
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'success'}).encode('utf-8'))
            except Exception as e:
                logging.error(f"Error capturing image: {str(e)}")
                self.send_error(500)
                self.end_headers()
                
        elif self.path == '/capture_for_ai':
            try:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f'ai_capture_{timestamp}.jpg'
                filepath = os.path.join(MEDIA_DIR, filename)
                
                picam2.capture_file(filepath)
                
                with open(filepath, 'rb') as f:
                    img_data = base64.b64encode(f.read()).decode('utf-8')
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'status': 'success',
                    'image': img_data
                }).encode('utf-8'))
                
            except Exception as e:
                logging.error(f"Error in capture_for_ai: {str(e)}")
                self.send_error(500)
                self.end_headers()
        
        elif self.path == '/toggle_network':
            try:
                current_state = True
                self.toggle_ap_mode(not current_state)
                current_state = not current_state
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'status': 'success',
                    'ap_mode': current_state
                }).encode('utf-8'))
                
            except Exception as e:
                logging.error(f"Error toggling network: {str(e)}")
                self.send_error(500)
                self.end_headers()
        
        elif self.path == '/ask_ai':
            try:
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                
                API_KEY = 'your-api-key'  # Replace with your actual key
                API_BASE_URL = 'https://litellm.sph-prod.ethz.ch/v1'
                
                headers = {
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {API_KEY}'
                }
                
                payload = {
                    "model": "claude-3.5-sonnet",
                    "messages": [{
                        "role": "user",
                        "content": f"I'm looking at a microscope image of {data['description']}. Please analyze what we can see in this sample and provide scientific insights."
                    }]
                }
                
                api_response = requests.post(
                    f'{API_BASE_URL}/chat/completions',
                    headers=headers,
                    json=payload
                )
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'response': api_response.json()['choices'][0]['message']['content']
                }).encode('utf-8'))
                
            except Exception as e:
                logging.error(f"Error in ask_ai: {str(e)}")
                self.send_error(500)
                self.end_headers()
    
        elif self.path == '/record/start' and not StreamingHandler.recording:
            try:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f'video_{timestamp}.mp4'
                filepath = os.path.join(MEDIA_DIR, filename)
                
                StreamingHandler.video_encoder = H264Encoder(
                    bitrate=10000000,
                    repeat=False,
                    iperiod=30,
                    quality=Quality.VERY_HIGH
                )
                
                StreamingHandler.video_output = FileOutput(filepath)
                picam2.stop_recording()
                picam2.start_recording(StreamingHandler.video_encoder, StreamingHandler.video_output)
                StreamingHandler.recording = True
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'started'}).encode('utf-8'))
                
            except Exception as e:
                logging.error(f"Error starting recording: {str(e)}")
                self.send_error(500)
                self.end_headers()
                
        elif self.path == '/record/stop' and StreamingHandler.recording:
            try:
                picam2.stop_recording()
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
                self.send_error(500)
                self.end_headers()
        
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
