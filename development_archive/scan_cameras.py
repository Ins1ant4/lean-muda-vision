import cv2

print("Scanning for cameras (0-9)...")
for i in range(10):
    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
    if cap.isOpened():
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        name = cap.getBackendName()
        
        # Try setting 4K to see if this camera supports it
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 3840)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 2160)
        w4k = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h4k = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        supports_4k = "YES 4K!" if (w4k >= 3840 and h4k >= 2160) else f"no (max {w4k}x{h4k})"
        print(f"  Camera {i}: FOUND | Default: {w}x{h} @ {fps}fps | 4K support: {supports_4k} | Backend: {name}")
        cap.release()
    else:
        print(f"  Camera {i}: not found")
        cap.release()

print("\nDone.")
