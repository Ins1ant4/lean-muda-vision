import tkinter as tk
import customtkinter as ctk
import config
from ui import theme

class SupervisorLoginWindow(ctk.CTkToplevel):
    def __init__(self, parent, on_success):
        super().__init__(parent)
        self.parent = parent
        self.on_success = on_success
        
        self.title("Supervisor Login")
        self.geometry("380x250")
        self.resizable(False, False)
        self.configure(fg_color=theme.BG_APP)
        
        # Focus/Grab
        self.grab_set()
        self.focus_force()
        
        # Center the window relative to parent
        self.update_idletasks()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_x()
        py = parent.winfo_y()
        w = self.winfo_width()
        h = self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")
        
        # Layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        frame = ctk.CTkFrame(self, fg_color=theme.BG_CARD, corner_radius=10, border_width=1, border_color=theme.BORDER_LIGHT)
        frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        frame.grid_columnconfigure(1, weight=1)
        
        # Title
        ctk.CTkLabel(
            frame, text="SUPERVISOR LOGIN",
            font=theme.font(14, "bold"), text_color=theme.BRAND_PRIMARY
        ).grid(row=0, column=0, columnspan=2, pady=(15, 15))
        
        # Username
        ctk.CTkLabel(frame, text="Username:", font=theme.font(11, "bold"), text_color=theme.TEXT_PRIMARY).grid(row=1, column=0, padx=(15, 5), pady=5, sticky="e")
        self.ent_user = ctk.CTkEntry(frame, font=theme.font(12), width=180, border_color=theme.BORDER_MEDIUM)
        self.ent_user.grid(row=1, column=1, padx=(5, 15), pady=5, sticky="w")
        self.ent_user.insert(0, "admin")
        
        # Password
        ctk.CTkLabel(frame, text="Password:", font=theme.font(11, "bold"), text_color=theme.TEXT_PRIMARY).grid(row=2, column=0, padx=(15, 5), pady=5, sticky="e")
        self.ent_pass = ctk.CTkEntry(frame, show="*", font=theme.font(12), width=180, border_color=theme.BORDER_MEDIUM)
        self.ent_pass.grid(row=2, column=1, padx=(5, 15), pady=5, sticky="w")
        
        # Error Label
        self.lbl_err = ctk.CTkLabel(frame, text="", font=theme.font(10, "bold"), text_color=theme.COLOR_DANGER)
        self.lbl_err.grid(row=3, column=0, columnspan=2, pady=2)
        
        # Buttons
        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.grid(row=4, column=0, columnspan=2, pady=(5, 15))
        
        ctk.CTkButton(
            btn_frame, text="Cancel", font=theme.font(11), width=80, height=28,
            fg_color="transparent", border_width=1, border_color=theme.BORDER_MEDIUM,
            text_color=theme.TEXT_SECONDARY, hover_color=theme.BG_TABLE_ALT,
            command=self.destroy
        ).pack(side="left", padx=5)
        
        ctk.CTkButton(
            btn_frame, text="Login", font=theme.font(11, "bold"), width=80, height=28,
            fg_color=theme.BRAND_PRIMARY, hover_color=theme.BRAND_DARK,
            command=self._attempt_login
        ).pack(side="left", padx=5)
        
        # Key bindings
        self.bind("<Return>", lambda e: self._attempt_login())
        self.bind("<Escape>", lambda e: self.destroy())
        self.ent_pass.focus_set()

    def _attempt_login(self):
        user = self.ent_user.get().strip()
        pwd = self.ent_pass.get().strip()
        
        # Hardcoded supervisor credentials as per spec
        if user == "admin" and pwd == "forvia-admin":
            self.destroy()
            self.on_success()
        else:
            self.lbl_err.configure(text="Invalid Username or Password.")
            self.ent_pass.delete(0, "end")
            self.ent_pass.focus_set()


class SupervisorSettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent, on_save):
        super().__init__(parent)
        self.parent = parent
        self.on_save = on_save
        
        self.title("Supervisor Settings")
        self.geometry("480x350")
        self.resizable(False, False)
        self.configure(fg_color=theme.BG_APP)
        
        # Focus/Grab
        self.grab_set()
        self.focus_force()
        
        # Center the window
        self.update_idletasks()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_x()
        py = parent.winfo_y()
        w = self.winfo_width()
        h = self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")
        
        # Layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        frame = ctk.CTkFrame(self, fg_color=theme.BG_CARD, corner_radius=10, border_width=1, border_color=theme.BORDER_LIGHT)
        frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        frame.grid_columnconfigure(0, weight=1)
        
        # Title
        ctk.CTkLabel(
            frame, text="TARGET PIECES PER HOUR (8H SHIFT)",
            font=theme.font(13, "bold"), text_color=theme.BRAND_PRIMARY
        ).grid(row=0, column=0, pady=(15, 10))
        
        # Grid Frame for 2x4 layout
        grid_frame = ctk.CTkFrame(frame, fg_color="transparent")
        grid_frame.grid(row=1, column=0, padx=15, pady=5, sticky="nsew")
        for col in range(4):
            grid_frame.grid_columnconfigure(col, weight=1, uniform="grid_col")
            
        # Get hourly targets
        hourly_targets = getattr(config, "HOURLY_TARGETS", [7.0]*8)
        
        self.entries = []
        for i in range(8):
            row_idx = 0 if i < 4 else 2
            col_idx = i % 4
            
            # Label
            lbl = ctk.CTkLabel(grid_frame, text=f"Hour {i+1}", font=theme.font(10, "bold"), text_color=theme.TEXT_SECONDARY)
            lbl.grid(row=row_idx, column=col_idx, padx=5, pady=(5, 2), sticky="s")
            
            # Entry
            entry = ctk.CTkEntry(grid_frame, font=theme.font(11), width=75, height=28, border_color=theme.BORDER_MEDIUM, justify="center")
            entry.grid(row=row_idx+1, column=col_idx, padx=5, pady=(0, 5))
            
            # Insert current target value
            val = hourly_targets[i]
            entry.insert(0, f"{val:.1f}")
            self.entries.append(entry)
            
        # Error Label
        self.lbl_err = ctk.CTkLabel(frame, text="", font=theme.font(10, "bold"), text_color=theme.COLOR_DANGER)
        self.lbl_err.grid(row=2, column=0, pady=5)
        
        # Buttons
        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.grid(row=3, column=0, pady=(10, 15))
        
        ctk.CTkButton(
            btn_frame, text="Cancel", font=theme.font(11), width=80, height=28,
            fg_color="transparent", border_width=1, border_color=theme.BORDER_MEDIUM,
            text_color=theme.TEXT_SECONDARY, hover_color=theme.BG_TABLE_ALT,
            command=self.destroy
        ).pack(side="left", padx=5)
        
        ctk.CTkButton(
            btn_frame, text="Save Settings", font=theme.font(11, "bold"), width=110, height=28,
            fg_color=theme.BRAND_PRIMARY, hover_color=theme.BRAND_DARK,
            command=self._save_settings
        ).pack(side="left", padx=5)
        
        # Bindings
        self.bind("<Return>", lambda e: self._save_settings())
        self.bind("<Escape>", lambda e: self.destroy())
        
        # Focus on the first entry
        if self.entries:
            self.entries[0].focus_set()
            self.entries[0].select_range(0, "end")
            
    def _save_settings(self):
        new_targets = []
        for i, entry in enumerate(self.entries):
            val_str = entry.get().strip()
            try:
                val = float(val_str)
                if val <= 0:
                    raise ValueError()
                new_targets.append(val)
            except ValueError:
                self.lbl_err.configure(text=f"Hour {i+1} must be a positive number.")
                entry.focus_set()
                entry.select_range(0, "end")
                return
                
        # Save config persistently using the new config function
        config.update_hourly_targets(new_targets)
        
        self.destroy()
        self.on_save()
