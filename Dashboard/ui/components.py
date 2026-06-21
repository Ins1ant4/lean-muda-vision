"""Reusable UI building blocks: cards, KPIs, status badge, logo block."""
import os
import tkinter as tk

import customtkinter as ctk
from PIL import Image

from . import theme


class LogoBlock(ctk.CTkFrame):
    """Logo image with text fallback."""

    def __init__(self, parent, logo_path=None, size=(160, 44), **kw):
        super().__init__(parent, fg_color="transparent", **kw)
        if logo_path and os.path.exists(logo_path):
            try:
                img = Image.open(logo_path)
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=size)
                ctk.CTkLabel(self, image=ctk_img, text="").pack()
                return
            except Exception as exc:  # noqa: BLE001
                print(f"[UI] logo load failed: {exc}")
        ctk.CTkLabel(
            self, text="FORVIA", text_color=theme.BRAND_PRIMARY,
            font=theme.font(24, "bold"),
        ).pack()


class CardFrame(ctk.CTkFrame):
    """White card with subtle border and an optional uppercase title bar."""

    def __init__(self, parent, title=None, **kw):
        super().__init__(
            parent,
            fg_color=theme.BG_CARD,
            corner_radius=theme.RADIUS_MD,
            border_width=1,
            border_color=theme.BORDER_LIGHT,
            **kw,
        )
        if title:
            head = ctk.CTkFrame(self, fg_color="transparent")
            head.pack(fill="x", padx=theme.PAD_LG, pady=(theme.PAD_LG, 0))
            ctk.CTkLabel(
                head, text=title.upper(),
                text_color=theme.TEXT_SECONDARY,
                font=theme.font(11, "bold"),
                anchor="w",
            ).pack(side="left")
            # subtle accent bar
            tk.Frame(self, bg=theme.BRAND_PRIMARY, height=2).pack(
                fill="x", padx=theme.PAD_LG, pady=(theme.PAD_SM, 0),
            )
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=theme.PAD_LG, pady=theme.PAD_LG)


class StatusBadge(ctk.CTkFrame):
    """Small colored dot + RUNNING/STOPPED label."""

    def __init__(self, parent, **kw):
        super().__init__(parent, fg_color="transparent", **kw)
        self.canvas = tk.Canvas(
            self, width=12, height=12, bg=kw.get("bg_color", "white"),
            highlightthickness=0, bd=0,
        )
        self.canvas.pack(side="left", padx=(0, 6))
        self._dot = self.canvas.create_oval(1, 1, 11, 11, fill=theme.COLOR_DANGER, outline="")
        self.label = ctk.CTkLabel(
            self, text="STOPPED",
            text_color=theme.TEXT_SECONDARY, font=theme.font(12, "bold"),
        )
        self.label.pack(side="left")

    def set_state(self, live: bool, running: bool):
        if not live:
            self.canvas.itemconfig(self._dot, fill=theme.COLOR_WARN)
            self.label.configure(text="MONITOR OFFLINE", text_color=theme.COLOR_WARN)
        elif running:
            self.canvas.itemconfig(self._dot, fill=theme.COLOR_OK)
            self.label.configure(text="RUNNING", text_color=theme.COLOR_OK)
        else:
            self.canvas.itemconfig(self._dot, fill=theme.COLOR_DANGER)
            self.label.configure(text="STOPPED", text_color=theme.COLOR_DANGER)


class KpiCard(CardFrame):
    """Large numeric KPI with title and small subtitle."""

    def __init__(self, parent, title, value="—", subtitle="", color=None, **kw):
        super().__init__(parent, title=title, **kw)
        self.value_lbl = ctk.CTkLabel(
            self.body, text=value,
            text_color=color or theme.TEXT_PRIMARY,
            font=theme.font(42, "bold"),
            anchor="w",
        )
        self.value_lbl.pack(anchor="w")
        self.subtitle_lbl = ctk.CTkLabel(
            self.body, text=subtitle,
            text_color=theme.TEXT_MUTED, font=theme.font(12),
            anchor="w",
        )
        self.subtitle_lbl.pack(anchor="w")

    def update_kpi(self, value=None, subtitle=None, color=None):
        if value is not None:
            self.value_lbl.configure(text=str(value))
        if subtitle is not None:
            self.subtitle_lbl.configure(text=subtitle)
        if color is not None:
            self.value_lbl.configure(text_color=color)


class HourlyBarChart(ctk.CTkFrame):
    """Simple bar chart for hourly OEE trends."""

    def __init__(self, parent, title="HOURLY OEE TREND", **kw):
        super().__init__(parent, fg_color="transparent", **kw)
        ctk.CTkLabel(
            self, text=title, font=theme.font(11, "bold"),
            text_color=theme.TEXT_SECONDARY, anchor="w",
        ).pack(fill="x", padx=10, pady=(0, 10))

        self.canvas = tk.Canvas(
            self, bg="white", highlightthickness=0, bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.draw())
        self.data = [] # List of (label, value)

    def set_data(self, data):
        """data: list of (hour_label, oee_value)"""
        self.data = data
        self.draw()

    def draw(self):
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 100 or h < 60: return

        if not self.data:
            self.canvas.create_text(w//2, h//2, text="No shift data yet", fill=theme.TEXT_MUTED, font=theme.font(12))
            return

        margin_l, margin_r, margin_t, margin_b = 40, 20, 20, 30
        chart_w = w - margin_l - margin_r
        chart_h = h - margin_t - margin_b
        
        bar_gap = 10
        n = len(self.data)
        bar_w = (chart_w - (n - 1) * bar_gap) / n
        
        # Grid lines (0%, 50%, 100%)
        for i in [0, 0.5, 1.0]:
            y = margin_t + chart_h * (1 - i)
            self.canvas.create_line(margin_l, y, w - margin_r, y, fill="#F1F5F9", dash=(2, 2))
            self.canvas.create_text(margin_l - 5, y, text=f"{int(i*100)}%", anchor="e", font=theme.font(8), fill=theme.TEXT_MUTED)

        for i, (label, val) in enumerate(self.data):
            x0 = margin_l + i * (bar_w + bar_gap)
            x1 = x0 + bar_w
            
            # Value Bar
            bar_h = chart_h * val
            y0 = margin_t + chart_h - bar_h
            y1 = margin_t + chart_h
            
            color = theme.COLOR_OK if val >= 0.85 else (theme.COLOR_WARN if val >= 0.65 else theme.COLOR_DANGER)
            
            # Draw bar with rounded top effect
            self.canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline="")
            
            # Label
            self.canvas.create_text((x0 + x1)//2, y1 + 10, text=label, font=theme.font(9), fill=theme.TEXT_SECONDARY)
            
            # Hover value (optional, just text for now)
            if val > 0:
                self.canvas.create_text((x0 + x1)//2, y0 - 8, text=f"{int(val*100)}%", font=theme.font(8, "bold"), fill=theme.TEXT_PRIMARY)


class StoppageTable(ctk.CTkFrame):
    """Scrollable table for shift stoppages history."""

    def __init__(self, parent, **kw):
        super().__init__(parent, fg_color="transparent", **kw)
        # Header
        self.head = ctk.CTkFrame(self, fg_color=theme.BG_TABLE_HEADER, height=34, corner_radius=0)
        self.head.pack(fill="x", padx=(0, 16))
        cols = [("TIME", 0.2), ("DURATION", 0.2), ("CLASSIFICATION", 0.6)]
        for txt, relw in cols:
            lbl = ctk.CTkLabel(
                self.head, text=txt, font=theme.font(10, "bold"),
                text_color=theme.TEXT_SECONDARY, anchor="w"
            )
            lbl.place(relx=sum(c[1] for c in cols[:cols.index((txt, relw))]), rely=0.5, anchor="w", relwidth=relw, x=15)

        self.scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent", corner_radius=0,
        )
        self.scroll.pack(fill="both", expand=True)

    def update_data(self, stoppages):
        for child in self.scroll.winfo_children():
            child.destroy()

        if not stoppages:
            ctk.CTkLabel(
                self.scroll, text="No stoppages recorded in this shift.",
                font=theme.font(12, "italic"), text_color=theme.TEXT_MUTED
            ).pack(pady=40)
            return

        for i, s in enumerate(reversed(stoppages)):
            bg = theme.BG_TABLE_ALT if i % 2 == 0 else "transparent"
            row = ctk.CTkFrame(self.scroll, fg_color=bg, height=38, corner_radius=4)
            row.pack(fill="x", pady=1)

            ts = s.get("timestamp", "")
            if ts:
                time_part = ts.split("T")[-1] if "T" in ts else ts.split(" ")[-1]
                ts = time_part[:5] # HH:MM

            raw_dur = s.get('stop_duration', 0)
            if raw_dur >= 60:
                mins = int(raw_dur // 60)
                secs = int(raw_dur % 60)
                if secs > 0:
                    dur = f"{mins} min {secs}s"
                else:
                    dur = f"{mins} min"
            else:
                dur = f"{int(raw_dur)}s"
            cls = s.get("classification") or "Unclassified"

            # Time
            ctk.CTkLabel(row, text=ts, font=theme.font(12), text_color=theme.TEXT_PRIMARY, anchor="w").place(relx=0, rely=0.5, anchor="w", relwidth=0.2, x=15)
            # Duration
            ctk.CTkLabel(row, text=dur, font=theme.font(12, "bold"), text_color=theme.COLOR_DANGER, anchor="w").place(relx=0.2, rely=0.5, anchor="w", relwidth=0.2, x=15)
            # Classification
            ctk.CTkLabel(row, text=cls, font=theme.font(12), text_color=theme.TEXT_SECONDARY, anchor="w").place(relx=0.4, rely=0.5, anchor="w", relwidth=0.6, x=15)


class ConnectionDot(ctk.CTkFrame):
    """Small dot + label used in the footer."""

    def __init__(self, parent, **kw):
        super().__init__(parent, fg_color="transparent", **kw)
        self.canvas = tk.Canvas(
            self, width=10, height=10, bg=theme.BG_FOOTER,
            highlightthickness=0, bd=0,
        )
        self.canvas.pack(side="left", padx=(0, 6))
        self._dot = self.canvas.create_oval(1, 1, 9, 9, fill=theme.COLOR_DANGER, outline="")
        self.label = ctk.CTkLabel(
            self, text="OFFLINE",
            text_color=theme.COLOR_DANGER, font=theme.font(11, "bold"),
        )
        self.label.pack(side="left")

    def set(self, text: str, color: str):
        self.canvas.itemconfig(self._dot, fill=color)
        self.label.configure(text=text, text_color=color)


class HistoryTable(ctk.CTkFrame):
    """Scrollable table for historical shift records."""

    def __init__(self, parent, show_details_callback=None, **kw):
        super().__init__(parent, fg_color="transparent", **kw)
        self.show_details_callback = show_details_callback
        
        # Load details icon
        assets_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
        img_details_path = os.path.join(assets_dir, "icon_details.png")
        if os.path.exists(img_details_path):
            img_details = Image.open(img_details_path)
            self.icon_details = ctk.CTkImage(light_image=img_details, dark_image=img_details, size=(20, 20))
        else:
            self.icon_details = None

        # Header
        self.head = ctk.CTkFrame(self, fg_color=theme.BG_TABLE_HEADER, height=34, corner_radius=0)
        self.head.pack(fill="x", padx=(0, 16))
        cols = [("DATE", 0.15), ("SHIFT", 0.15), ("OEE %", 0.15), ("OK PARTS", 0.15), ("SCRAP", 0.10), ("DOWNTIME", 0.15), ("DETAILS", 0.15)]
        for txt, relw in cols:
            lbl = ctk.CTkLabel(
                self.head, text=txt, font=theme.font(10, "bold"),
                text_color=theme.TEXT_SECONDARY, anchor="w"
            )
            lbl.place(relx=sum(c[1] for c in cols[:cols.index((txt, relw))]), rely=0.5, anchor="w", relwidth=relw, x=15)

        self.scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent", corner_radius=0,
        )
        self.scroll.pack(fill="both", expand=True)

    def update_data(self, history):
        for child in self.scroll.winfo_children():
            child.destroy()

        if not history:
            ctk.CTkLabel(
                self.scroll, text="No historical shift data loaded.",
                font=theme.font(12, "italic"), text_color=theme.TEXT_MUTED
            ).pack(pady=40)
            return

        for i, h in enumerate(reversed(history)):
            bg = theme.BG_TABLE_ALT if i % 2 == 0 else "transparent"
            row = ctk.CTkFrame(self.scroll, fg_color=bg, height=38, corner_radius=4)
            row.pack(fill="x", pady=1)

            date_str = h.get("date", "")
            shift_name = h.get("shift", "")
            oee_val = f"{int(h.get('oee', 0.0) * 100)}%"
            ok_val = str(h.get("ok", 0))
            scrap_val = str(h.get("scrap", 0))
            
            raw_dur = h.get('downtime_s', 0)
            if raw_dur >= 3600:
                hours = int(raw_dur // 3600)
                mins = int((raw_dur % 3600) // 60)
                dur = f"{hours}h {mins}m"
            elif raw_dur >= 60:
                dur = f"{int(raw_dur // 60)} min"
            else:
                dur = f"{int(raw_dur)}s"

            # Draw labels
            ctk.CTkLabel(row, text=date_str, font=theme.font(12), text_color=theme.TEXT_PRIMARY, anchor="w").place(relx=0, rely=0.5, anchor="w", relwidth=0.15, x=15)
            ctk.CTkLabel(row, text=shift_name, font=theme.font(12), text_color=theme.TEXT_PRIMARY, anchor="w").place(relx=0.15, rely=0.5, anchor="w", relwidth=0.15, x=15)
            
            # OEE colored by threshold
            oee_f = h.get('oee', 0.0)
            oee_col = theme.COLOR_OK if oee_f >= 0.85 else (theme.COLOR_WARN if oee_f >= 0.65 else theme.COLOR_DANGER)
            ctk.CTkLabel(row, text=oee_val, font=theme.font(12, "bold"), text_color=oee_col, anchor="w").place(relx=0.3, rely=0.5, anchor="w", relwidth=0.15, x=15)
            
            ctk.CTkLabel(row, text=ok_val, font=theme.font(12), text_color=theme.TEXT_PRIMARY, anchor="w").place(relx=0.45, rely=0.5, anchor="w", relwidth=0.15, x=15)
            ctk.CTkLabel(row, text=scrap_val, font=theme.font(12), text_color=theme.TEXT_PRIMARY, anchor="w").place(relx=0.6, rely=0.5, anchor="w", relwidth=0.10, x=15)
            ctk.CTkLabel(row, text=dur, font=theme.font(12), text_color=theme.TEXT_SECONDARY, anchor="w").place(relx=0.7, rely=0.5, anchor="w", relwidth=0.15, x=15)

            # Details Button (ⓘ)
            btn_details = ctk.CTkButton(
                row, text="" if self.icon_details else "ⓘ", image=self.icon_details,
                width=30, height=30, fg_color="transparent", hover_color=theme.BG_TABLE_ALT,
                command=lambda h_data=h: self.show_details_callback(h_data) if self.show_details_callback else None
            )
            btn_details.place(relx=0.85, rely=0.5, anchor="w", x=15)


