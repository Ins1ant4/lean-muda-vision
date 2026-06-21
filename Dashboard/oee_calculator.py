"""Live OEE = Availability x Performance x Quality.

Availability is measured against the FULL planned shift duration (e.g. 8h),
so with zero stoppages A = 100% from the very first second of the shift.
Performance and Quality default to 100% until production data exists,
giving an intuitive OEE that starts at 100% and only drops when a real
loss happens (downtime, slow cycle, or scrap).
"""


def get_cumulative_target(elapsed_s, downtime_s, hourly_targets):
    if elapsed_s <= 0:
        return 0.0
    raw_target = 0.0
    remaining = elapsed_s
    for i in range(100):  # limit loop to prevent infinite loop
        if remaining <= 0:
            break
        chunk = min(3600.0, remaining)
        # Fallback to last target value in list if elapsed exceeds the specified target list
        idx = min(i, len(hourly_targets) - 1)
        target_val = hourly_targets[idx]
        raw_target += (chunk / 3600.0) * target_val
        remaining -= chunk
    
    # Scale down by run ratio to account for downtime
    run_ratio = max(0.0, (elapsed_s - downtime_s) / elapsed_s)
    return raw_target * run_ratio


def compute_oee(shift_start, shift_end, now, ok, scrap, downtime_s,
                hourly_targets, planned_break_s=0.0):
    shift_duration_s = max(0.0, (shift_end - shift_start).total_seconds())
    planned_run_time = max(0.0, shift_duration_s - planned_break_s)
    elapsed = max(0.0, (now - shift_start).total_seconds())

    if planned_run_time <= 0:
        return {
            "oee": 1.0, "availability": 1.0, "performance": 1.0, "quality": 1.0,
            "ok": ok, "scrap": scrap, "downtime_s": downtime_s,
            "elapsed_s": elapsed, "planned_run_s": 0.0, "actual_run_s": 0.0,
            "shift_duration_s": shift_duration_s,
        }

    # Availability — losses accumulate against the full planned shift
    availability = max(0.0, (planned_run_time - downtime_s) / planned_run_time)

    # Convert cycle_time_s to hourly_targets format if it is single float/int
    if not isinstance(hourly_targets, (list, tuple)):
        cycle_time_s = float(hourly_targets)
        p_h = 3600.0 / cycle_time_s if cycle_time_s > 0 else 0.0
        hourly_targets = [p_h] * 8

    # Performance — 'Smart Target' logic: 100% until a deadline is actually missed
    total = ok + scrap
    
    target = get_cumulative_target(elapsed, downtime_s, hourly_targets)
    
    if target <= 0:
        performance = 1.0
    else:
        expected_full_pieces = int(target) # Floor: how many SHOULD be done by now
        
        if total >= expected_full_pieces:
            # You are on track or ahead of the integer target
            performance = 1.0
        else:
            # You have missed at least one piece's deadline
            performance = total / target

    # Quality — default 100% until first piece exists
    quality = ok / total if total > 0 else 1.0

    oee = availability * performance * quality

    return {
        "oee": oee,
        "availability": availability,
        "performance": performance,
        "quality": quality,
        "ok": ok,
        "scrap": scrap,
        "downtime_s": downtime_s,
        "elapsed_s": elapsed,
        "planned_run_s": planned_run_time,
        "actual_run_s": max(0.0, elapsed - downtime_s),
        "shift_duration_s": shift_duration_s,
    }
