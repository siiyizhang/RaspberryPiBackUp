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
import traceback  # 添加用于详细错误跟踪

# 增强日志配置
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/var/log/microscope.log')  # 添加文件日志
    ]
)

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
    def _send_cors_headers(self):
        """添加CORS头"""
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        """处理OPTIONS请求"""
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
                logging.info('Starting image capture for AI analysis')
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f'ai_capture_{timestamp}.jpg'
                filepath = os.path.join(MEDIA_DIR, filename)
                
                # 捕获图像
                logging.debug(f'Capturing to file: {filepath}')
                picam2.capture_file(filepath)
                
                # 转换为base64
                logging.debug('Converting to base64')
                with open(filepath, 'rb') as f:
                    img_data = base64.b64encode(f.read()).decode('utf-8')
                
                # 删除临时文件
                os.remove(filepath)
                
                # 发送响应
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
                logging.info('Image capture and processing completed successfully')
                
            except Exception as e:
                logging.error(f"Detailed capture error: {str(e)}")
                logging.error(traceback.format_exc())
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self._send_cors_headers()
                self.end_headers()
                error_response = {
                    'status': 'error',
                    'message': str(e),
                    'details': traceback.format_exc()
                }
                self.wfile.write(json.dumps(error_response).encode('utf-8'))
        
        elif self.path == '/toggle_network':
            try:
                logging.info('Starting network toggle')
                
                # 执行网络切换脚本
                result = subprocess.run(
                    'sudo /home/siyi/wifi_toggle.sh client',
                    shell=True,
                    check=True,
                    capture_output=True,
                    text=True
                )
                
                logging.debug(f'Network toggle script output: {result.stdout}')
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self._send_cors_headers()
                self.end_headers()
                
                response_data = {
                    'status': 'success',
                    'message': 'Network mode switched to client'
                }
                self.wfile.write(json.dumps(response_data).encode('utf-8'))
                logging.info('Network toggle completed successfully')
                
            except subprocess.CalledProcessError as e:
                logging.error(f"Network toggle script error: {str(e)}")
                logging.error(f"Script output: {e.output}")
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self._send_cors_headers()
                self.end_headers()
                error_response = {
                    'status': 'error',
                    'message': f"Network toggle failed: {str(e)}",
                    'details': e.output
                }
                self.wfile.write(json.dumps(error_response).encode('utf-8'))
            
            except Exception as e:
                logging.error(f"Unexpected network toggle error: {str(e)}")
                logging.error(traceback.format_exc())
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self._send_cors_headers()
                self.end_headers()
                error_response = {
                    'status': 'error',
                    'message': str(e),
                    'details': traceback.format_exc()
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
    logging.info('Starting streaming server on port 8000')
    server.serve_forever()
finally:
    logging.info('Stopping camera and server')
    picam2.stop_recording()
