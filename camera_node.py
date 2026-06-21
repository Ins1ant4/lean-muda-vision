"""
FORVIA Camera Node - Raspberry Pi Sender
Captures frames from the Pi camera, JPEG-compresses them, and sends to the laptop over TCP.
JPEG compression reduces bandwidth from ~80 MB/s to ~1.5 MB/s (50x reduction).
"""
import cv2
import socket
import struct
import pickle
import time
import platform

# ---- CONFIGURATION ----
host_ip = '192.168.137.1'  # The Windows laptop IP
port = 9999
JPEG_QUALITY = 80  # 1-100: higher = better quality but more bandwidth
CAMERA_INDEX = 0   # Pi camera index
CAMERA_W = 1280
CAMERA_H = 720
TARGET_FPS = 30

cap = None

def init_camera():
    global cap
    if cap is not None:
        try:
            cap.release()
        except:
            pass
            
    # Force V4L2 backend on Linux (Raspberry Pi) to avoid GStreamer pipeline issues
    if platform.system() == 'Linux':
        print(f"Initializing camera index {CAMERA_INDEX} via V4L2 backend...", flush=True)
        cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_V4L2)
    else:
        print(f"Initializing camera index {CAMERA_INDEX} (Windows/Mac)...", flush=True)
        cap = cv2.VideoCapture(CAMERA_INDEX)
        
    if not cap.isOpened():
        print(f"Error: Camera index {CAMERA_INDEX} could not be opened.", flush=True)
        return False
        
    # Try to set capture format to MJPG to allow camera hardware to stream 30+ FPS
    try:
        print("Setting camera capture format to MJPG...", flush=True)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
    except Exception as e:
        print(f"Warning: Could not set MJPEG capture format: {e}", flush=True)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_H)
    cap.set(cv2.CAP_PROP_FPS, TARGET_FPS)
    
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Camera parameters queried: {actual_w}x{actual_h}", flush=True)
    
    # Test read to verify video stream is actually flowing
    print("Testing camera frame capture...", flush=True)
    ret, test_frame = cap.read()
    if not ret or test_frame is None or actual_w == 0 or actual_h == 0:
        print("Error: Camera initialized but failed to capture a test frame (data stream error).", flush=True)
        return False
        
    print(f"Camera successfully initialized and verified: {actual_w}x{actual_h}", flush=True)
    return True

# Initialize camera on startup
init_camera()

encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]

while True:
    # Ensure camera is opened and capturing before trying to connect
    if cap is None or not cap.isOpened():
        print("Camera is not active. Retrying camera initialization in 3 seconds...", flush=True)
        init_camera()
        time.sleep(3)
        continue

    client_socket = None
    try:
        # ---- CONNECT TO LAPTOP ----
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        # Disable Nagle's algorithm for low-latency streaming
        try:
            client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception as e:
            print(f"Warning: Could not set TCP_NODELAY option: {e}", flush=True)
            
        print(f"Connecting to Central Server ({host_ip}:{port})...", flush=True)
        client_socket.connect((host_ip, port))
        print("Connected successfully! Starting stream...", flush=True)
        
        frame_count = 0
        fps_timer = time.time()
        frame_interval = 1.0 / TARGET_FPS
        
        while cap.isOpened():
            t_start = time.time()
            
            # Read frame
            ret, frame = cap.read()
            if not ret or frame is None:
                print("Camera read failed inside stream loop. Re-initializing camera...", flush=True)
                try:
                    cap.release()
                except:
                    pass
                break
            
            # JPEG compress the frame
            success_encode, encoded = cv2.imencode('.jpg', frame, encode_param)
            if not success_encode or encoded is None:
                print("JPEG compression failed, skipping frame.", flush=True)
                continue
            
            # Convert JPEG numpy array to raw bytes and send with size header (bypasses pickle CPU overhead)
            data = encoded.tobytes()
            message = struct.pack("Q", len(data)) + data
            
            # Send data
            client_socket.sendall(message)
            
            frame_count += 1
            elapsed = time.time() - fps_timer
            if elapsed >= 5.0:
                fps = frame_count / elapsed
                size_kb = len(data) / 1024
                print(f"Streaming: {fps:.1f} FPS | {size_kb:.0f} KB/frame | {size_kb * fps / 1024:.1f} MB/s", flush=True)
                frame_count = 0
                fps_timer = time.time()
            
            # Throttle to target FPS
            sleep_time = frame_interval - (time.time() - t_start)
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\nStopping...", flush=True)
        break
    except (socket.error, BrokenPipeError, ConnectionResetError) as e:
        print(f"Connection error: {e}. Reconnecting in 3 seconds...", flush=True)
        if client_socket:
            try:
                client_socket.close()
            except:
                pass
        time.sleep(3)
    except Exception as e:
        print(f"Unexpected error: {e}. Reconnecting in 3 seconds...", flush=True)
        if client_socket:
            try:
                client_socket.close()
            except:
                pass
        time.sleep(3)

if cap is not None:
    cap.release()
print("Camera node shutdown complete.", flush=True)
