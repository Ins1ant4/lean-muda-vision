"""Professional FORVIA AMS Dashboard — Real-time performance & stoppages management."""
import os
import threading
import tkinter as tk
from datetime import datetime, timezone, timedelta
import json
import paho.mqtt.client as mqtt

import customtkinter as ctk

import config
from shift_manager import get_current_shift, get_past_shifts
from oee_calculator import compute_oee
from ui import theme, components
from ui.settings_ui import SupervisorLoginWindow, SupervisorSettingsWindow


class Dashboard(ctk.CTk):
    def __init__(self, data_service):
        super().__init__()
        self.ds = data_service
        
        # Window Setup
        ctk.set_appearance_mode("light")
        self.title("FORVIA - AMS Smart Productivity Monitor")
        self.geometry(f"{config.WINDOW_W}x{config.WINDOW_H}")
        self.minsize(1200, 700)
        self.configure(fg_color=theme.BG_APP)
        
        self.bind("<F11>", self._toggle_fullscreen)
        self.bind("<Escape>", lambda _: self.attributes("-fullscreen", False))
        self._fullscreen = False
        self._fetching = False
        
        self.mqtt_status = None
        self.mqtt_client = None
        self.current_production = []
        self._pending_production = []
        self._pending_stoppages = []
        self.current_stoppages = []
        self._fetching_history = False
        self._current_tab = "Live Monitor"
        self._setup_mqtt()

        self._build_layout()
        self._tick()

    def _build_layout(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1) # Main content area

        # 1. Header
        header = ctk.CTkFrame(self, fg_color=theme.BG_HEADER, height=80, corner_radius=0)
        header.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        
        # Logo
        logo_path = os.path.join(os.path.dirname(__file__), "assets", "logo-global.png")
        components.LogoBlock(header, logo_path=logo_path).pack(side="left", padx=30)
        
        # Machine Info
        info_frame = ctk.CTkFrame(header, fg_color="transparent")
        info_frame.pack(side="left", padx=20)
        ctk.CTkLabel(
            info_frame, text=config.MACHINE_DISPLAY_NAME, 
            font=theme.font(20, "bold"), text_color=theme.TEXT_PRIMARY
        ).pack(anchor="w")
        self.badge_status = components.StatusBadge(info_frame)
        self.badge_status.pack(anchor="w")

        # Right header controls
        right_controls = ctk.CTkFrame(header, fg_color="transparent")
        right_controls.pack(side="right", padx=30)
        
        # Load tab and settings icons
        assets_dir = os.path.join(os.path.dirname(__file__), "assets")
        from PIL import Image
        img_live_path = os.path.join(assets_dir, "icon_live.png")
        img_hist_path = os.path.join(assets_dir, "icon_hist.png")
        img_settings_path = os.path.join(assets_dir, "icon_settings.png")
        
        if os.path.exists(img_live_path):
            img_live = Image.open(img_live_path)
            self.icon_live = ctk.CTkImage(light_image=img_live, dark_image=img_live, size=(25, 25))
        else:
            self.icon_live = None
            
        if os.path.exists(img_hist_path):
            img_hist = Image.open(img_hist_path)
            self.icon_hist = ctk.CTkImage(light_image=img_hist, dark_image=img_hist, size=(25, 25))
        else:
            self.icon_hist = None
            
        if os.path.exists(img_settings_path):
            img_settings = Image.open(img_settings_path)
            self.icon_settings = ctk.CTkImage(light_image=img_settings, dark_image=img_settings, size=(25, 25))
        else:
            self.icon_settings = None
        
        # Tab Buttons
        self.btn_tab_live = ctk.CTkButton(
            right_controls, text="" if self.icon_live else "📊", image=self.icon_live,
            width=40, height=40, fg_color="white", hover_color=theme.BRAND_LIGHT,
            border_color=theme.BRAND_PRIMARY, border_width=2, text_color=theme.BRAND_PRIMARY,
            command=lambda: self._select_tab("Live Monitor")
        )
        self.btn_tab_live.pack(side="left", padx=5)

        self.btn_tab_hist = ctk.CTkButton(
            right_controls, text="" if self.icon_hist else "🕒", image=self.icon_hist,
            width=40, height=40, fg_color="white", hover_color=theme.BRAND_LIGHT,
            border_color=theme.BORDER_LIGHT, border_width=1, text_color=theme.TEXT_SECONDARY,
            command=lambda: self._select_tab("Performance History")
        )
        self.btn_tab_hist.pack(side="left", padx=5)
        
        self.btn_settings = ctk.CTkButton(
            right_controls, text="" if self.icon_settings else "⚙", image=self.icon_settings,
            width=40, height=40, fg_color="white", hover_color=theme.BRAND_LIGHT,
            border_color=theme.BORDER_LIGHT, border_width=1, text_color=theme.TEXT_SECONDARY,
            command=self._open_settings_login
        )
        self.btn_settings.pack(side="left", padx=5)
        
        # Separator line
        ctk.CTkLabel(right_controls, text=" | ", font=theme.font(16), text_color=theme.BORDER_MEDIUM).pack(side="left", padx=10)
        
        # Shift Label
        self.lbl_shift_name = ctk.CTkLabel(
            right_controls, text="INITIALIZING...", 
            font=theme.font(14, "bold"), text_color=theme.BRAND_PRIMARY
        )
        self.lbl_shift_name.pack(side="left")

        # 2. Main Content Frames
        self.frame_live = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_hist = ctk.CTkFrame(self, fg_color="transparent")
        
        # Configure grid for frames
        self.frame_live.grid_columnconfigure(0, weight=1)
        self.frame_live.grid_rowconfigure(1, weight=1)
        self.frame_hist.grid_columnconfigure(0, weight=1)
        self.frame_hist.grid_rowconfigure(0, weight=1)

        # Show Live Monitor by default
        self.frame_live.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))

        # ── TAB 1: LIVE MONITOR ──
        # Top Row: KPI Cards
        kpi_row = ctk.CTkFrame(self.frame_live, fg_color="transparent")
        kpi_row.grid(row=0, column=0, sticky="nsew", pady=(0, 20))
        for i in range(4): kpi_row.grid_columnconfigure(i, weight=1)

        target_pcs = 3600.0 / config.CYCLE_TIME_S if config.CYCLE_TIME_S > 0 else 0.0
        self.kpi_oee = components.KpiCard(kpi_row, "OEE", subtitle=f"Target: 85% (Avg: {target_pcs:.1f} pcs/h)")
        self.kpi_oee.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        self.kpi_ok = components.KpiCard(kpi_row, "TOTAL OK", color=theme.COLOR_OK)
        self.kpi_ok.grid(row=0, column=1, sticky="nsew", padx=10)

        self.kpi_scrap = components.KpiCard(kpi_row, "SCRAP", color=theme.COLOR_DANGER)
        self.kpi_scrap.grid(row=0, column=2, sticky="nsew", padx=10)

        self.kpi_downtime = components.KpiCard(kpi_row, "DOWNTIME", subtitle="Current shift")
        self.kpi_downtime.grid(row=0, column=3, sticky="nsew", padx=(10, 0))

        # Bottom Row: Chart and Table
        bottom_row = ctk.CTkFrame(self.frame_live, fg_color="transparent")
        bottom_row.grid(row=1, column=0, sticky="nsew")
        bottom_row.grid_columnconfigure(0, weight=4) # Chart
        bottom_row.grid_columnconfigure(1, weight=6) # Table
        bottom_row.grid_rowconfigure(0, weight=1)

        # Chart Card
        chart_card = components.CardFrame(bottom_row, title="Hourly OEE Breakdown")
        chart_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.chart = components.HourlyBarChart(chart_card.body)
        self.chart.pack(fill="both", expand=True)

        # Stoppage Management Card
        table_card = components.CardFrame(bottom_row, title="Shift Stoppages History")
        table_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.table = components.StoppageTable(table_card.body)
        self.table.pack(fill="both", expand=True)

        # ── TAB 2: PERFORMANCE HISTORY ──
        hist_container = ctk.CTkFrame(self.frame_hist, fg_color="transparent")
        hist_container.grid(row=0, column=0, sticky="nsew")
        hist_container.grid_columnconfigure(0, weight=1) # Full-width
        hist_container.grid_rowconfigure(0, weight=1)

        # History Table Card (Full Width)
        hist_table_card = components.CardFrame(hist_container, title="Past Shifts Log (Last 7 Days)")
        hist_table_card.grid(row=0, column=0, sticky="nsew", padx=0)
        self.hist_table = components.HistoryTable(hist_table_card.body, show_details_callback=self._show_shift_details)
        self.hist_table.pack(fill="both", expand=True)

        # 3. Footer
        footer = ctk.CTkFrame(self, fg_color=theme.BG_FOOTER, height=30, corner_radius=0)
        footer.grid(row=2, column=0, sticky="nsew")
        
        self.conn_dot = components.ConnectionDot(footer)
        self.conn_dot.pack(side="left", padx=20, pady=5)
        
        self.mqtt_dot = components.ConnectionDot(footer)
        self.mqtt_dot.pack(side="left", padx=10, pady=5)
        self.mqtt_dot.set("MQTT CONNECTING", theme.COLOR_WARN)
        
        self.lbl_last_update = ctk.CTkLabel(
            footer, text="Last update: —", 
            font=theme.font(10), text_color=theme.TEXT_MUTED
        )
        self.lbl_last_update.pack(side="right", padx=20)

    # ── Data Processing ───────────────────────────────────────
    def _tick(self):
        if not self._fetching:
            threading.Thread(target=self._fetch, daemon=True).start()
        self.after(config.REFRESH_INTERVAL_MS, self._tick)

    def _fetch(self):
        self._fetching = True
        try:
            now = datetime.now().astimezone()
            shift_name, shift_start, shift_end = get_current_shift(now)

            if shift_start is None:
                self.after(0, self._render_offline, "OUTSIDE PRODUCTION HOURS")
                return

            status = None
            if self.mqtt_status and self._is_recent(self.mqtt_status.get("last_heartbeat"), 10.0):
                status = self.mqtt_status
            else:
                status = self.ds.fetch_status()
            production = self.ds.fetch_production(shift_start, now)
            downtime = self.ds.fetch_downtime(shift_start, now)

            ok = sum(1 for p in production if (p.get("result") or "").upper() == "OK")
            scrap = sum(1 for p in production if (p.get("result") or "").upper() == "SCRAP")
            downtime_s = sum((d.get("stop_duration") or 0.0) for d in downtime)

            oee_res = compute_oee(
                shift_start, shift_end, now, ok, scrap, downtime_s,
                config.HOURLY_TARGETS, config.PLANNED_BREAK_MIN * 60,
            )

            live = bool(status) and self._is_recent(status.get("last_heartbeat"), config.HEARTBEAT_TIMEOUT_S)
            state = status.get("state", "IDLE") if status else "IDLE"
            is_running = live and (state in ["Normal Production", "Restart Validation", "QC", "Rework Piece"])

            # ── Hourly Breakdown ──────────
            hourly_stats = []
            bucket_start = shift_start.replace(minute=0, second=0, microsecond=0)
            while bucket_start < shift_end:
                bucket_end = bucket_start + timedelta(hours=1)
                
                # Sliced data for this hour
                h_prod = [r for r in production if bucket_start <= datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")) < bucket_end]
                h_down = [r for r in downtime if bucket_start <= datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")) < bucket_end]
                
                h_ok = sum(1 for p in h_prod if (p.get("result") or "").upper() == "OK")
                h_scrap = sum(1 for p in h_prod if (p.get("result") or "").upper() == "SCRAP")
                h_down_s = sum((d.get("stop_duration") or 0.0) for d in h_down)
                
                h_now = min(now, bucket_end)
                if h_now > bucket_start:
                    idx = min(max(0, int((bucket_start - shift_start).total_seconds() / 3600)), 7)
                    h_res = compute_oee(bucket_start, bucket_end, h_now, h_ok, h_scrap, h_down_s, [config.HOURLY_TARGETS[idx]])
                    hourly_stats.append((bucket_start.strftime("%H:00"), h_res["oee"]))
                else:
                    hourly_stats.append((bucket_start.strftime("%H:00"), 0.0))
                
                bucket_start = bucket_end

            self.after(0, self._render, {
                "shift": shift_name,
                "is_running": is_running,
                "connected": self.ds.connected,
                "live": live,
                "ok": ok, "scrap": scrap, "downtime_s": downtime_s,
                "oee": oee_res["oee"],
                "stoppages": downtime,
                "production": production,
                "hourly_stats": hourly_stats
            })
        except Exception as e:
            print(f"[DASH] Fetch thread error: {e}")
        finally:
            self._fetching = False

    def _render(self, p):
        # Header & Status
        self.lbl_shift_name.configure(text=f"SHIFT: {p['shift']}")
        self.badge_status.set_state(p["live"], p["is_running"])
        
        # KPIs
        oee = p["oee"]
        oee_color = theme.COLOR_OK if oee >= config.OEE_EXCELLENT else (theme.COLOR_WARN if oee >= config.OEE_NORMAL else theme.COLOR_DANGER)
        self.kpi_oee.update_kpi(f"{int(oee*100)}%", color=oee_color)
        
        self.current_production = p["production"]
        self._update_production_kpis()
        
        h = int(p["downtime_s"] // 3600)
        m = int((p["downtime_s"] % 3600) // 60)
        s = int(p["downtime_s"] % 60)
        self.kpi_downtime.update_kpi(f"{h}h {m}m {s}s" if h > 0 else f"{m}m {s}s")

        # Chart & Table
        self.chart.set_data(p["hourly_stats"])
        self.current_stoppages = p["stoppages"]
        self._update_stoppages_ui()

        # Connection
        if p["connected"] and p["live"]:
            self.conn_dot.set("SYSTEM ONLINE", theme.COLOR_OK)
        elif p["connected"]:
            self.conn_dot.set("NO HEARTBEAT", theme.COLOR_WARN)
        else:
            self.conn_dot.set("DATABASE OFFLINE", theme.COLOR_DANGER)
            
        self.lbl_last_update.configure(text=f"Last update: {datetime.now().strftime('%H:%M:%S')}")

    def _render_offline(self, reason):
        self.lbl_shift_name.configure(text=reason)
        self.badge_status.set_state(False, False)
        self.kpi_oee.update_kpi("0%")
        self.chart.set_data([])
        self.table.update_data([])

    def _is_recent(self, iso_ts: str, max_age_s: float) -> bool:
        if not iso_ts: return False
        try:
            ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
            if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - ts).total_seconds() < max_age_s
        except Exception: return False

    def _toggle_fullscreen(self, _evt=None):
        self._fullscreen = not self._fullscreen
        self.attributes("-fullscreen", self._fullscreen)

    # ── MQTT Subscription ─────────────────────────────────────
    def _setup_mqtt(self):
        def _connect():
            try:
                broker_ip = os.getenv("MQTT_BROKER_IP", "127.0.0.1")
                self.mqtt_client = mqtt.Client(client_id="FORVIA_Dashboard_Sub")
                self.mqtt_client.on_message = self._on_mqtt_message
                self.mqtt_client.on_connect = self._on_mqtt_connect
                self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
                self.mqtt_client.connect(broker_ip, 1883, 60)
                self.mqtt_client.loop_start()
                print(f"[DASH] MQTT Client initialized and listening on {broker_ip}:1883")
            except Exception as e:
                print(f"[DASH] Failed to initialize MQTT client: {e}. Falling back to DB-only mode.")
                self.after(0, lambda: self.mqtt_dot.set("MQTT OFFLINE", theme.COLOR_DANGER))
        
        threading.Thread(target=_connect, daemon=True).start()

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        if rc == 0:
            client.subscribe("forvia/juki/live_status")
            client.subscribe("forvia/juki/alerts")
            print("[DASH] MQTT Subscribed to topics successfully.")
            self.after(0, lambda: self.mqtt_dot.set("MQTT ONLINE", theme.COLOR_OK))
        else:
            print(f"[DASH] MQTT Connection failed with code {rc}")
            self.after(0, lambda: self.mqtt_dot.set("MQTT OFFLINE", theme.COLOR_WARN))

    def _on_mqtt_disconnect(self, client, userdata, rc):
        print(f"[DASH] MQTT Disconnected with code {rc}")
        self.after(0, lambda: self.mqtt_dot.set("MQTT OFFLINE", theme.COLOR_WARN))

    def _on_mqtt_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            topic = msg.topic
            
            if topic == "forvia/juki/live_status":
                self.after(0, self._handle_mqtt_status, payload)
            elif topic == "forvia/juki/alerts":
                self.after(0, self._handle_mqtt_alert, payload)
        except Exception as e:
            print(f"[DASH] Error processing MQTT message: {e}")

    def _handle_mqtt_status(self, payload):
        state = payload.get("state", "IDLE")
        is_running = state in ["Normal Production", "Restart Validation", "QC", "Rework Piece"]
        self.badge_status.set_state(True, is_running)
        self.conn_dot.set("SYSTEM ONLINE", theme.COLOR_OK)
        self.lbl_last_update.configure(text=f"Last update (Live): {datetime.now().strftime('%H:%M:%S')}")
        self.mqtt_status = {
            "is_moving": payload.get("jig_moving", False),
            "state": state,
            "current_downtime_s": payload.get("current_downtime", 0.0),
            "last_heartbeat": datetime.now(timezone.utc).isoformat()
        }

    def _update_stoppages_ui(self):
        def parse_ts(ts_str):
            if not ts_str:
                return None
            ts_str = ts_str.replace("Z", "+00:00")
            dt = None
            if "T" not in ts_str and " " in ts_str:
                try:
                    dt = datetime.strptime(ts_str.split(".")[0], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass
            if not dt:
                try:
                    dt = datetime.fromisoformat(ts_str)
                except Exception:
                    try:
                        dt = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        pass
            if dt and dt.tzinfo is None:
                dt = dt.astimezone()
            return dt

        # Deduplicate self._pending_stoppages against self.current_stoppages
        updated_pending = []
        for pending in self._pending_stoppages:
            pending_dt = parse_ts(pending.get("timestamp"))
            matched = False
            for fetched in self.current_stoppages:
                fetched_dt = parse_ts(fetched.get("timestamp"))
                if pending_dt and fetched_dt:
                    time_diff = abs((pending_dt - fetched_dt).total_seconds())
                else:
                    time_diff = 999999.0
                
                dur_diff = abs(pending.get("stop_duration", 0) - fetched.get("stop_duration", 0))
                
                # Match if same classification, close duration, and timestamp close within 10 seconds
                if (pending.get("classification") == fetched.get("classification") and
                    dur_diff < 1.0 and
                    time_diff < 10.0):
                    matched = True
                    break
            
            if not matched:
                updated_pending.append(pending)
        
        self._pending_stoppages = updated_pending

        # Combine fetched and pending
        combined = list(self.current_stoppages)
        combined.extend(self._pending_stoppages)

        # Sort chronologically by timestamp
        def get_timestamp_key(item):
            dt = parse_ts(item.get("timestamp"))
            return dt or datetime.min

        combined.sort(key=get_timestamp_key)

        # Update the UI table with the merged list
        self.table.update_data(combined)

    def _update_production_kpis(self):
        def parse_ts(ts_str):
            if not ts_str:
                return None
            ts_str = ts_str.replace("Z", "+00:00")
            dt = None
            if "T" not in ts_str and " " in ts_str:
                try:
                    dt = datetime.strptime(ts_str.split(".")[0], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass
            if not dt:
                try:
                    dt = datetime.fromisoformat(ts_str)
                except Exception:
                    try:
                        dt = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        pass
            if dt and dt.tzinfo is None:
                dt = dt.astimezone()
            return dt

        # Deduplicate self._pending_production against self.current_production
        updated_pending = []
        for pending in self._pending_production:
            pending_dt = parse_ts(pending.get("timestamp"))
            matched = False
            for fetched in self.current_production:
                fetched_dt = parse_ts(fetched.get("timestamp"))
                if pending_dt and fetched_dt:
                    time_diff = abs((pending_dt - fetched_dt).total_seconds())
                else:
                    time_diff = 999999.0
                
                # Only match if the timestamp is close (within 10 seconds) to ensure it's the same piece
                if time_diff < 10.0:
                    # Check piece number first if available
                    p_num_pending = pending.get("piece_number")
                    p_num_fetched = fetched.get("piece_number")
                    if p_num_pending is not None and p_num_fetched is not None:
                        if p_num_pending == p_num_fetched and pending.get("result", "").upper() == fetched.get("result", "").upper():
                            matched = True
                            break
                    # Fallback to result match
                    elif pending.get("result", "").upper() == fetched.get("result", "").upper():
                        matched = True
                        break
            
            if not matched:
                updated_pending.append(pending)
        
        self._pending_production = updated_pending

        # Combine fetched and pending
        combined = list(self.current_production)
        combined.extend(self._pending_production)

        # Recalculate counts
        ok = sum(1 for p in combined if (p.get("result") or "").upper() == "OK")
        scrap = sum(1 for p in combined if (p.get("result") or "").upper() == "SCRAP")

        # Update KPI UI
        self.kpi_ok.update_kpi(ok)
        self.kpi_scrap.update_kpi(scrap)

    def _handle_mqtt_alert(self, payload):
        print(f"[DASH] MQTT Alert received: {payload}")
        
        # 1. Optimistic UI Update (Instant visual feedback in the table / KPIs)
        if payload.get("alert_type") == "MUDA_CLASSIFIED":
            new_stoppage = {
                "timestamp": payload.get("timestamp"),
                "stop_duration": payload.get("duration"),
                "classification": payload.get("classification")
            }
            self._pending_stoppages.append(new_stoppage)
            self._update_stoppages_ui()
        elif payload.get("alert_type") == "PRODUCTION_LOGGED":
            new_prod = {
                "timestamp": payload.get("timestamp"),
                "result": payload.get("result"),
                "piece_number": payload.get("piece_number")
            }
            self._pending_production.append(new_prod)
            self._update_production_kpis()

        # 2. Background Sync (Wait 300ms for Supabase cloud writes to propagate)
        if not self._fetching:
            self.after(300, lambda: threading.Thread(target=self._fetch, daemon=True).start())

    def _select_tab(self, tab_name):
        if tab_name == "Live Monitor":
            self.frame_hist.grid_forget()
            self.frame_live.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
            self.btn_tab_live.configure(border_color=theme.BRAND_PRIMARY, border_width=2, text_color=theme.BRAND_PRIMARY)
            self.btn_tab_hist.configure(border_color=theme.BORDER_LIGHT, border_width=1, text_color=theme.TEXT_SECONDARY)
            self._current_tab = "Live Monitor"
        else:
            self.frame_live.grid_forget()
            self.frame_hist.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
            self.btn_tab_live.configure(border_color=theme.BORDER_LIGHT, border_width=1, text_color=theme.TEXT_SECONDARY)
            self.btn_tab_hist.configure(border_color=theme.BRAND_PRIMARY, border_width=2, text_color=theme.BRAND_PRIMARY)
            self._current_tab = "Performance History"
            self._trigger_history_fetch()

    def _trigger_history_fetch(self):
        if not self._fetching_history:
            threading.Thread(target=self._fetch_history, daemon=True).start()

    def _show_shift_details(self, shift_data):
        ShiftDetailsWindow(self, shift_data)

    def _fetch_history(self):
        self._fetching_history = True
        try:
            now = datetime.now().astimezone()
            start_date = now - timedelta(days=7)
            
            # Fetch batch data
            prod_records = self.ds.fetch_historical_production(start_date, now)
            down_records = self.ds.fetch_historical_downtime(start_date, now)
            
            # Helper to parse UTC timestamps
            def parse_utc_ts(ts_str):
                if not ts_str:
                    return None
                ts_str = ts_str.replace("Z", "+00:00")
                try:
                    return datetime.fromisoformat(ts_str)
                except Exception:
                    return None
            
            # Parse once for performance
            for r in prod_records:
                r["_parsed_dt"] = parse_utc_ts(r.get("timestamp"))
            for r in down_records:
                r["_parsed_dt"] = parse_utc_ts(r.get("timestamp"))
            
            # Generate shifts
            past_shifts = get_past_shifts(days=7, now=now)
            
            history_data = []
            for date_str, shift_name, start, end in past_shifts:
                # Filter records inside this shift window
                shift_prod = [r for r in prod_records if r["_parsed_dt"] and start <= r["_parsed_dt"] < end]
                shift_down = [r for r in down_records if r["_parsed_dt"] and start <= r["_parsed_dt"] < end]
                
                ok = sum(1 for r in shift_prod if (r.get("result") or "").upper() == "OK")
                scrap = sum(1 for r in shift_prod if (r.get("result") or "").upper() == "SCRAP")
                downtime_s = sum((r.get("stop_duration") or 0.0) for r in shift_down)
                
                oee_res = compute_oee(
                    start, end, end, ok, scrap, downtime_s,
                    config.HOURLY_TARGETS, config.PLANNED_BREAK_MIN * 60,
                )
                
                history_data.append({
                    "date": date_str,
                    "shift": shift_name,
                    "oee": oee_res["oee"],
                    "ok": ok,
                    "scrap": scrap,
                    "downtime_s": downtime_s,
                    "production": shift_prod,
                    "downtime": shift_down
                })
                
            self.after(0, self._render_history, history_data)
        except Exception as e:
            print(f"[DASH] History fetch error: {e}")
        finally:
            self._fetching_history = False

    def _render_history(self, history_data):
        self.hist_table.update_data(history_data)

    def _open_settings_login(self):
        SupervisorLoginWindow(self, on_success=self._open_settings_dialog)

    def _open_settings_dialog(self):
        SupervisorSettingsWindow(self, on_save=self._on_settings_saved)

    def _on_settings_saved(self):
        # Settings were saved, now trigger a dynamic recalculation and refresh the KPI subtitle
        target_pcs = 3600.0 / config.CYCLE_TIME_S if config.CYCLE_TIME_S > 0 else 0.0
        self.kpi_oee.update_kpi(subtitle=f"Target: 85% (Avg: {target_pcs:.1f} pcs/h)")
        
        # Trigger an immediate background fetch to update the live OEE gauge/charts
        if not self._fetching:
            threading.Thread(target=self._fetch, daemon=True).start()
            
        # Also trigger a history refresh if we are currently viewing it
        if self._current_tab == "Performance History":
            self._trigger_history_fetch()


class ShiftDetailsWindow(ctk.CTkToplevel):
    def __init__(self, parent, shift_data):
        super().__init__(parent)
        self.title(f"Details — {shift_data['date']} {shift_data['shift']}")
        self.geometry("700x500")
        self.minsize(600, 400)
        self.configure(fg_color=theme.BG_APP)
        
        # Focus/Grab
        self.grab_set()
        
        # Layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        # 1. Header
        header = ctk.CTkFrame(self, fg_color=theme.BG_HEADER, height=60, corner_radius=0)
        header.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(
            header, text=f"SHIFT DETAILS: {shift_data['date']} - {shift_data['shift']}",
            font=theme.font(16, "bold"), text_color=theme.TEXT_PRIMARY
        ).pack(side="left", padx=20, pady=15)
        
        # Close Button
        ctk.CTkButton(
            header, text="Close", font=theme.font(12), width=80,
            command=self.destroy
        ).pack(side="right", padx=20, pady=15)
        
        # 2. Tabs inside popup: Production vs Downtimes
        self.tabview = ctk.CTkTabview(
            self, fg_color="transparent",
            segmented_button_fg_color=theme.BG_TABLE_ALT,
            segmented_button_selected_color=theme.BRAND_PRIMARY,
            segmented_button_selected_hover_color=theme.BRAND_PRIMARY,
            text_color=theme.TEXT_PRIMARY
        )
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=20, pady=20)
        
        self.tabview.add("Pieces Produced")
        self.tabview.add("Muda Downtimes")
        
        tab_pieces = self.tabview.tab("Pieces Produced")
        tab_muda = self.tabview.tab("Muda Downtimes")
        
        # 3. Populate Pieces
        self._build_pieces_table(tab_pieces, shift_data.get("production", []))
        
        # 4. Populate Mudas
        self._build_mudas_table(tab_muda, shift_data.get("downtime", []))
        
    def _build_pieces_table(self, parent, production):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew")
        
        # Headers
        head = ctk.CTkFrame(scroll, fg_color=theme.BG_TABLE_HEADER, height=30)
        head.pack(fill="x", pady=(0, 5))
        cols = [("PIECE #", 0.2), ("RESULT", 0.3), ("TIME", 0.5)]
        for txt, relw in cols:
            lbl = ctk.CTkLabel(
                head, text=txt, font=theme.font(10, "bold"),
                text_color=theme.TEXT_SECONDARY, anchor="w"
            )
            lbl.place(relx=sum(c[1] for c in cols[:cols.index((txt, relw))]), rely=0.5, anchor="w", relwidth=relw, x=10)
            
        if not production:
            ctk.CTkLabel(scroll, text="No pieces logged in this shift.", font=theme.font(12, "italic"), text_color=theme.TEXT_MUTED).pack(pady=30)
            return
            
        for i, p in enumerate(reversed(production)):
            bg = theme.BG_TABLE_ALT if i % 2 == 0 else "transparent"
            row = ctk.CTkFrame(scroll, fg_color=bg, height=34, corner_radius=4)
            row.pack(fill="x", pady=1)
            
            p_num = str(p.get("piece_number") or i + 1)
            res = p.get("result", "OK")
            res_color = theme.COLOR_OK if res.upper() == "OK" else theme.COLOR_DANGER
            ts = p.get("timestamp", "")
            if ts:
                time_part = ts.split("T")[-1] if "T" in ts else ts.split(" ")[-1]
                ts = time_part[:8] # HH:MM:SS
                
            ctk.CTkLabel(row, text=f"Piece {p_num}", font=theme.font(12), text_color=theme.TEXT_PRIMARY, anchor="w").place(relx=0, rely=0.5, anchor="w", relwidth=0.2, x=10)
            ctk.CTkLabel(row, text=res.upper(), font=theme.font(12, "bold"), text_color=res_color, anchor="w").place(relx=0.2, rely=0.5, anchor="w", relwidth=0.3, x=10)
            ctk.CTkLabel(row, text=ts, font=theme.font(12), text_color=theme.TEXT_SECONDARY, anchor="w").place(relx=0.5, rely=0.5, anchor="w", relwidth=0.5, x=10)

    def _build_mudas_table(self, parent, downtime):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew")
        
        # Headers
        head = ctk.CTkFrame(scroll, fg_color=theme.BG_TABLE_HEADER, height=30)
        head.pack(fill="x", pady=(0, 5))
        cols = [("TIME", 0.2), ("DURATION", 0.3), ("CLASSIFICATION", 0.5)]
        for txt, relw in cols:
            lbl = ctk.CTkLabel(
                head, text=txt, font=theme.font(10, "bold"),
                text_color=theme.TEXT_SECONDARY, anchor="w"
            )
            lbl.place(relx=sum(c[1] for c in cols[:cols.index((txt, relw))]), rely=0.5, anchor="w", relwidth=relw, x=10)
            
        if not downtime:
            ctk.CTkLabel(scroll, text="No mudas logged in this shift.", font=theme.font(12, "italic"), text_color=theme.TEXT_MUTED).pack(pady=30)
            return
            
        for i, d in enumerate(reversed(downtime)):
            bg = theme.BG_TABLE_ALT if i % 2 == 0 else "transparent"
            row = ctk.CTkFrame(scroll, fg_color=bg, height=34, corner_radius=4)
            row.pack(fill="x", pady=1)
            
            ts = d.get("timestamp", "")
            if ts:
                time_part = ts.split("T")[-1] if "T" in ts else ts.split(" ")[-1]
                ts = time_part[:8] # HH:MM:SS
                
            raw_dur = d.get("stop_duration", 0)
            if raw_dur >= 60:
                dur = f"{int(raw_dur // 60)} min {int(raw_dur % 60)}s"
            else:
                dur = f"{int(raw_dur)}s"
                
            cls = d.get("classification") or "Unclassified"
            
            ctk.CTkLabel(row, text=ts, font=theme.font(12), text_color=theme.TEXT_PRIMARY, anchor="w").place(relx=0, rely=0.5, anchor="w", relwidth=0.2, x=10)
            ctk.CTkLabel(row, text=dur, font=theme.font(12, "bold"), text_color=theme.COLOR_DANGER, anchor="w").place(relx=0.2, rely=0.5, anchor="w", relwidth=0.3, x=10)
            ctk.CTkLabel(row, text=cls, font=theme.font(12), text_color=theme.TEXT_SECONDARY, anchor="w").place(relx=0.5, rely=0.5, anchor="w", relwidth=0.5, x=10)
