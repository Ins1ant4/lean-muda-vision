"""
One-shot migration: pushes local SQLite history into Supabase.

  - production_data.db / mudas_log     ->  Supabase mudas_log
  - forvia_production.db / production_log -> Supabase production_log

Run AFTER you've created the tables in Supabase (see supabase_setup.sql):

    python migrate_to_supabase.py
"""
import os
import sqlite3
from dotenv import load_dotenv
from supabase import create_client

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(SCRIPT_DIR, ".env"))

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
MACHINE_ID = os.getenv("MACHINE_ID", "RH1")

MUDAS_DB = os.path.join(SCRIPT_DIR, "production_data.db")
FORVIA_DB = os.path.join(SCRIPT_DIR, "forvia_production.db")


def migrate_mudas(sb):
    if not os.path.exists(MUDAS_DB):
        print(f"Skip mudas: {MUDAS_DB} not found")
        return
    conn = sqlite3.connect(MUDAS_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT timestamp, stop_duration, classification, state FROM mudas_log ORDER BY id"
    ).fetchall()
    conn.close()
    if not rows:
        print("mudas_log empty.")
        return
    payload = [
        {
            "timestamp": r["timestamp"],
            "stop_duration": r["stop_duration"],
            "classification": r["classification"],
            "state": r["state"],
            "machine_id": MACHINE_ID,
        }
        for r in rows
    ]
    print(f"Pushing {len(payload)} muda rows...")
    resp = sb.table("mudas_log").insert(payload).execute()
    print(f"  -> {len(resp.data) if resp.data else 0} inserted.")


def migrate_production(sb):
    if not os.path.exists(FORVIA_DB):
        print(f"Skip production: {FORVIA_DB} not found")
        return
    conn = sqlite3.connect(FORVIA_DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT timestamp, piece_number, result, sewing_time_s, rework_count "
            "FROM production_log ORDER BY id"
        ).fetchall()
    except sqlite3.OperationalError as e:
        print(f"Skip production: {e}")
        conn.close()
        return
    conn.close()
    if not rows:
        print("production_log empty.")
        return
    payload = [
        {
            "timestamp": r["timestamp"],
            "machine_id": MACHINE_ID,
            "piece_number": r["piece_number"],
            "result": r["result"],
            "sewing_time_s": r["sewing_time_s"],
            "rework_count": r["rework_count"],
        }
        for r in rows
    ]
    print(f"Pushing {len(payload)} production rows...")
    resp = sb.table("production_log").insert(payload).execute()
    print(f"  -> {len(resp.data) if resp.data else 0} inserted.")


def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise SystemExit("SUPABASE_URL / SUPABASE_KEY missing — check .env")
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    migrate_mudas(sb)
    migrate_production(sb)
    print("Done.")


if __name__ == "__main__":
    main()
