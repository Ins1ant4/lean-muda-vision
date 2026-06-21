"""Supabase queries for the dashboard. All times exchanged as UTC ISO strings."""
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

import config


def _to_utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc).isoformat()


class DataService:
    def __init__(self, env_path: str):
        load_dotenv(env_path)
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError(
                f"SUPABASE_URL / SUPABASE_KEY missing. Looked for .env at: {env_path}"
            )
        self.sb = create_client(url, key)
        self.connected = False

    # ── live machine state ────────────────────────────────────
    def fetch_status(self, machine_id: str = None):
        machine_id = machine_id or config.MACHINE_ID
        try:
            r = (
                self.sb.table("machine_status")
                .select("*")
                .eq("machine_id", machine_id)
                .limit(1)
                .execute()
            )
            self.connected = True
            return r.data[0] if r.data else None
        except Exception as e:
            print(f"[DASH] fetch_status failed: {e}")
            self.connected = False
            return None

    # ── production counts in shift window ─────────────────────
    def fetch_production(self, start_dt: datetime, end_dt: datetime, machine_id: str = None):
        machine_id = machine_id or config.MACHINE_ID
        try:
            r = (
                self.sb.table("production_log")
                .select("result, timestamp, piece_number")
                .eq("machine_id", machine_id)
                .gte("timestamp", _to_utc_iso(start_dt))
                .lte("timestamp", _to_utc_iso(end_dt))
                .execute()
            )
            self.connected = True
            return r.data or []
        except Exception as e:
            print(f"[DASH] fetch_production failed: {e}")
            self.connected = False
            return []

    # ── downtime in shift window ──────────────────────────────
    def fetch_downtime(self, start_dt: datetime, end_dt: datetime, machine_id: str = None):
        machine_id = machine_id or config.MACHINE_ID
        try:
            q = (
                self.sb.table("mudas_log")
                .select("stop_duration, classification, timestamp, machine_id")
                .gte("timestamp", _to_utc_iso(start_dt))
                .lte("timestamp", _to_utc_iso(end_dt))
                .execute()
            )
            self.connected = True
            # Some legacy rows may have machine_id=NULL — treat as belonging to this machine.
            return [r for r in (q.data or []) if r.get("machine_id") in (None, machine_id)]
        except Exception as e:
            print(f"[DASH] fetch_downtime failed: {e}")
            self.connected = False
            return []

    # ── historical production log (batch query) ───────────────
    def fetch_historical_production(self, start_dt: datetime, end_dt: datetime, machine_id: str = None):
        machine_id = machine_id or config.MACHINE_ID
        try:
            r = (
                self.sb.table("production_log")
                .select("result, timestamp, piece_number")
                .eq("machine_id", machine_id)
                .gte("timestamp", _to_utc_iso(start_dt))
                .lte("timestamp", _to_utc_iso(end_dt))
                .execute()
            )
            return r.data or []
        except Exception as e:
            print(f"[DASH] fetch_historical_production failed: {e}")
            return []

    # ── historical downtime log (batch query) ──────────────────
    def fetch_historical_downtime(self, start_dt: datetime, end_dt: datetime, machine_id: str = None):
        machine_id = machine_id or config.MACHINE_ID
        try:
            q = (
                self.sb.table("mudas_log")
                .select("stop_duration, classification, timestamp, machine_id")
                .gte("timestamp", _to_utc_iso(start_dt))
                .lte("timestamp", _to_utc_iso(end_dt))
                .execute()
            )
            return [r for r in (q.data or []) if r.get("machine_id") in (None, machine_id)]
        except Exception as e:
            print(f"[DASH] fetch_historical_downtime failed: {e}")
            return []

