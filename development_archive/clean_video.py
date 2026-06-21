import os
import re

path = r"c:\Users\pc\OneDrive\Bureau\VISION\vision_loop_video.py"

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Remove threading and TCP imports
content = re.sub(
    r"import threading\nimport socket\nimport struct\nimport pickle\n",
    "",
    content
)

# 2. Remove CameraReader and TCPReader
content = re.sub(
    r"# ==========================================\n# THREADED CAMERA READER \(eliminates capture blocking\)\n# ==========================================\nclass CameraReader:.*?def isOpened\(self\):\n        return self\.connected\n\n",
    "",
    content,
    flags=re.DOTALL
)

# 3. Remove SOURCE MODE config
content = re.sub(
    r"    # ---- SOURCE MODE ----\n    # Priority: use_tcp > use_camera > video file\n    use_tcp:       bool  = True       # True = receive frames from Raspberry Pi over TCP\n    tcp_host:      str   = '192\.168\.137\.1'  # Laptop IP on the shared network\n    tcp_port:      int   = 9999\n\n    use_camera:    bool  = False      # True = live USB camera \(ignored if use_tcp=True\)\n    camera_index:  int   = 1          # USB camera index \(0 = laptop webcam, 1 = external USB 4K\)\n    camera_w:      int   = 1920       # 1080p = best performance/quality balance\n    camera_h:      int   = 1080       # \(4K decode is too slow for real-time\)\n    camera_fps:    int   = 30         # Requested FPS from camera\n\n",
    "",
    content
)

# 4. Remove Source Init
content = re.sub(
    r"raw_cap = None  # Only used for camera/video modes\n\nif cfg\.use_tcp:\n    # ---- RASPBERRY PI TCP RECEIVER ----\n.*?else:\n    # ---- VIDEO FILE ----\n    raw_cap = cv2\.VideoCapture\(cfg\.video_path\)\n    cap = raw_cap\n    source_name = cfg\.video_path\n    if not raw_cap\.isOpened\(\):\n        print\(f\"ERROR: Cannot open \{source_name\}\"\); raise SystemExit\n    VIDEO_W = int\(raw_cap\.get\(cv2\.CAP_PROP_FRAME_WIDTH\)\)\n    VIDEO_H = int\(raw_cap\.get\(cv2\.CAP_PROP_FRAME_HEIGHT\)\)\n    VIDEO_FPS = raw_cap\.get\(cv2\.CAP_PROP_FPS\) or 30\.0\n    print\(f\"Source  : \{source_name\}\"\)\n    print\(f\"Resolution: \{VIDEO_W\}x\{VIDEO_H\} @ \{VIDEO_FPS:\.1f\} FPS\"\)\n",
    r"""# ---- VIDEO FILE ----
cap = cv2.VideoCapture(cfg.video_path)
source_name = cfg.video_path
if not cap.isOpened():
    print(f"ERROR: Cannot open {source_name}"); raise SystemExit
VIDEO_W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
VIDEO_H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
VIDEO_FPS = cap.get(cv2.CAP_PROP_FPS) or 30.0
print(f"Source  : {source_name}")
print(f"Resolution: {VIDEO_W}x{VIDEO_H} @ {VIDEO_FPS:.1f} FPS")
""",
    content,
    flags=re.DOTALL
)

# 5. Fix Main loop read
content = re.sub(
    r"        success, frame = cap\.read\(\)\n        if not success or frame is None:\n            if cfg\.use_tcp or cfg\.use_camera:\n                time\.sleep\(0\.005\)  # Brief sleep to avoid busy-waiting\n                continue\n            else:\n                break  # End of video file\n        \n        # Auto-detect resolution from first TCP frame\n        if cfg\.use_tcp and VIDEO_W == 0 and frame is not None:\n            VIDEO_H, VIDEO_W = frame\.shape\[:2\]\n            VIDEO_FPS = 30\.0\n            print\(f\"TCP Frame detected: \{VIDEO_W\}x\{VIDEO_H\}\"\)\n        frame_count \+= 1\n",
    r"""        success, frame = cap.read()
        if not success or frame is None:
            break  # End of video file
        frame_count += 1
""",
    content
)

# 6. Fix timing
content = re.sub(
    r"            dt = real_dt \* cfg\.process_every if \(cfg\.use_tcp or cfg\.use_camera\) else \(1\.0 / VIDEO_FPS \* cfg\.process_every\)\n            current_video_s = time\.time\(\) - loop_start_time if \(cfg\.use_tcp or cfg\.use_camera\) else \(cap\.get\(cv2\.CAP_PROP_POS_FRAMES\) / max\(1\.0, VIDEO_FPS\)\)",
    r"""            dt = 1.0 / VIDEO_FPS * cfg.process_every
            current_video_s = cap.get(cv2.CAP_PROP_POS_FRAMES) / max(1.0, VIDEO_FPS)""",
    content
)

# 7. Fix frame idx
content = re.sub(
    r"            # For live camera, use frame_count as the frame index and real FPS\n            frame_idx = frame_count if \(cfg\.use_tcp or cfg\.use_camera\) else cap\.get\(cv2\.CAP_PROP_POS_FRAMES\)\n            effective_fps = fps_display if \(\(cfg\.use_tcp or cfg\.use_camera\) and fps_display > 0\) else VIDEO_FPS",
    r"""            frame_idx = cap.get(cv2.CAP_PROP_POS_FRAMES)
            effective_fps = VIDEO_FPS""",
    content
)

# 8. Fix HUD label
content = re.sub(
    r"        src_label = \"TCP/RPi\" if cfg\.use_tcp else \(\"LIVE CAM\" if cfg\.use_camera else \"VIDEO\"\)",
    r"""        src_label = "VIDEO\"""",
    content
)

# 9. Fix Cleanup
content = re.sub(
    r"if cfg\.use_tcp:\n    cap\.stop\(\)\nelif cfg\.use_camera:\n    cap\.stop\(\)\n    raw_cap\.release\(\)\nelse:\n    cap\.release\(\)",
    r"cap.release()",
    content
)

# Write back
with open(path, "w", encoding="utf-8") as f:
    f.write(content)
