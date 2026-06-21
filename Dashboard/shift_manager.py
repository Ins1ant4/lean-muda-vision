"""Determine the current shift window in local time."""
from datetime import datetime, time, timedelta

import config


def _parse_t(s: str) -> time:
    h, m = map(int, s.split(":"))
    return time(h, m)


def _local_now():
    return datetime.now().astimezone()


def get_current_shift(now=None):
    """Return (name, start_dt, end_dt) for the active shift, all timezone-aware local datetimes.
    Returns (None, None, None) if outside every defined shift window.
    """
    now = now or _local_now()
    today = now.date()

    candidates = []
    # today's shifts
    for name, s, e in config.SHIFT_SCHEDULE:
        st, et = _parse_t(s), _parse_t(e)
        start = datetime.combine(today, st).astimezone()
        end_day = today + timedelta(days=1) if et <= st else today
        end = datetime.combine(end_day, et).astimezone()
        candidates.append((name, start, end))
    # yesterday's overnight shifts that may still be running
    yest = today - timedelta(days=1)
    for name, s, e in config.SHIFT_SCHEDULE:
        st, et = _parse_t(s), _parse_t(e)
        if et <= st:
            start = datetime.combine(yest, st).astimezone()
            end = datetime.combine(today, et).astimezone()
            candidates.append((name, start, end))

    for name, start, end in candidates:
        if start <= now < end:
            return name, start, end
    return None, None, None


def get_past_shifts(days=7, now=None):
    """Return a list of (date_str, name, start_dt, end_dt) for all shifts in the last `days` days,
    sorted chronologically (oldest first).
    """
    now = now or _local_now()
    today = now.date()

    shifts = []
    # Loop back from `days` days ago to today
    for d in range(days, -1, -1):
        target_day = today - timedelta(days=d)
        for name, s, e in config.SHIFT_SCHEDULE:
            st, et = _parse_t(s), _parse_t(e)
            start = datetime.combine(target_day, st).astimezone()
            end_day = target_day + timedelta(days=1) if et <= st else target_day
            end = datetime.combine(end_day, et).astimezone()

            # Only include shifts that have already started/ended
            if end <= now:
                shifts.append((target_day.strftime("%Y-%m-%d"), name, start, end))

    # Sort chronologically
    shifts.sort(key=lambda x: x[2])
    return shifts

