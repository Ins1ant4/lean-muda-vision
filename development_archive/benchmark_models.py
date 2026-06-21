"""
=============================================================
  FORVIA – YOLO Model Benchmark Comparator  (Multi-Video)
  Compares: best.pt  best1.pt  best2.pt  best8.pt
=============================================================
Output
------
  • Console : real-time progress + final ranked table
  • File    : benchmark_results.txt  (full report, next to script)

Usage
-----
  # Test on two specific videos (spread-sampled):
  python benchmark_models.py --videos WIN_20260408_17_14_58_Pro.mp4 WIN_20260518_12_21_14_Pro.mp4

  # Limit frames per video (speeds things up on large files):
  python benchmark_models.py --videos vid1.mp4 vid2.mp4 --frames 300

  # Change confidence / skip rate:
  python benchmark_models.py --videos vid1.mp4 --conf 0.4 --skip 4
"""

import os
import sys
import time
import argparse
import textwrap
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import cv2
import torch
from ultralytics import YOLO

# ─────────────────────────── CONFIG ──────────────────────────────────────────

SCRIPT_DIR  = Path(__file__).parent
REPORT_PATH = SCRIPT_DIR / "benchmark_results.txt"

MODELS = [
    SCRIPT_DIR / "best.pt",
    SCRIPT_DIR / "best1.pt",
    SCRIPT_DIR / "best2.pt",
    SCRIPT_DIR / "best8.pt",
]

# Classes that are critical for your production logic
CRITICAL_CLASSES = {"jig_charge", "jig_vide", "tissu", "mains", "operateur", "maintenance"}

# ─────────────────────────── DATA STRUCTURES ─────────────────────────────────

@dataclass
class ModelStats:
    name: str
    inference_times_ms: List[float]           = field(default_factory=list)
    confidences:        List[float]           = field(default_factory=list)
    detections_per_frame: List[int]           = field(default_factory=list)
    class_counts:       Dict[str, int]        = field(default_factory=lambda: defaultdict(int))
    class_confidences:  Dict[str, List[float]]= field(default_factory=lambda: defaultdict(list))
    frames_with_zero_det: int = 0
    total_frames:         int = 0
    videos_tested:  List[str] = field(default_factory=list)   # which videos contributed

    # ── Derived ───────────────────────────────────────────────────────────
    @property
    def avg_inference_ms(self):
        return sum(self.inference_times_ms) / len(self.inference_times_ms) if self.inference_times_ms else 0

    @property
    def p95_inference_ms(self):
        if not self.inference_times_ms: return 0
        s = sorted(self.inference_times_ms)
        return s[int(len(s) * 0.95)]

    @property
    def avg_conf(self):
        return sum(self.confidences) / len(self.confidences) if self.confidences else 0

    @property
    def avg_dets(self):
        return sum(self.detections_per_frame) / len(self.detections_per_frame) if self.detections_per_frame else 0

    @property
    def miss_rate(self):
        return self.frames_with_zero_det / self.total_frames if self.total_frames else 0

    @property
    def effective_fps(self):
        return 1000 / self.avg_inference_ms if self.avg_inference_ms else 0

    def critical_recall(self) -> Dict[str, float]:
        result = {}
        for cls in CRITICAL_CLASSES:
            confs = self.class_confidences.get(cls, [])
            result[cls] = sum(confs) / len(confs) if confs else 0.0
        return result


# ─────────────────────────── SCORING ─────────────────────────────────────────

def score_model(stats: ModelStats) -> float:
    """
    Composite score (higher = better).
      40% — avg detection confidence
      35% — critical class coverage (avg conf across 6 key classes)
      15% — speed (effective FPS, capped at 60)
      10% — miss-rate penalty
    """
    conf_score   = stats.avg_conf * 100
    speed_score  = min(stats.effective_fps, 60) / 60 * 100
    miss_penalty = stats.miss_rate * 100
    crit_avg     = (sum(stats.critical_recall().values()) / len(CRITICAL_CLASSES)) * 100
    return round(0.40*conf_score + 0.35*crit_avg + 0.15*speed_score - 0.10*miss_penalty, 2)


# ─────────────────────────── HELPERS ─────────────────────────────────────────

def bar(value: float, total: float = 1.0, width: int = 20, fill="█", empty="░") -> str:
    ratio = min(max(value / total if total else 0, 0), 1)
    filled = int(ratio * width)
    return fill * filled + empty * (width - filled)

def pct(v: float)  -> str: return f"{v*100:.1f}%"
def ms(v: float)   -> str: return f"{v:.1f} ms"
def col_width(items, header): return max(len(header), max((len(str(i)) for i in items), default=0)) + 2


def build_seek_positions(cap: cv2.VideoCapture, n_frames: int, skip: int) -> List[int]:
    """
    Return a list of video frame indices spread evenly across the whole video.
    This ensures we sample diverse production conditions (not just the first N seconds).
    """
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total <= 0:
        # Cannot determine length (live stream etc.) — fall back to sequential
        return list(range(0, n_frames * skip, skip))

    # We want `n_frames` processed frames, each `skip` apart, spread across `total` frames.
    # Divide video into n_frames equally spaced segments and pick one frame per segment.
    segment_size = total / n_frames
    positions = []
    for i in range(n_frames):
        # Pick the first frame of each segment that is divisible by `skip`
        raw = int(i * segment_size)
        aligned = (raw // skip) * skip          # snap to nearest skip boundary
        positions.append(max(0, min(aligned, total - 1)))
    return positions


# ─────────────────────────── SINGLE-VIDEO RUNNER ─────────────────────────────

def run_model_on_video(
    model: YOLO,
    model_names: dict,
    video_path: Path,
    stats: ModelStats,
    max_frames: int,
    skip: int,
    conf: float,
    imgsz: int,
    device: str,
) -> None:
    """
    Run `model` on `video_path` and accumulate results into `stats`.
    Uses spread sampling when max_frames > 0.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"  [WARN] Cannot open {video_path.name} – skipping.")
        return

    total_vid_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps_vid          = cap.get(cv2.CAP_PROP_FPS) or 30

    # Build seek positions (spread or sequential)
    if max_frames > 0 and total_vid_frames > 0:
        seek_positions = build_seek_positions(cap, max_frames, skip)
        use_seek = True
    else:
        seek_positions = []
        use_seek = False

    processed  = 0
    last_print = time.perf_counter()
    target     = max_frames if max_frames > 0 else (total_vid_frames // skip)

    if use_seek:
        for pos in seek_positions:
            cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue

            frame_disp = cv2.resize(frame, (1280, 720))
            t0 = time.perf_counter()
            results = model.predict(source=frame_disp, conf=conf, imgsz=imgsz,
                                    device=device, verbose=False)
            inf_ms = (time.perf_counter() - t0) * 1000

            _accumulate(results, inf_ms, stats, model_names)
            processed += 1

            now = time.perf_counter()
            if now - last_print >= 2.0:
                _print_progress(processed, target, inf_ms,
                                len(results[0].boxes), video_path.name)
                last_print = now
    else:
        # Sequential (no frame limit)
        frame_idx = 0
        while cap.isOpened():
            ret = cap.grab()
            if not ret: break
            frame_idx += 1
            if frame_idx % skip != 0: continue
            ret, frame = cap.retrieve()
            if not ret or frame is None: continue

            frame_disp = cv2.resize(frame, (1280, 720))
            t0 = time.perf_counter()
            results = model.predict(source=frame_disp, conf=conf, imgsz=imgsz,
                                    device=device, verbose=False)
            inf_ms = (time.perf_counter() - t0) * 1000

            _accumulate(results, inf_ms, stats, model_names)
            processed += 1

            now = time.perf_counter()
            if now - last_print >= 2.0:
                _print_progress(processed, target, inf_ms,
                                len(results[0].boxes), video_path.name)
                last_print = now

    cap.release()
    stats.videos_tested.append(video_path.name)
    print(f"  ✓ {video_path.name}: {processed} frames  "
          f"(avg {stats.avg_inference_ms:.1f}ms so far)")


def _accumulate(results, inf_ms, stats, model_names):
    boxes = results[0].boxes
    n_det = len(boxes)
    stats.inference_times_ms.append(inf_ms)
    stats.detections_per_frame.append(n_det)
    stats.total_frames += 1
    if n_det == 0:
        stats.frames_with_zero_det += 1
    for box in boxes:
        conf_val = float(box.conf[0])
        cls_name = model_names[int(box.cls[0])].lower()
        stats.confidences.append(conf_val)
        stats.class_counts[cls_name] += 1
        stats.class_confidences[cls_name].append(conf_val)


def _print_progress(processed, target, inf_ms, n_det, vid_name):
    b = bar(processed, target, 25) if target > 0 else "█" * 10
    short = vid_name[:22] + ".." if len(vid_name) > 24 else vid_name
    print(f"  [{b}] {processed}/{target or '?'} frames | "
          f"{inf_ms:.0f}ms | dets:{n_det}  [{short}]")


# ─────────────────────────── MAIN BENCHMARK ──────────────────────────────────

def run_benchmark(
    video_paths: List[Path],
    max_frames: int,
    conf: float,
    skip: int,
    imgsz: int,
) -> List[ModelStats]:

    device = "cuda" if torch.cuda.is_available() else "cpu"

    print(f"\n{'='*66}")
    print(f"  FORVIA Multi-Video Model Benchmark  |  Device: {device.upper()}")
    for vp in video_paths:
        total = int(cv2.VideoCapture(str(vp)).get(cv2.CAP_PROP_FRAME_COUNT))
        size_gb = vp.stat().st_size / 1e9
        print(f"  Video : {vp.name}  ({size_gb:.1f} GB, ~{total} frames)")
    print(f"  Frames/video: {'ALL' if max_frames == 0 else max_frames} (spread-sampled)")
    print(f"  Conf  : {conf}  |  Skip: 1/{skip}  |  imgsz: {imgsz}")
    print(f"{'='*66}\n")

    all_stats: List[ModelStats] = []

    for model_path in MODELS:
        if not model_path.exists():
            print(f"[WARN] {model_path.name} not found – skipping.\n")
            continue

        stats = ModelStats(name=model_path.name)
        dash  = "─" * max(0, 44 - len(model_path.name))
        print(f"─── Testing {model_path.name} {dash}")

        # Load model once, test across all videos
        model = YOLO(str(model_path))
        model.overrides["verbose"] = False

        # GPU warm-up
        if device == "cuda":
            dummy = torch.zeros((1, 3, imgsz, imgsz), device=device)
            model.predict(source=dummy, imgsz=imgsz, conf=conf, device=device, verbose=False)
            del dummy

        t_model_start = time.perf_counter()

        for vp in video_paths:
            run_model_on_video(
                model=model,
                model_names=model.names,
                video_path=vp,
                stats=stats,
                max_frames=max_frames,
                skip=skip,
                conf=conf,
                imgsz=imgsz,
                device=device,
            )

        elapsed = time.perf_counter() - t_model_start
        print(f"  ── Total: {stats.total_frames} frames across {len(video_paths)} videos "
              f"in {elapsed:.1f}s  |  avg {stats.avg_inference_ms:.1f}ms  "
              f"|  {stats.effective_fps:.1f} eff. FPS\n")

        del model
        all_stats.append(stats)

    return all_stats


# ─────────────────────────── REPORT ──────────────────────────────────────────

def build_report(all_stats: List[ModelStats], video_paths: List[Path]) -> str:
    if not all_stats:
        return "No results to report."

    scores = {s.name: score_model(s) for s in all_stats}
    ranked = sorted(all_stats, key=lambda s: scores[s.name], reverse=True)
    sep    = "=" * 70
    sep2   = "-" * 70
    lines  = []
    def add(*args): lines.extend(args)

    add(sep,
        "  FORVIA YOLO MODEL BENCHMARK – MULTI-VIDEO RESULTS",
        sep,
        f"  Videos tested ({len(video_paths)}):")
    for vp in video_paths:
        add(f"    • {vp.name}")
    add("")

    # ── Summary ranking table ─────────────────────────────────────────────
    add("RANKING  (Higher score = Better)", sep2)
    headers = ["Rank", "Model", "Score", "Avg Conf", "Eff FPS", "Miss%", "Avg Dets", "Frames"]
    rows = []
    for rank, s in enumerate(ranked, 1):
        rows.append([
            f"#{rank}", s.name, f"{scores[s.name]:.1f}",
            pct(s.avg_conf), f"{s.effective_fps:.1f}",
            pct(s.miss_rate), f"{s.avg_dets:.1f}", str(s.total_frames),
        ])
    cw = [col_width([r[i] for r in rows], headers[i]) for i in range(len(headers))]
    add("  ".join(h.ljust(cw[i]) for i, h in enumerate(headers)), sep2)
    for r in rows:
        add("  ".join(str(v).ljust(cw[i]) for i, v in enumerate(r)))
    add("")

    # ── Per-model detail ──────────────────────────────────────────────────
    for s in ranked:
        add(sep2, f"  {s.name}   [Score: {scores[s.name]:.1f}]", sep2)
        add(f"  Videos : {', '.join(s.videos_tested)}",
            f"  Inference Speed:",
            f"    Avg : {ms(s.avg_inference_ms)}  ({s.effective_fps:.1f} eff. FPS)",
            f"    P95 : {ms(s.p95_inference_ms)}",
            f"  Detection Quality:",
            f"    Avg confidence   : {pct(s.avg_conf)}",
            f"    Avg dets / frame : {s.avg_dets:.2f}",
            f"    Miss rate        : {pct(s.miss_rate)}  "
            f"({s.frames_with_zero_det}/{s.total_frames} frames with 0 dets)",
            f"  Critical Class Coverage:")

        crit = s.critical_recall()
        for cls in sorted(CRITICAL_CLASSES):
            c       = crit.get(cls, 0)
            det_cnt = s.class_counts.get(cls, 0)
            add(f"    {cls:<20} {bar(c,1.0,15)}  avg_conf={pct(c)}  dets={det_cnt}")

        add(f"\n  All Detected Classes:")
        if s.class_counts:
            for cls, cnt in sorted(s.class_counts.items(), key=lambda x: -x[1]):
                avg_c = sum(s.class_confidences[cls]) / len(s.class_confidences[cls])
                add(f"    {cls:<25} {cnt:>6} detections  avg_conf={pct(avg_c)}")
        else:
            add("    (none)")
        add("")

    # ── Verdict ───────────────────────────────────────────────────────────
    winner = ranked[0]
    add(sep, f"  ★  BEST MODEL: {winner.name}  (Score: {scores[winner.name]:.1f})", sep)

    reasons = []
    if winner.avg_conf   == max(s.avg_conf   for s in all_stats): reasons.append("highest avg confidence")
    if winner.miss_rate  == min(s.miss_rate  for s in all_stats): reasons.append("lowest miss rate")
    if winner.effective_fps == max(s.effective_fps for s in all_stats): reasons.append("fastest inference")
    crit_scores = {s.name: sum(s.critical_recall().values()) for s in all_stats}
    if crit_scores[winner.name] == max(crit_scores.values()):    reasons.append("best critical class coverage")
    if reasons: add(f"  Reasons: {', '.join(reasons)}.")
    add("")

    # ── Speed vs accuracy note ────────────────────────────────────────────
    fastest  = min(all_stats, key=lambda s: s.avg_inference_ms)
    most_acc = max(all_stats, key=lambda s: s.avg_conf)
    if fastest.name != most_acc.name:
        add("  TRADE-OFF NOTE:",
            f"    Fastest   : {fastest.name}  ({fastest.avg_inference_ms:.1f}ms avg  |  {fastest.effective_fps:.1f} FPS)",
            f"    Most Acc. : {most_acc.name}  ({pct(most_acc.avg_conf)} avg conf)",
            f"    Your pipeline needs only ~7.5 FPS (30fps÷4) — accuracy should win.")
    add("")

    return "\n".join(lines)


# ─────────────────────────── CLI ─────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(__doc__))
    parser.add_argument("--videos", nargs="+", type=Path,
                        default=[SCRIPT_DIR / "VideoPFE.mp4"],
                        help="One or more video paths to benchmark on.")
    parser.add_argument("--frames", type=int, default=300,
                        help="Processed frames per video (0=all). Default: 300")
    parser.add_argument("--conf",   type=float, default=0.35,
                        help="Confidence threshold (default: 0.35)")
    parser.add_argument("--skip",   type=int, default=4,
                        help="Process 1 frame in every N (default: 4)")
    parser.add_argument("--imgsz",  type=int, default=640,
                        help="YOLO inference image size (default: 640)")
    return parser.parse_args()


# ─────────────────────────── ENTRY ───────────────────────────────────────────

if __name__ == "__main__":
    args = parse_args()

    video_paths = []
    for vp in args.videos:
        if not vp.is_absolute():
            vp = SCRIPT_DIR / vp
        if not vp.exists():
            print(f"[ERROR] Video not found: {vp}")
            sys.exit(1)
        video_paths.append(vp)

    all_stats = run_benchmark(
        video_paths=video_paths,
        max_frames=args.frames,
        conf=args.conf,
        skip=args.skip,
        imgsz=args.imgsz,
    )

    report = build_report(all_stats, video_paths)
    print("\n" + report)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"[INFO] Full report saved → {REPORT_PATH}")
