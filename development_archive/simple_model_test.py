"""
YOLO Real-Time Inference Script
Usage:
    python yolo_inference.py --model path/to/best.pt --source path/to/video.mp4
    python yolo_inference.py --model path/to/best.pt --source 0   # webcam
"""

import os
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["OPENBLAS_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"

import argparse
import sys
import time
from pathlib import Path

import cv2
import torch
from ultralytics import YOLO


# ─────────────────────────── CLI ────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run YOLO inference on a video file or webcam."
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=Path(r"c:\Users\pc\OneDrive\Bureau\VISION\best (1).pt"),
        help="Path to the YOLO .pt weights file.",
    )
    parser.add_argument(
        "--source",
        default=r"c:\Users\pc\OneDrive\Bureau\VISION\WIN_20260408_18_49_13_Pro.mp4",
        help="Video file path, or integer index for webcam (e.g. 0).",
    )
    parser.add_argument("--conf",    type=float, default=0.35,  help="Confidence threshold.")
    parser.add_argument("--iou",     type=float, default=0.45,  help="IoU threshold for NMS.")
    parser.add_argument("--imgsz",   type=int,   default=640,   help="Inference image size.")
    parser.add_argument("--skip",    type=int,   default=8,     help="Process 1 in every N frames.")
    parser.add_argument("--maxw",    type=int,   default=1280,  help="Max display width (px).")
    parser.add_argument("--loop",    action="store_true",       help="Loop video when it ends.")
    parser.add_argument("--threads", type=int,   default=2,     help="PyTorch CPU thread cap.")
    return parser.parse_args()


# ─────────────────────────── HELPERS ────────────────────────────────────────

def resolve_source(source: str):
    """Return an int (webcam index) or a validated Path for a video file."""
    try:
        return int(source)
    except ValueError:
        p = Path(source)
        if not p.exists():
            raise FileNotFoundError(f"Video not found: {p}")
        return p


def load_model(model_path: Path, device: str) -> YOLO:
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")

    print(f"[INFO] Loading model: {model_path}")
    model = YOLO(str(model_path))
    model.overrides["verbose"] = False   # silence per-frame logs globally
    print(f"[INFO] Model loaded — running on {device.upper()}")
    return model


def open_capture(source) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(source if isinstance(source, int) else str(source))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open source: {source}")
    return cap


def resize_to_fit(frame, max_width: int):
    h, w = frame.shape[:2]
    if w <= max_width:
        return frame
    scale = max_width / w
    return cv2.resize(frame, (max_width, int(h * scale)), interpolation=cv2.INTER_LINEAR)


def dynamic_line_width(frame_width: int) -> int:
    """Scale bounding-box line width to the display resolution."""
    return max(1, frame_width // 320)


# ─────────────────────────── MAIN LOOP ──────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    # ── Device setup ────────────────────────────────────────────────────────
    if not torch.cuda.is_available():
        print("[WARN] CUDA not detected — falling back to CPU.")
        device, half = "cpu", False
    else:
        device, half = "cuda", True
        print(f"[INFO] GPU: {torch.cuda.get_device_name(0)}")

    torch.set_num_threads(args.threads)

    # ── Model & source ───────────────────────────────────────────────────────
    model  = load_model(args.model, device)
    source = resolve_source(str(args.source))
    cap    = open_capture(source)

    fps_cap = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    is_file = isinstance(source, Path)

    print(f"[INFO] Source FPS: {fps_cap:.1f}  |  Total frames: {total_frames or '∞'}")
    print("[INFO] Press 'q' to quit, 'r' to restart, 'p' to pause.")

    # ── State ────────────────────────────────────────────────────────────────
    frame_count = 0
    processed   = 0
    paused      = False
    t_start     = time.perf_counter()
    inference_ms_avg = 0.0

    window_title = "YOLO Inference  |  q=quit  r=restart  p=pause"
    cv2.namedWindow(window_title, cv2.WINDOW_NORMAL)

    while True:
        if paused:
            key = cv2.waitKey(50) & 0xFF
            if key == ord('q'):
                break
            if key == ord('p'):
                paused = False
            continue

        ret = cap.grab()

        if not ret:
            if args.loop and is_file:
                print("[INFO] End of video — restarting.")
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                frame_count = 0
                continue
            else:
                print("[INFO] End of stream.")
                break

        frame_count += 1

        # ── Frame skipping ───────────────────────────────────────────────────
        if frame_count % args.skip != 0:
            continue

        ret, frame = cap.retrieve()
        if not ret or frame is None:
            continue

        # ── Inference ────────────────────────────────────────────────────────
        frame_small = cv2.resize(frame, (640, 360))
        t0 = time.perf_counter()
        results = model.predict(
            frame_small,
            conf=args.conf,
            iou=args.iou,
            imgsz=args.imgsz,
            device=device,
            half=half,
        )
        inference_ms = (time.perf_counter() - t0) * 1000
        inference_ms_avg = 0.9 * inference_ms_avg + 0.1 * inference_ms   # EMA

        # ── Visualise ────────────────────────────────────────────────────────
        annotated = results[0].plot(line_width=dynamic_line_width(frame_small.shape[1]))
        annotated = resize_to_fit(annotated, args.maxw)

        # ── OSD overlay ─────────────────────────────────────────────────────
        processed += 1
        elapsed   = time.perf_counter() - t_start
        disp_fps  = processed / elapsed if elapsed > 0 else 0
        n_dets    = len(results[0].boxes)

        osd_lines = [
            f"Display FPS : {disp_fps:.1f}",
            f"Inference   : {inference_ms_avg:.1f} ms",
            f"Detections  : {n_dets}",
            f"Frame       : {frame_count}" + (f"/{total_frames}" if total_frames else ""),
        ]
        for i, line in enumerate(osd_lines):
            cv2.putText(
                annotated, line,
                (10, 24 + i * 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65,
                (0, 255, 0), 2, cv2.LINE_AA,
            )

        cv2.imshow(window_title, annotated)

        # ── Key handling ─────────────────────────────────────────────────────
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        if key == ord('r') and is_file:
            print("[INFO] Restarting video.")
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            frame_count = 0
            processed   = 0
            t_start     = time.perf_counter()
        if key == ord('p'):
            paused = True
            print("[INFO] Paused. Press 'p' to resume.")

    # ── Summary ──────────────────────────────────────────────────────────────
    elapsed = time.perf_counter() - t_start
    print(f"\n[INFO] Done. Processed {processed} frames in {elapsed:.1f}s "
          f"({processed / elapsed:.1f} fps effective).")

    cap.release()
    cv2.destroyAllWindows()


# ─────────────────────────── ENTRY ──────────────────────────────────────────

if __name__ == "__main__":
    try:
        run(parse_args())
    except (FileNotFoundError, RuntimeError) as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user.")
        cv2.destroyAllWindows()
        sys.exit(0)