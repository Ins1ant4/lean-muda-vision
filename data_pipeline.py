import os
import sqlite3
import json
import time
import threading
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

# Load .env from the script's directory regardless of CWD.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# Supabase is optional — pipeline still runs offline if the package or network is unavailable.
try:
    from supabase import create_client, Client as SupabaseClient
    _SUPABASE_AVAILABLE = True
except ImportError:
    _SUPABASE_AVAILABLE = False

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_TABLE = os.getenv("SUPABASE_TABLE", "mudas_log")
MACHINE_ID = os.getenv("MACHINE_ID", "RH1")
STATUS_PUSH_INTERVAL_S = 1.0  # throttle live-status writes to Supabase

class DataPipeline:
    def __init__(self, broker_ip="127.0.0.1", port=1883):
        # ---------------------------------------------------------
        # 1. SQLITE SETUP (Long-Term Memory)
        # ---------------------------------------------------------
        self.db_name = "production_data.db"
        self._init_db()

        # ---------------------------------------------------------
        # 2. MQTT SETUP (Real-Time Voice)
        # ---------------------------------------------------------
        self.broker_ip = os.getenv("MQTT_BROKER_IP") or broker_ip or "127.0.0.1"
        self.port = port
        self.client = mqtt.Client(client_id="JUKI_Edge_Node_01")

        try:
            self.client.connect(self.broker_ip, self.port, 60)
            self.client.loop_start() # Runs in the background!
            print(f"[INFO] MQTT Connected to {self.broker_ip}")
        except Exception as e:
            print(f"[WARNING] MQTT Connection failed: {e}. Running offline.")

        # ---------------------------------------------------------
        # 3. SUPABASE SETUP (Cloud Mirror — fire-and-forget)
        # ---------------------------------------------------------
        self.supabase = None
        self._last_status_push = 0.0
        self.forvia_db_name = os.path.join(os.path.dirname(os.path.abspath(__file__)), "forvia_production.db")
        if not _SUPABASE_AVAILABLE:
            print("[WARNING] supabase package not installed. Run: pip install supabase")
        elif not SUPABASE_URL or not SUPABASE_KEY:
            print("[WARNING] SUPABASE_URL / SUPABASE_KEY not set in .env. Cloud sync disabled.")
        else:
            try:
                self.supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)
                print(f"[INFO] Supabase client initialized -> {SUPABASE_URL}")
            except Exception as e:
                print(f"[WARNING] Supabase init failed: {e}. Cloud sync disabled.")

        # ---------------------------------------------------------
        # 4. OFFLINE SYNC DAEMON
        # ---------------------------------------------------------
        self.sync_thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.sync_thread.start()

    def _init_db(self):
        """Creates the SQL table if it doesn't exist."""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mudas_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                stop_duration REAL,
                classification TEXT,
                state TEXT,
                synced INTEGER DEFAULT 0
            )
        ''')
        # Migration: ensure synced column exists if DB was already created
        try:
            cursor.execute("ALTER TABLE mudas_log ADD COLUMN synced INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        conn.commit()
        conn.close()
        print(f"[INFO] SQLite Local Database connected -> {self.db_name}")

    def publish_realtime_status(self, current_state, is_moving, downtime, last_classification=None):
        """Sends live heartbeat to the CustomTkinter Dashboard (Every frame/second)"""
        payload = {
            "state": current_state.value,
            "jig_moving": bool(is_moving),
            "current_downtime": round(downtime, 1)
        }
        # MQTT — fire and forget
        self.client.publish("forvia/juki/live_status", json.dumps(payload), qos=0)

        # Supabase — throttled upsert into machine_status (one row per machine)
        if self.supabase is None:
            return
        now = time.time()
        if now - self._last_status_push < STATUS_PUSH_INTERVAL_S:
            return
        self._last_status_push = now
        row = {
            "machine_id": MACHINE_ID,
            "state": current_state.value,
            "is_moving": bool(is_moving),
            "current_downtime_s": round(downtime, 1),
            "last_classification": last_classification.value if last_classification else None,
            "last_heartbeat": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        }
        threading.Thread(target=self._upsert_status, args=(row,), daemon=True).start()

    def _upsert_status(self, row):
        try:
            self.supabase.table("machine_status").upsert(row, on_conflict="machine_id").execute()
        except Exception as e:
            print(f"[SUPABASE STATUS ERROR] {e}")

    def log_production_to_cloud(self, piece_number, result, sewing_time_s, rework_count, local_id=None):
        """Mirror a production record (OK / Scrap) into Supabase production_log."""
        # MQTT Alert - notify dashboard instantly of the production piece
        payload = {
            "alert_type": "PRODUCTION_LOGGED",
            "piece_number": piece_number,
            "result": result,
            "sewing_time": round(sewing_time_s or 0.0, 2),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        try:
            self.client.publish("forvia/juki/alerts", json.dumps(payload), qos=1)
        except Exception as e:
            print(f"[MQTT PROD ALERT ERROR] {e}")

        if self.supabase is None:
            return
        row = {
            "machine_id": MACHINE_ID,
            "piece_number": piece_number,
            "result": result,
            "sewing_time_s": round(sewing_time_s or 0.0, 2),
            "rework_count": rework_count or 0,
        }
        threading.Thread(target=self._push_production, args=(row, local_id), daemon=True).start()

    def _push_production(self, row, local_id=None):
        try:
            self.supabase.table("production_log").insert(row).execute()
            print(f"[SUPABASE] Production logged: {row['result']} #{row['piece_number']}")
            if local_id is not None:
                self._mark_production_synced(local_id)
        except Exception as e:
            print(f"[SUPABASE PROD ERROR] {e}")

    def _push_to_supabase(self, row, local_id=None):
        """Background thread target — never blocks the vision loop."""
        try:
            self.supabase.table(SUPABASE_TABLE).insert(row).execute()
            print(f"[SUPABASE] Logged {row['classification']} ({row['stop_duration']}s)")
            if local_id is not None:
                self._mark_muda_synced(local_id)
        except Exception as e:
            print(f"[SUPABASE ERROR] {e}")

    def log_and_publish_muda(self, duration, classification):
        """Called ONLY when a stop is fully validated and classified."""
        local_id = None
        # 1. Save to local SQL (fallback / offline buffer)
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO mudas_log (stop_duration, classification, synced)
                VALUES (?, ?, 0)
            ''', (round(duration, 1), classification.value))
            local_id = cursor.lastrowid
            conn.commit()
            conn.close()
            print(f"[SQL] Logged {classification.value} ({duration:.1f}s)")
        except Exception as e:
            print(f"[SQL ERROR] {e}")

        # 2. Mirror to Supabase (non-blocking)
        if self.supabase is not None:
            row = {
                "stop_duration": round(duration, 1),
                "classification": classification.value,
                "machine_id": MACHINE_ID,
            }
            threading.Thread(
                target=self._push_to_supabase, args=(row, local_id), daemon=True
            ).start()

        # 3. Send Alert via MQTT
        payload = {
            "alert_type": "MUDA_CLASSIFIED",
            "duration": round(duration, 1),
            "classification": classification.value,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        self.client.publish("forvia/juki/alerts", json.dumps(payload), qos=1)

    # ---------------------------------------------------------
    # 5. SYNC DAEMON METHODS
    # ---------------------------------------------------------
    def _mark_production_synced(self, local_id):
        try:
            conn = sqlite3.connect(self.forvia_db_name)
            cursor = conn.cursor()
            cursor.execute("UPDATE production_log SET synced = 1 WHERE id = ?", (local_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[SQL FORVIA UPDATE ERROR] {e}")

    def _mark_muda_synced(self, local_id):
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            cursor.execute("UPDATE mudas_log SET synced = 1 WHERE id = ?", (local_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[SQL MUDA UPDATE ERROR] {e}")

    def _sync_loop(self):
        """Periodically checks for unsynced rows and pushes them to Supabase."""
        time.sleep(5)  # Wait a few seconds after startup
        while True:
            try:
                if self.supabase is not None:
                    self._sync_pending_mudas()
                    self._sync_pending_production()
            except Exception as e:
                print(f"[SYNC LOOP ERROR] {e}")
            time.sleep(30)

    def _sync_pending_mudas(self):
        try:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            # Ensure table has synced column
            try:
                cursor.execute("ALTER TABLE mudas_log ADD COLUMN synced INTEGER DEFAULT 0")
                conn.commit()
            except sqlite3.OperationalError:
                pass

            rows = cursor.execute(
                "SELECT id, timestamp, stop_duration, classification, state FROM mudas_log WHERE synced = 0 LIMIT 100"
            ).fetchall()
            conn.close()
            
            if not rows:
                return

            print(f"[SYNC] Found {len(rows)} unsynced muda logs. Syncing to Supabase...")
            
            payload = []
            for r in rows:
                payload.append({
                    "timestamp": r["timestamp"],
                    "stop_duration": r["stop_duration"],
                    "classification": r["classification"],
                    "state": r["state"],
                    "machine_id": MACHINE_ID,
                })
            
            self.supabase.table(SUPABASE_TABLE).insert(payload).execute()
            
            # Update local rows to synced
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            row_ids = [r["id"] for r in rows]
            cursor.execute(
                f"UPDATE mudas_log SET synced = 1 WHERE id IN ({','.join(['?']*len(row_ids))})",
                row_ids
            )
            conn.commit()
            conn.close()
            print(f"[SYNC] Successfully synced {len(rows)} muda logs to Supabase.")
        except Exception as e:
            print(f"[SYNC MUDA ERROR] {e}")

    def _sync_pending_production(self):
        if not os.path.exists(self.forvia_db_name):
            return
        try:
            conn = sqlite3.connect(self.forvia_db_name)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            # Ensure table has synced column
            try:
                cursor.execute("ALTER TABLE production_log ADD COLUMN synced INTEGER DEFAULT 0")
                conn.commit()
            except sqlite3.OperationalError:
                pass

            rows = cursor.execute(
                "SELECT id, timestamp, piece_number, result, sewing_time_s, rework_count FROM production_log WHERE synced = 0 LIMIT 100"
            ).fetchall()
            conn.close()

            if not rows:
                return

            print(f"[SYNC] Found {len(rows)} unsynced production logs. Syncing to Supabase...")

            payload = []
            for r in rows:
                payload.append({
                    "timestamp": r["timestamp"],
                    "machine_id": MACHINE_ID,
                    "piece_number": r["piece_number"],
                    "result": r["result"],
                    "sewing_time_s": r["sewing_time_s"],
                    "rework_count": r["rework_count"],
                })

            self.supabase.table("production_log").insert(payload).execute()

            # Update local rows to synced
            conn = sqlite3.connect(self.forvia_db_name)
            cursor = conn.cursor()
            row_ids = [r["id"] for r in rows]
            cursor.execute(
                f"UPDATE production_log SET synced = 1 WHERE id IN ({','.join(['?']*len(row_ids))})",
                row_ids
            )
            conn.commit()
            conn.close()
            print(f"[SYNC] Successfully synced {len(rows)} production logs to Supabase.")
        except Exception as e:
            print(f"[SYNC PRODUCTION ERROR] {e}")
