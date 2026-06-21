import cv2
import numpy as np
import torch
import sqlite3
import os
import time
import threading
import socket
import struct
import pickle
from dataclasses import dataclass
from ultralytics import YOLO
from logique_mudas import MudaStateMachine, SystemState, MudaClassification, LogicConfig
from data_pipeline import DataPipeline

print("Booting FORVIA SMART Monitor - LIVE CAMERA EDITION...")

# ==========================================
# THREADED CAMERA READER (eliminates capture blocking)
# ==========================================
class CameraReader:
    """Reads frames from the camera in a background thread so cap.read()
    never blocks the main processing loop."""
    def __init__(self, cap):
        self.cap = cap
        self.frame = None
        self.grabbed = False
        self.new_frame = False
        self.stopped = False
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()
    
    def _update(self):
        while not self.stopped:
            grabbed, frame = self.cap.read()
            with self.lock:
                self.grabbed = grabbed
                self.frame = frame
                self.new_frame = True
    
    def read(self):
        with self.lock:
            if self.new_frame and self.frame is not None:
                self.new_frame = False
                return True, self.frame.copy()
            return False, None
    
    def stop(self):
        self.stopped = True
        self.thread.join(timeout=2)
    
    def isOpened(self):
        return self.cap.isOpened()

class TCPReader:
    """Receives frames from a Raspberry Pi over TCP in a background thread.
    Supports both raw pickle frames and JPEG-compressed frames (auto-detect)."""
    def __init__(self, host_ip, port):
        self.host_ip = host_ip
        self.port = port
        self.frame = None
        self.grabbed = False
        self.new_frame = False
        self.stopped = False
        self.connected = False
        self.lock = threading.Lock()
        self.payload_size = struct.calcsize("Q")
        self._data_buffer = b""
        self._jpeg_mode = None  # Auto-detect on first frame
        
        # Start TCP server
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((host_ip, port))
        self.server_socket.listen(5)
        print(f"TCP Server listening on {host_ip}:{port}")
        print("Waiting for Raspberry Pi on JUKI machine...")
        
        self.client_socket, self.addr = self.server_socket.accept()
        self.client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # Disable Nagle's algorithm for low-latency streaming
        self.connected = True
        print(f"Connection established from: {self.addr}")
        
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()
    
    def _update(self):
        while not self.stopped and self.connected:
            try:
                # Read message size header
                while len(self._data_buffer) < self.payload_size:
                    packet = self.client_socket.recv(65536)  # 64KB buffer for speed
                    if not packet:
                        self.connected = False
                        print("TCP: Connection lost from Raspberry Pi.")
                        return
                    self._data_buffer += packet
                
                packed_msg_size = self._data_buffer[:self.payload_size]
                self._data_buffer = self._data_buffer[self.payload_size:]
                msg_size = struct.unpack("Q", packed_msg_size)[0]
                
                # Read frame data
                while len(self._data_buffer) < msg_size:
                    packet = self.client_socket.recv(65536)
                    if not packet:
                        self.connected = False
                        print("TCP: Connection lost from Raspberry Pi during frame reception.")
                        return
                    self._data_buffer += packet
                
                frame_data = self._data_buffer[:msg_size]
                self._data_buffer = self._data_buffer[msg_size:]
                
                try:
                    data = pickle.loads(frame_data)
                    is_pickled = True
                except Exception:
                    data = frame_data
                    is_pickled = False
                
                if not is_pickled:
                    # Direct unpickled bytes stream (best performance)
                    if data.startswith(b'\xff\xd8'):
                        frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
                        if self._jpeg_mode is None:
                            self._jpeg_mode = True
                            print("TCP: Raw JPEG bytes stream detected (optimized)")
                    else:
                        # Fallback / Raw stream format mismatch
                        frame = None
                        if self._jpeg_mode is None:
                            self._jpeg_mode = False
                            print("TCP: Error - Unrecognized raw stream data format")
                else:
                    # Legacy pickled stream (backward compatibility)
                    if isinstance(data, bytes):
                        frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
                        if self._jpeg_mode is None:
                            self._jpeg_mode = True
                            print("TCP: JPEG compressed stream detected (legacy pickled)")
                    elif isinstance(data, np.ndarray) and data.ndim == 1:
                        frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
                        if self._jpeg_mode is None:
                            self._jpeg_mode = True
                            print("TCP: JPEG compressed stream detected (legacy pickled numpy)")
                    else:
                        frame = data
                        if self._jpeg_mode is None:
                            self._jpeg_mode = False
                            print("TCP: RAW uncompressed stream (consider JPEG on Pi for better FPS)")
                
                if frame is not None:
                    with self.lock:
                        self.grabbed = True
                        self.frame = frame
                        self.new_frame = True
            except Exception as e:
                if not self.stopped:
                    print(f"TCP recv error: {e}")
                    self.connected = False
                return
    
    def read(self):
        with self.lock:
            if self.new_frame and self.frame is not None:
                self.new_frame = False
                return self.grabbed, self.frame.copy()
            return False, None
    
    def stop(self):
        self.stopped = True
        try: self.client_socket.close()
        except: pass
        try: self.server_socket.close()
        except: pass
        self.thread.join(timeout=2)
    
    def isOpened(self):
        return self.connected

# ==========================================
# 1. CONFIGURATIONµ
# ==========================================
@dataclass
class VisionConfig:
    script_dir:    str   = os.path.dirname(os.path.abspath(__file__))
    model_path:    str   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "best.pt")
    video_path:    str   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "PFE Video.mp4")
    db_path:       str   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "forvia_production.db") 

    # ---- SOURCE MODE ----
    # Priority: use_tcp > use_camera > video file
    use_tcp:       bool  = True       # True = receive frames from Raspberry Pi over TCP
    tcp_host:      str   = '192.168.137.1'  # Laptop IP on the shared network
    tcp_port:      int   = 9999

    use_camera:    bool  = False      # True = live USB camera (ignored if use_tcp=True)
    camera_index:  int   = 1          # USB camera index (0 = laptop webcam, 1 = external USB 4K)
    camera_w:      int   = 1280       # 720p capture resolution (drastically faster than 1080p on CPU)
    camera_h:      int   = 720        # 
    camera_fps:    int   = 30         # Requested FPS from camera

    conf_thresh:   float = 0.2  # NEW: Low global threshold to capture dark/poorly-lit tissu
    process_every: int   = 4
    display_w:     int   = 1280 
    display_h:     int   = 720
    imgsz:         int   = 640        # YOLO inference size (640 = fast CPU, 1024 = high accuracy)
    use_half:      bool  = False      # FP16 half-precision (set True only on RTX cards with Tensor Cores)

    # User's V4 ROIs (raw 4K) 
    roi_machine: tuple = ((519, 471), (2283, 405), (2448, 657), (561, 831), (522, 468))
    roi_ok:      tuple = ((2502, 1518), (2910, 1401), (3273, 1602), (2895, 1779), (2502, 1515))
    roi_scrap:   tuple = ((3351, 1647), (2973, 1815), (3363, 2091), (3771, 1917), (3360, 1638))

    # ROI Reference Resolution (The resolution used to define the coordinates above)
    roi_ref_w: int = 3840
    roi_ref_h: int = 2160

cfg = VisionConfig()

# ==========================================
# 2. DATABASE
# ==========================================
def init_db():
    conn = sqlite3.connect(cfg.db_path)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS production_log (id INTEGER PRIMARY KEY AUTOINCREMENT, piece_number INTEGER, result TEXT, sewing_time_s REAL, qc_time_s REAL, rework_count INTEGER, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, synced INTEGER DEFAULT 0)')
    c.execute('CREATE TABLE IF NOT EXISTS downtime_log (id INTEGER PRIMARY KEY AUTOINCREMENT, muda_type TEXT, duration_s REAL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)')
    # Migration: check if synced column exists, if not, add it
    try:
        c.execute('ALTER TABLE production_log ADD COLUMN synced INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    conn.commit(); conn.close()

def log_production(piece_number, result, sewing_time, qc_time, rework_count):
    row_id = None
    try:
        conn = sqlite3.connect(cfg.db_path)
        c = conn.cursor()
        c.execute('INSERT INTO production_log (piece_number, result, sewing_time_s, qc_time_s, rework_count, synced) VALUES (?, ?, ?, ?, ?, 0)',
                  (piece_number, result, sewing_time, qc_time, rework_count))
        row_id = c.lastrowid
        conn.commit(); conn.close()
    except Exception as e:
        print("DB Error:", e)
    return row_id

def log_downtime(muda_type, duration):
    try:
        conn = sqlite3.connect(cfg.db_path)
        c = conn.cursor()
        c.execute('INSERT INTO downtime_log (muda_type, duration_s) VALUES (?, ?)', (muda_type, duration))
        conn.commit(); conn.close()
    except Exception as e:
        print("DB Error:", e)

init_db()

# ==========================================
# 3. INIT MODEL & SOURCE
# ==========================================
cv2.setUseOptimized(True)
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"[INFO] Using inference device: {device.upper()}")
if device == "cpu":
    torch.set_num_threads(4)
    cfg.use_half = False  # FP16 not supported on CPU
model = YOLO(cfg.model_path).to(device)

# FP16 half-precision: handled by passing half=True to model() calls (~30% faster on GPU)
if cfg.use_half and device == "cuda":
    print("[PERF] FP16 half-precision ENABLED (will apply during inference)")

# CUDA Warmup: first inference is always slow due to kernel compilation.
# Run 3 dummy frames to pre-warm the GPU pipeline before real processing.
if device == "cuda":
    print("[PERF] Warming up CUDA kernels (3 dummy inferences)...", end=" ", flush=True)
    _dummy = np.zeros((cfg.display_h, cfg.display_w, 3), dtype=np.uint8)
    for _ in range(3):
        model(_dummy, imgsz=cfg.imgsz, conf=cfg.conf_thresh, verbose=False, device=device, half=cfg.use_half)
    del _dummy
    torch.cuda.synchronize()
    print("Done!")

raw_cap = None  # Only used for camera/video modes

if cfg.use_tcp:
    # ---- RASPBERRY PI TCP RECEIVER ----
    cap = TCPReader(cfg.tcp_host, cfg.tcp_port)
    source_name = f"TCP ({cfg.tcp_host}:{cfg.tcp_port})"
    # Resolution will be determined from the first frame
    VIDEO_W, VIDEO_H, VIDEO_FPS = 0, 0, 30.0
    print(f"Source  : {source_name}")
    print("Resolution: will detect from first frame")

elif cfg.use_camera:
    # ---- USB CAMERA ----
    raw_cap = cv2.VideoCapture(cfg.camera_index, cv2.CAP_DSHOW)
    raw_cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    raw_cap.set(cv2.CAP_PROP_FRAME_WIDTH,  cfg.camera_w)
    raw_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.camera_h)
    raw_cap.set(cv2.CAP_PROP_FPS,          cfg.camera_fps)
    raw_cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    source_name = f"USB Camera #{cfg.camera_index}"
    cap = CameraReader(raw_cap)

    if not raw_cap.isOpened():
        print(f"ERROR: Cannot open {source_name}"); raise SystemExit
    VIDEO_W = int(raw_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    VIDEO_H = int(raw_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    VIDEO_FPS = raw_cap.get(cv2.CAP_PROP_FPS) or 30.0
    print(f"Source  : {source_name}")
    print(f"Resolution: {VIDEO_W}x{VIDEO_H} @ {VIDEO_FPS:.1f} FPS")
    if VIDEO_W < cfg.camera_w or VIDEO_H < cfg.camera_h:
        print(f"WARNING: Camera settled at {VIDEO_W}x{VIDEO_H} instead of requested {cfg.camera_w}x{cfg.camera_h}")

else:
    # ---- VIDEO FILE ----
    raw_cap = cv2.VideoCapture(cfg.video_path)
    cap = raw_cap
    source_name = cfg.video_path
    if not raw_cap.isOpened():
        print(f"ERROR: Cannot open {source_name}"); raise SystemExit
    VIDEO_W = int(raw_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    VIDEO_H = int(raw_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    VIDEO_FPS = raw_cap.get(cv2.CAP_PROP_FPS) or 30.0
    print(f"Source  : {source_name}")
    print(f"Resolution: {VIDEO_W}x{VIDEO_H} @ {VIDEO_FPS:.1f} FPS")

# Scale factors from 4K (Ref) to Display
sx, sy = cfg.display_w / cfg.roi_ref_w, cfg.display_h / cfg.roi_ref_h

def scale_poly(pts):
    return np.array([(int(x*sx), int(y*sy)) for x,y in pts], np.int32)

ZONE_JUKI  = scale_poly(cfg.roi_machine)
ZONE_OK    = scale_poly(cfg.roi_ok)
ZONE_REBUT = scale_poly(cfg.roi_scrap)

# ==========================================
# 4. STATE & BUFFERS
# ==========================================
machine = MudaStateMachine(cfg=LogicConfig())
pipeline = DataPipeline(broker_ip="127.0.0.1")
previous_state = machine.current_state
MAX_TTL    = 5
buf_frames = {k: 0 for k in ["jig", "maint", "oper", "mains", "mains_in", "maint_in", "multi_oper"]}
missing    = {k: MAX_TTL for k in ["jig", "maint", "oper", "mains", "mains_in", "maint_in", "multi_oper"]}

# Smart Stacking Detection Timers (wall-clock based for live camera)
last_count_ok_time   = 0.0
last_count_scrap_time = 0.0
mains_in_ok_timer    = 0.0
mains_in_scrap_timer = 0.0
ok_confirm_timer     = 0.0
scrap_confirm_timer  = 0.0
# Wall-clock based timers
last_det_boxes     = []
paused             = False
loop_start_time    = time.time()
last_frame_time    = time.time()
fps_counter        = 0
fps_display        = 0.0
fps_timer          = time.time()
frame_count        = 0
collected_points   = []

# Tissu persistence: 15s memory to bridge "stationary" detection gaps
TISSU_TTL          = 15.0  
tissu_ok_last_seen = 0.0   
tissu_rebut_last_seen = 0.0  

# NEW: Pure Duration-Based Counting (100% Accuracy Refactor)
ok_presence_timer    = 0.0
scrap_presence_timer = 0.0
empty_ok_timer       = 0.0
empty_scrap_timer    = 0.0

def on_mouse(event, x, y, flags, param):
    global collected_points
    if event == cv2.EVENT_LBUTTONDOWN:
        # OpenCV maps mouse coords to image space automatically with WINDOW_NORMAL
        # Scale directly from display (1280x720) to 4K reference
        raw_x = int(x * (cfg.roi_ref_w / cfg.display_w))
        raw_y = int(y * (cfg.roi_ref_h / cfg.display_h))
        collected_points.append((raw_x, raw_y))
        print(f"Point Added: ({raw_x}, {raw_y}) | Click: ({x},{y}) | Total: {len(collected_points)}")

# ==========================================
# 5. UI COMPONENTS (PRO EDITION)
# ==========================================
C_FORVIA_BLUE = (150, 75, 0)   # More professional blue
C_EMERALD     = (120, 210, 50)
C_SCRAP       = (60, 60, 220)
C_WHITE       = (255, 255, 255)
C_DARK        = (30, 30, 30)
C_GREY        = (180, 180, 180)
C_GOLD        = (0, 215, 255)

def draw_rounded_rect(img, pt1, pt2, color, thickness, r):
    x1, y1 = pt1
    x2, y2 = pt2
    # Fill
    if thickness == -1:
        cv2.rectangle(img, (x1 + r, y1), (x2 - r, y2), color, -1)
        cv2.rectangle(img, (x1, y1 + r), (x2, y2 - r), color, -1)
        cv2.circle(img, (x1 + r, y1 + r), r, color, -1)
        cv2.circle(img, (x2 - r, y1 + r), r, color, -1)
        cv2.circle(img, (x1 + r, y2 - r), r, color, -1)
        cv2.circle(img, (x2 - r, y2 - r), r, color, -1)
    else:
        # Outline (less common for HUD)
        cv2.line(img, (x1 + r, y1), (x2 - r, y1), color, thickness)
        cv2.line(img, (x1 + r, y2), (x2 - r, y2), color, thickness)
        cv2.line(img, (x1 + r, y1 + r), (x1, y2 - r), color, thickness)
        cv2.line(img, (x2, y1 + r), (x2, y2 - r), color, thickness)
        cv2.ellipse(img, (x1 + r, y1 + r), (r, r), 180, 0, 90, color, thickness)
        cv2.ellipse(img, (x2 - r, y1 + r), (r, r), 270, 0, 90, color, thickness)
        cv2.ellipse(img, (x1 + r, y2 - r), (r, r), 90, 0, 90, color, thickness)
        cv2.ellipse(img, (x2 - r, y2 - r), (r, r), 0, 0, 90, color, thickness)

def draw_panel(frame, x, y, w, h, alpha=0.7, title=None):
    # Clamp coordinates to frame boundaries
    fh, fw = frame.shape[:2]
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(fw, x + w), min(fh, y + h)
    if x2 <= x1 or y2 <= y1:
        return
    
    # Extract ROI of the panel for alpha blending (avoids copying/blending the whole frame)
    roi = frame[y1:y2, x1:x2]
    overlay = roi.copy()
    
    # Draw relative to the ROI
    draw_rounded_rect(overlay, (x - x1, y - y1), (x + w - x1, y + h - y1), C_DARK, -1, 15)
    cv2.addWeighted(overlay, alpha, roi, 1 - alpha, 0, roi)
    
    draw_rounded_rect(frame, (x, y), (x + w, y + h), (100, 100, 100), 1, 15)
    if title:
        cv2.rectangle(frame, (x + 15, y + 30), (x + w - 15, y + 32), C_FORVIA_BLUE, -1)
        txt(frame, title, (x + 20, y + 25), 0.5, C_FORVIA_BLUE, 2)

def draw_zone(frame, poly, color, alpha=0.15, label=None):
    # Optimized: use ROI bounding rect instead of full frame copy
    x, y, rw, rh = cv2.boundingRect(poly)
    pad = 2
    x1c, y1c = max(0, x - pad), max(0, y - pad)
    x2c, y2c = min(frame.shape[1], x + rw + pad), min(frame.shape[0], y + rh + pad)
    sub = frame[y1c:y2c, x1c:x2c]
    overlay = sub.copy()
    shifted_poly = poly - np.array([x1c, y1c])
    cv2.fillPoly(overlay, [shifted_poly], color)
    cv2.addWeighted(overlay, alpha, sub, 1-alpha, 0, sub)
    cv2.polylines(frame, [poly], True, color, 1, cv2.LINE_AA)
    if label: txt(frame, label, (poly[0][0], poly[0][1]-10), 0.5, color, 1)

def state_color(state):
    return {
        SystemState.IDLE: C_GREY, 
        SystemState.NORMAL_PRODUCTION: C_EMERALD, 
        SystemState.QC: (255,200,0), 
        SystemState.MACHINE_STOPPED: C_SCRAP,
        SystemState.RESTART_VALIDATION: (255, 255, 0)
    }.get(state, C_WHITE)

def get_color(cname):
    for key, col in {"jig_charge":(0,255,0), "jig_vide":(0,200,200), "mains":(255,255,0), "maintenance":(0,165,255), "operateur":(255,255,255), "tissu":(200,200,200)}.items():
        if key in cname.lower(): return col
    return (180,180,180)

def inside(poly, cx, cy, buffer=20):
    # Returns True if point is inside OR within 'buffer' pixels of the edge
    return cv2.pointPolygonTest(poly, (float(cx), float(cy)), True) >= -buffer

def get_ttl(key):
    if "mains" in key: return 10 # Reduced from 15 to prevent Retouche % inflating
    if "jig" in key: 
        # Dynamic Juki TTL: long buffer (25 frames) while sewing to prevent false micro-stops.
        # Extremely short buffer (3 frames) when stopped/idle to capture fast swaps instantly!
        if 'machine' in globals() and machine.is_moving:
            return 25
        return 3
    if "maint" in key: return 25 
    return MAX_TTL

def update_buffer(key, detected):
    if detected:
        missing[key] = 0
    else:
        missing[key] += 1

def is_present(key): 
    return missing[key] < get_ttl(key)

def txt(frame, text, pos, scale=0.6, color=C_WHITE, thickness=1, shadow=True):
    if shadow:
        cv2.putText(frame, str(text), (pos[0]+1, pos[1]+1), cv2.FONT_HERSHEY_SIMPLEX, scale, (0,0,0), thickness+1, cv2.LINE_AA)
    cv2.putText(frame, str(text), pos, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)

def draw_hud(frame, fidx):
    w, h = cfg.display_w, cfg.display_h
    
    # 1. PRODUCTION SUMMARY
    draw_panel(frame, 20, 80, 260, 170, title="PRODUCTION")
    txt(frame, f"OK    : {machine.count_ok}", (40, 135), 0.6, C_EMERALD, 2)
    txt(frame, f"SCRAP : {machine.count_scrap}", (40, 165), 0.6, C_SCRAP, 2)
    txt(frame, f"WAITING: {machine.production_credits} pc", (40, 195), 0.5, (255, 255, 0), 1)
    txt(frame, f"SEW TIME: {machine.current_cycle_sewing_time:.1f}s / {machine.cfg.t_sewing_min:.0f}s", (40, 225), 0.45, (200, 200, 200), 1)

    # 2. SYSTEM STATUS
    draw_panel(frame, 20, 290, 260, 160, title="MONITOR")
    sc = state_color(machine.current_state)
    stat_str = machine.current_state.value
    
    # Status LED
    cv2.circle(frame, (45, 365), 10, sc, -1)
    cv2.circle(frame, (45, 365), 12, C_WHITE, 1)
    txt(frame, stat_str, (70, 375), 0.6, sc, 2)
    
    if machine.last_classification:
        txt(frame, f"LAST: {machine.last_classification.value}", (40, 410), 0.45, (255,165,0), 1)
    
    # Progress Indicators (Hysteresis/Validation)
    if machine.pending_maint_validation:
        rem = machine.cfg.t_maint_validation - (time.time() - machine.maint_validation_start)
        txt(frame, "VALIDATING REPAIR...", (40, 435), 0.4, C_GREY, 1)
        cv2.rectangle(frame, (40, 440), (240, 445), (40, 40, 40), -1)
        cv2.rectangle(frame, (40, 440), (40 + int(max(0, rem)/machine.cfg.t_maint_validation*200), 445), (0, 255, 0), -1)
    elif machine.current_state == SystemState.RESTART_VALIDATION:
        rem_rep = machine.cfg.t_reprise - (time.time() - machine.reprise_start_time)
        txt(frame, "STABILIZING...", (40, 435), 0.4, C_GREY, 1)
        cv2.rectangle(frame, (40, 440), (240, 445), (40, 40, 40), -1)
        cv2.rectangle(frame, (40, 440), (40 + int(max(0, rem_rep)/machine.cfg.t_reprise*200), 445), (255, 255, 0), -1)

    # 3. AI SENSORS
    draw_panel(frame, w-280, 80, 260, 220, title="AI HEALTH")
    def draw_sensor(y, key, label, color):
        is_active = is_present(key)
        t_col = color if is_active else C_GREY
        txt(frame, label, (w-260, y), 0.45, t_col, 1)
        limit = get_ttl(key)
        val = max(0, limit - missing[key])
        cv2.rectangle(frame, (w-260, y+10), (w-40, y+18), (40,40,40), -1)
        if val > 0: cv2.rectangle(frame, (w-260, y+10), (w-260+int((val/limit)*220), y+18), color, -1)
    draw_sensor(130, "jig", "Jig Presence", (0,255,0))
    draw_sensor(170, "maint", "Maintenance", (0,180,255))
    draw_sensor(210, "oper", "Operator", (255,255,255))
    draw_sensor(250, "mains", "Manual Work", (255,220,0))

    # 4. PERFORMANCE ANALYSIS (Diagnostic by Elimination)
    # 4. PERFORMANCE ANALYSIS (Diagnostic by Elimination)
    draw_panel(frame, 20, h-220, 360, 200, title="DIAGNOSTIC")
    
    is_live = machine.current_state in [SystemState.MACHINE_STOPPED, SystemState.RESTART_VALIDATION]
    if is_live:
        stop_t  = time.time() - machine.stop_start_time if machine.stop_start_time > 0 else 0
        div     = max(1.0, stop_t)
        h_pct   = machine.acc_hands_s / div
        m_pct   = machine.acc_maint_s / div
        o_pct   = machine.acc_operator_s / div
        abs_maint = machine.acc_maint_s
    else:
        # Machine is back to normal! Reset all stats to 0
        stop_t  = 0.0
        h_pct   = 0.0
        m_pct   = 0.0
        o_pct   = 0.0
        abs_maint = 0.0

    # Classification Tag
    if not is_live:
        stop_type = "RUNNING"
        st_col = C_EMERALD
    elif stop_t < machine.cfg.t_micro:
        stop_type = "MICRO-STOP"
        st_col = C_GOLD
    else:
        if m_pct >= machine.cfg.s_presence_maint_pct or abs_maint >= machine.cfg.t_micro_maint:
            stop_type = "MAINTENANCE"
            st_col = (0, 165, 255)
        elif h_pct >= machine.cfg.s_presence_retouche_pct:
            stop_type = "REWORK"
            st_col = (0, 140, 255)
        else:
            stop_type = "UNJUSTIFIED"
            st_col = (0, 255, 255)

    txt(frame, f"DUR: {stop_t:.1f}s", (40, h-160), 0.7, C_WHITE, 2)
    txt(frame, f"[{stop_type}]", (200, h-160), 0.5, st_col, 1)
    
    def draw_stat(y, label, pct, target, is_abs=False, custom_color=None):
        col = C_EMERALD if pct >= target else C_GREY
        if custom_color: col = custom_color
        val_str = f"{pct:.0f}s" if is_abs else f"{pct:.0%}"
        tgt_str = f"{target:.0f}s" if is_abs else f"{target:.0%}"
        txt(frame, f"{label}: {val_str}", (40, y), 0.45, C_WHITE if not custom_color else custom_color, 1)
        txt(frame, f"Tgt:{tgt_str}", (280, y), 0.35, C_GREY, 1)
        cv2.rectangle(frame, (140, y-12), (270, y-2), (40,40,40), -1)
        if pct > 0:
            ratio = min(1.0, pct / target) if target > 0 else 0
            cv2.rectangle(frame, (140, y-12), (140+int(ratio*130), y-2), col, -1)
    
    rework_active_col = C_GOLD if is_present("mains_in") else C_WHITE
    draw_stat(h-120, "Rework", h_pct, machine.cfg.s_presence_retouche_pct, custom_color=rework_active_col)
    draw_stat(h-90, "Maint%", m_pct, machine.cfg.s_presence_maint_pct)



# ==========================================
# 6. MAIN LOOP
# ==========================================
cv2.namedWindow("FORVIA - SMART Monitor", cv2.WINDOW_NORMAL)
cv2.resizeWindow("FORVIA - SMART Monitor", cfg.display_w, cfg.display_h)
cv2.setMouseCallback("FORVIA - SMART Monitor", on_mouse)

while cap.isOpened():
    if not paused:
        success, frame = cap.read()
        if not success or frame is None:
            if cfg.use_tcp or cfg.use_camera:
                time.sleep(0.005)  # Brief sleep to avoid busy-waiting
                continue
            else:
                break  # End of video file
        
        # Auto-detect resolution from first TCP frame
        if cfg.use_tcp and VIDEO_W == 0 and frame is not None:
            VIDEO_H, VIDEO_W = frame.shape[:2]
            VIDEO_FPS = 30.0
            print(f"TCP Frame detected: {VIDEO_W}x{VIDEO_H}")
        frame_count += 1
        now = time.time()
        real_dt = now - last_frame_time
        last_frame_time = now
        
        # FPS measurement
        fps_counter += 1
        if now - fps_timer >= 1.0:
            fps_display = fps_counter / (now - fps_timer)
            fps_counter = 0
            fps_timer = now
        
        if frame.shape[1] == cfg.display_w and frame.shape[0] == cfg.display_h:
            display = frame
        else:
            display = cv2.resize(frame, (cfg.display_w, cfg.display_h), interpolation=cv2.INTER_LINEAR)

        if frame_count % cfg.process_every == 0:
            t_frame_start = time.time()
            current_video_s = time.time() - loop_start_time if (cfg.use_tcp or cfg.use_camera) else (cap.get(cv2.CAP_PROP_POS_FRAMES) / max(1.0, VIDEO_FPS))
            results = model(display, imgsz=cfg.imgsz, conf=cfg.conf_thresh, verbose=False, device=device, half=cfg.use_half)
            det = {k: False for k in ["jig", "maint", "oper", "mains"]}
            jig_in_juki = tissu_ok = tissu_rebut = False
            mains_in_juki = maint_in_juki = False
            jig_vide_on_table = False
            operator_count = 0
            curr_jig_xy = None
            current_boxes = []
            hand_boxes = []
            jig_charge_boxes = []
            tissu_boxes = []
            piece_boxes = [] # For general "Manual Work" detection
            tissu_ok_boxes = []
            tissu_rebut_boxes = []
            
            for box in results[0].boxes:
                cname = model.names[int(box.cls[0])]
                conf = float(box.conf[0])
                low_cname = cname.lower()
                
                # Class-specific confidence: super-sensitive for tissu (0.05), standard for others (0.15)
                min_conf = 0.05 if "tissu" in low_cname else 0.15
                if conf < min_conf:
                    continue
                    
                x1,y1,x2,y2 = map(int, box.xyxy[0])
                cx, cy = (x1+x2)//2, (y1+y2)//2
                current_boxes.append((x1,y1,x2,y2, cname))
                
                if "maintenance" in low_cname: det["maint"] = True
                elif "operateur" in low_cname: det["oper"] = True
                
                # Collect hands and pieces separately for intersection checking
                if "mains" in low_cname or low_cname == "main":
                    hand_boxes.append((x1,y1,x2,y2, cx, cy))
                elif "jig_charge" in low_cname:
                    jig_charge_boxes.append((x1,y1,x2,y2))
                    piece_boxes.append((x1,y1,x2,y2))
                elif "tissu" in low_cname:
                    tissu_boxes.append((x1,y1,x2,y2))
                    piece_boxes.append((x1,y1,x2,y2))
                elif low_cname == "jig_vide":
                    piece_boxes.append((x1,y1,x2,y2))
                
                if inside(ZONE_JUKI, cx, cy):
                    if "jig_charge" in low_cname:    
                        jig_in_juki = True
                        det["jig"] = True
                    elif "maintenance" in low_cname: maint_in_juki = True
                    elif "operateur" in low_cname:   operator_count += 1
                
                # NEW: Track if operator body is in OK/Scrap zones to inhibit "pass-by" triggers
                if "operateur" in low_cname:
                    # If operator center or a large portion of their box is in the zone, it's a pass-by
                    if (inside(ZONE_OK, cx, cy) or inside(ZONE_REBUT, cx, cy)) and (x2 - x1 > 100):
                        det["oper_in_zone"] = True 
                
                if "jig_charge" in low_cname:
                    if inside(ZONE_JUKI, cx, cy):
                        curr_jig_xy = (cx, cy)
                elif "jig_vide" in low_cname:
                    if inside(ZONE_OK, cx, cy): jig_vide_on_table = True
                    elif inside(ZONE_REBUT, cx, cy): jig_vide_on_table = True
                elif "tissu" in low_cname:
                    # MULTI-POINT CLASSIFICATION: Check center, bottom-center, and bottom corners for 100% detection rate
                    check_pts = [(cx, cy), (cx, y2), (x1, y2), (x2, y2)]
                    in_ok = any(inside(ZONE_OK, px, py, buffer=15) for px, py in check_pts)
                    in_rebut = any(inside(ZONE_REBUT, px, py, buffer=15) for px, py in check_pts)
                    
                    if in_ok and in_rebut:
                        # Tie-breaker: which one is the center closer to? (Strict center check)
                        if inside(ZONE_OK, cx, cy, buffer=0): in_rebut = False
                        else: in_ok = False

                    if in_ok: 
                        tissu_ok = True
                        tissu_ok_boxes.append((x1,y1,x2,y2))
                        tissu_ok_last_seen = current_video_s
                    elif in_rebut: 
                        tissu_rebut = True
                        tissu_rebut_boxes.append((x1,y1,x2,y2))
                        tissu_rebut_last_seen = current_video_s
                    else:
                        pass  # Tissu outside zones — ignored
            
            # Apply tissu persistence: if tissu was recently seen in a zone, keep it "present"
            tissu_ok_persistent = tissu_ok or (current_video_s - tissu_ok_last_seen < TISSU_TTL)
            tissu_rebut_persistent = tissu_rebut or (current_video_s - tissu_rebut_last_seen < TISSU_TTL)
            
            # INTERSECTION FILTER: Capture hands touching pieces, and count OK/Scrap interactions
            hands_touching_ok = False
            hands_touching_rebut = False
            
            for hx1, hy1, hx2, hy2, hcx, hcy in hand_boxes:
                # 1. OK/Scrap Zone Detection
                if inside(ZONE_OK, hcx, hcy):
                    hands_touching_ok = True
                if inside(ZONE_REBUT, hcx, hcy):
                    hands_touching_rebut = True

                # 2. General Manual Work (Touching any piece)
                is_touching_piece = False
                for px1, py1, px2, py2 in piece_boxes:
                    if not (hx2 < px1 or hx1 > px2 or hy2 < py1 or hy1 > py2):
                        is_touching_piece = True
                        break
                
                if is_touching_piece:
                    det["mains"] = True

                # 3. Refined Rework Detection (Hand center inside Jig/Tissu box + Outside Machine with 20px Margin)
                # pointPolygonTest < 0 means outside. We use < -20 for a safety buffer.
                dist_to_machine = cv2.pointPolygonTest(ZONE_JUKI, (float(hcx), float(hcy)), True)

                if dist_to_machine < -20:
                    touching_jig = False
                    for jx1, jy1, jx2, jy2 in jig_charge_boxes:
                        if jx1 <= hcx <= jx2 and jy1 <= hcy <= jy2:
                            touching_jig = True
                            break
                    
                    touching_tissu = False
                    for tx1, ty1, tx2, ty2 in tissu_boxes:
                        if tx1 <= hcx <= tx2 and ty1 <= hcy <= ty2:
                            touching_tissu = True
                            break
                    
                    if touching_jig or touching_tissu:
                        mains_in_juki = True # Feeds Rework % accumulator

            # Priority Override: If Maintenance is present, Rework does not count
            if det["maint"]:
                mains_in_juki = False

            last_det_boxes = current_boxes
            update_buffer("jig", det["jig"])
            update_buffer("maint", det["maint"] or maint_in_juki)
            update_buffer("oper", det["oper"])
            update_buffer("mains", det["mains"])
            update_buffer("mains_in", mains_in_juki)
            update_buffer("maint_in", maint_in_juki)
            update_buffer("multi_oper", operator_count >= 2)

            dt = real_dt * cfg.process_every if (cfg.use_tcp or cfg.use_camera) else (1.0 / VIDEO_FPS * cfg.process_every)
            
            # ==========================================================
            # REFACTORED TRIGGER LOGIC: 10s ACTUAL PRESENCE
            # ==========================================================
            trigger_ok = False
            trigger_rebut = False

            # ==========================================================
            # REFACTORED TRIGGER LOGIC: PURE 10s REPEATING TIMER
            # ==========================================================
            trigger_ok = False
            trigger_rebut = False

            # --- ZONE OK LOGIC ---
            if tissu_ok:
                empty_ok_timer = 0
                ok_presence_timer += dt
                if ok_presence_timer >= 5.0:
                    if machine.production_credits > 0:
                        trigger_ok = True
                        machine.production_credits -= 1 # SPEND CREDIT
                        ok_presence_timer = 0 # RESET TO 0 TO ALLOW NEXT 5s
                        print(f"[TRIGGER] OK piece confirmed (5s Stability reached). Credits remaining: {machine.production_credits}")
                    else:
                        # Cap at 5.0 to trigger instantly when credit arrives
                        ok_presence_timer = 5.0
            else:
                empty_ok_timer += dt
                # If gone for more than 1.5s, reset the 5s counter (pass-through)
                if empty_ok_timer >= 1.5: 
                    ok_presence_timer = 0

            # --- ZONE SCRAP LOGIC ---
            if tissu_rebut:
                empty_scrap_timer = 0
                scrap_presence_timer += dt
                if scrap_presence_timer >= 5.0:
                    if machine.production_credits > 0:
                        trigger_rebut = True
                        machine.production_credits -= 1 # SPEND CREDIT
                        scrap_presence_timer = 0 # RESET TO 0 TO ALLOW NEXT 5s
                        print(f"[TRIGGER] SCRAP piece confirmed (5s Stability reached). Credits remaining: {machine.production_credits}")
                    else:
                        # Cap at 5.0 to trigger instantly when credit arrives
                        scrap_presence_timer = 5.0
            else:
                empty_scrap_timer += dt
                # If gone for more than 1.5s, reset the 5s counter
                if empty_scrap_timer >= 1.5: 
                    scrap_presence_timer = 0

            # For live camera, use frame_count as the frame index and real FPS
            frame_idx = frame_count if (cfg.use_tcp or cfg.use_camera) else cap.get(cv2.CAP_PROP_POS_FRAMES)
            effective_fps = fps_display if ((cfg.use_tcp or cfg.use_camera) and fps_display > 0) else VIDEO_FPS
            
            machine.update(is_present("jig"), curr_jig_xy, is_present("jig"), trigger_ok, 
                           trigger_rebut, is_present("maint"), 
                           is_present("oper"), is_present("mains"), 
                           frame_idx, effective_fps,
                           mains_in_juki=is_present("mains_in"), 
                           maint_in_juki=is_present("maint"), # Use global detection for Maint%
                           jig_vide_on_table=jig_vide_on_table,
                           multi_oper=is_present("multi_oper"))

            for log in machine.pending_logs:
                if log[0] == "production":
                    local_id = log_production(log[1], log[2], log[3], log[4], log[5])
                    pipeline.log_production_to_cloud(log[1], log[2], log[3], log[5], local_id)
                elif log[0] == "downtime":
                    log_downtime(log[1], log[2])
                elif log[0] == "muda":
                    # Unified logging: Local + Cloud + MQTT Alert
                    log_downtime(log[1].value, log[2])
                    pipeline.log_and_publish_muda(duration=log[2], classification=log[1])
            machine.pending_logs.clear()

            # ------------------------------------------
            # E. DATA PIPELINE (MQTT & SQL)
            # ------------------------------------------
            # 1. Publish Live Status (Heartbeat for your Dashboard)
            pipeline.publish_realtime_status(
                current_state=machine.current_state,
                is_moving=machine.is_moving,
                downtime=machine.total_stop_s
            )
            # Print latency to console to prove sub-50ms speed
            if frame_count % 10 == 0:
                latency_ms = (time.time() - t_frame_start) * 1000
                print(f"[LATENCY] Frame processed & sent to MQTT in {latency_ms:.1f} ms")

            # 2. Check for State Changes & New Classifications
            # Update previous state (now only used to detect transitions for heartbeat/HUD)
            if machine.current_state != previous_state:
                previous_state = machine.current_state

        # Draw Persistent Boxes (Smooth Visuals)
        for (x1, y1, x2, y2, cname) in last_det_boxes:
            color = get_color(cname)
            cv2.rectangle(display, (x1,y1), (x2,y2), color, 1)
            txt(display, cname, (x1, y1-5), 0.4, color, 1)
            
            # Draw Center Point (Barycenter) for specific classes
            if "tissu" in cname.lower() or "jig_charge" in cname.lower():
                cx, cy = (x1+x2)//2, (y1+y2)//2
                cv2.circle(display, (cx, cy), 4, color, -1) # Solid circle
                cv2.circle(display, (cx, cy), 6, C_WHITE, 1) # White outline

        draw_zone(display, ZONE_OK, (0,180,0), 0.15, "ZONE OK")
        draw_zone(display, ZONE_REBUT, (0,0,180), 0.15, "ZONE REBUT")
        draw_zone(display, ZONE_JUKI, (200,120,0), 0.15, "MACHINE ROI")
        
        m_col = C_EMERALD if machine.is_moving else C_SCRAP
        cv2.circle(display, (ZONE_JUKI[0][0]+15, ZONE_JUKI[0][1]+15), 8, m_col, -1)
        txt(display, "LIVE MOV", (ZONE_JUKI[0][0]+30, ZONE_JUKI[0][1]+22), 0.45, m_col, 1)

        draw_hud(display, frame_count)
        src_label = "TCP/RPi" if cfg.use_tcp else ("LIVE CAM" if cfg.use_camera else "VIDEO")
        txt(display, f"FORVIA SMART MONITOR | {src_label} | FPS: {fps_display:.1f} | {VIDEO_W}x{VIDEO_H} | PROC: 1/{cfg.process_every}", (10, cfg.display_h-10), 0.4, C_GREY, 1)
        base_display = display  # No copy needed, display is already a new array from resize

    if 'base_display' in locals():
        render_display = base_display.copy()  # Only this copy is needed for point overlay
        # Draw currently collecting points (large and visible)
        for i, p in enumerate(collected_points):
            # Scale for display
            dx = int(p[0] * (cfg.display_w / cfg.roi_ref_w))
            dy = int(p[1] * (cfg.display_h / cfg.roi_ref_h))
            cv2.circle(render_display, (dx, dy), 6, (0, 255, 255), -1)
            cv2.circle(render_display, (dx, dy), 8, (255, 255, 255), 2)
            txt(render_display, str(i+1), (dx+10, dy-5), 0.5, (0, 255, 255), 2)
        if len(collected_points) > 1:
            pts = np.array([(int(p[0]*(cfg.display_w/cfg.roi_ref_w)), int(p[1]*(cfg.display_h/cfg.roi_ref_h))) for p in collected_points], dtype=np.int32)
            cv2.polylines(render_display, [pts], False, (0, 255, 255), 2)
        if len(collected_points) > 0:
            txt(render_display, f"ROI SNIPER: {len(collected_points)} pts | 'p'=print 'c'=clear", (10, 25), 0.5, (0, 255, 255), 2)

        cv2.imshow("FORVIA - SMART Monitor", render_display)

    # waitKey(1) = minimal delay for live camera (real-time), still 1ms for video
    key = cv2.waitKey(1) & 0xFF
    key_char = chr(key).lower() if 32 <= key < 127 else ""

    if key_char == "q": break
    elif key_char == " ": paused = not paused
    elif key_char == "p":
        points_str = str(tuple(collected_points))
        print("\n--- COLLECTED ROI POINTS (4K FORMAT) ---")
        print(points_str)
        print("----------------------------------------\n")
        try:
            import subprocess
            subprocess.run("clip", input=points_str, text=True, check=True)
            print("[CLIPBOARD] Points copied to clipboard automatically!\n")
        except Exception as e:
            print(f"[CLIPBOARD] Failed to copy to clipboard: {e}\n")
    elif key_char == "c":
        collected_points = []
        print("Points Cleared.")
    elif key_char == "z":
        print("\n========== ZONE DEBUG (Display Coords) ==========")
        print(f"ZONE_OK    corners: {ZONE_OK.tolist()}")
        print(f"ZONE_REBUT corners: {ZONE_REBUT.tolist()}")
        print(f"ZONE_JUKI  corners: {ZONE_JUKI.tolist()}")
        print(f"\nYour ROIs were calibrated for the VIDEO file.")
        print(f"For the LIVE CAMERA you need to re-draw them:")
        print(f"  1. Click corners of the OK zone -> press 'p'")
        print(f"  2. Press 'c' to clear -> click REBUT corners -> 'p'")
        print(f"  3. Press 'c' -> click MACHINE corners -> 'p'")
        print(f"  4. Paste the printed tuples into roi_ok/roi_scrap/roi_machine")
        print("=================================================\n")

if cfg.use_tcp:
    cap.stop()
elif cfg.use_camera:
    cap.stop()
    raw_cap.release()
else:
    cap.release()
cv2.destroyAllWindows()