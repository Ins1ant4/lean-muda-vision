"""Dashboard configuration. Edit shift schedule + targets to your factory."""

# ─── Machine ────────────────────────────────────────────────
MACHINE_ID           = "RH1"
MACHINE_DISPLAY_NAME = "RH1"

# ─── Shift schedule (local time, 24h "HH:MM") ──────────────
# Overnight shifts are auto-detected (when end <= start).
SHIFT_SCHEDULE = [
    ("Shift A", "06:00", "14:00"),
    ("Shift B", "14:00", "22:00"),
    ("Shift C", "22:00", "06:00"),
]
PLANNED_BREAK_MIN = 0    # Set to 0 if the 480min is pure production time

# ─── OEE inputs ────────────────────────────────────────────
import os
import json

# Default cycle time (7 parts per hour)
DEFAULT_CYCLE_TIME_S = 514.3

# Resolve settings file path
_HERE = os.path.dirname(os.path.abspath(__file__))
_SETTINGS_PATH = os.path.join(_HERE, "settings.json")

def load_settings():
    if os.path.exists(_SETTINGS_PATH):
        try:
            with open(_SETTINGS_PATH, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"[CONFIG] Load settings failed: {e}")
    return {}

def save_settings(data):
    try:
        current = load_settings()
        current.update(data)
        with open(_SETTINGS_PATH, "w") as f:
            json.dump(current, f, indent=4)
        print(f"[CONFIG] Settings saved persistently: {data}")
    except Exception as e:
        print(f"[CONFIG] Save settings failed: {e}")

_settings = load_settings()
HOURLY_TARGETS = _settings.get("hourly_targets", [7.0]*8)
if not isinstance(HOURLY_TARGETS, list) or len(HOURLY_TARGETS) != 8:
    HOURLY_TARGETS = [7.0]*8
else:
    HOURLY_TARGETS = [float(x) for x in HOURLY_TARGETS]

CYCLE_TIME_S = 3600.0 / (sum(HOURLY_TARGETS) / 8) if sum(HOURLY_TARGETS) > 0 else DEFAULT_CYCLE_TIME_S

def update_hourly_targets(targets):
    global HOURLY_TARGETS, CYCLE_TIME_S
    HOURLY_TARGETS = [float(x) for x in targets]
    CYCLE_TIME_S = 3600.0 / (sum(HOURLY_TARGETS) / 8) if sum(HOURLY_TARGETS) > 0 else DEFAULT_CYCLE_TIME_S
    save_settings({
        "hourly_targets": HOURLY_TARGETS,
        "cycle_time_s": CYCLE_TIME_S
    })

OEE_EXCELLENT = 0.85
OEE_NORMAL    = 0.65

# ─── UI ────────────────────────────────────────────────────
WINDOW_W = 1280
WINDOW_H = 720
REFRESH_INTERVAL_MS = 2000
HEARTBEAT_TIMEOUT_S = 5.0   # if last_heartbeat older than this → "Stopped" / disconnected

# ─── Colors (Premium FORVIA palette) ────────────────────────
BG_CREAM       = "#F8F9FC"
BORDER_GREEN   = "#E2E4EE"
ACCENT_GREEN   = "#16A34A"
ACCENT_AMBER   = "#F59E0B"
ACCENT_RED     = "#DC2626"
TITLE_BLUE     = "#1F20C3"
TEXT_DARK      = "#161629"
TEXT_GRAY      = "#5C6178"
GAUGE_TRACK    = "#E2E8F0"
