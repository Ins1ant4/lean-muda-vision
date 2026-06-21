import time
import numpy as np
from enum import Enum
from dataclasses import dataclass

# ==========================================
# 1. CONFIGURATION
# ==========================================
@dataclass
class LogicConfig:
    t_micro: float = 35.0          # < T_micro -> MICRO-ARRÊT
    t_micro_maint: float = 300.0   # Absolute duration threshold for Maintenance
    t_pause_min: float = 1200.0    # 20 min — Official Operator Pause
    t_pause_max: float = 1800.0    # 30 min — Idle Time threshold
    
    t_grace_stop: float = 10.0     # 10s of no movement before "STOPPED"
    t_grace_exit: float = 2.5     # 2.5s outside zone before ending cycle (to capture 3-7s swaps)
    t_reprise: float = 5.0       # 10s of stable movement (Restart Validation / Hysteresis)

    s_presence_retouche_pct: float = 0.60   # 40% Rule (Retouche)
    s_presence_maint_pct: float = 0.35      # 50% Rule (Maintenance)
    movement_threshold: float = 5.0         # Reduced from 20 to easily capture small Juki jig movements
    t_sewing_min: float = 25.0             # Minimum active sewing seconds to validate a cycle (5 minutes)
    t_maint_validation: float = 10.0       # Time in seconds to validate maintenance repair

# ==========================================
# 2. STATES & CLASSIFICATIONS
# ==========================================
class SystemState(Enum):
    IDLE               = "IDLE"
    NORMAL_PRODUCTION  = "Normal Production"
    MACHINE_STOPPED    = "Machine Stopped"
    RESTART_VALIDATION = "Restart Validation"
    QC                 = "QC"
    REWORK             = "Rework Piece"

class MudaClassification(Enum):
    NORMAL_CYCLE      = "Cycle Normal"
    MICRO_STOP        = "Planned Minor Stop"
    REWORK            = "Retouche"
    MAINTENANCE       = "Arret Maintenance"
    OPERATOR_DELAY    = "Attente Operateur"
    PAUSE_OFFICIELLE  = "Pause Officielle"
    IDLE_TIME         = "Idle Time (Abandone)"
    HEALTHY_SUPPORT   = "Healthy Status: Support"
    EMPTY_JIG_WARN    = "Warning: Empty Jig on Table"

# ==========================================
# 3. STATE MACHINE
# ==========================================
class MudaStateMachine:
    def __init__(self, cfg: LogicConfig):
        self.cfg = cfg

        # Production state
        self.current_state      = SystemState.IDLE
        self.last_classification = None

        # Cycle timing
        self.sew_start_frame    = 0
        self.total_sew_frames   = 0
        self.qc_start_frame     = 0
        self.rework_count       = 0
        self.production_credits  = 0  # NEW: Tracks finished cycles waiting for vision confirmation
        self.current_cycle_sewing_time = 0.0 # NEW: Tracks actual active sewing seconds in current cycle
        self.piece_completed_in_cycle = False # NEW: Track if a credit was already awarded during sewing in the current cycle

        # Stop timing
        self.stop_start_time    = 0.0
        self.total_stop_s       = 0.0
        self.not_working_start  = 0.0

        # Accumulated presence during stop
        self.acc_hands_s        = 0.0
        self.acc_maint_s        = 0.0
        self.acc_operator_s     = 0.0
        self.last_update_time   = time.time()

        # Jig movement tracking
        self.jig_history        = [] # List of (x,y)
        self.is_moving          = False
        # Visual Memory (Binary latches during downtime)
        self.memory_blue_vest   = False
        self.memory_hands       = False

        # Timers
        self.reprise_start_time = 0.0
        self.exit_timer_start   = 0.0
        self.validation_active_movement_s = 0.0

        # Quality counters
        self.count_ok           = 0
        self.count_scrap        = 0
        self.all_sew_times      = []

        # Downtime
        self.total_downtime_s   = 0.0
        self.maintenance_active = False
        self.maintenance_start  = 0.0

        # Edge Case tracking
        self.multi_oper_start   = 0.0
        self.jig_vide_start     = 0.0
        self.support_active     = False
        self.jig_warn_active    = False
        
        # Maintenance Validation (Phase 3 detail)
        self.pending_maint_validation = False
        self.maint_validation_start   = 0.0
        self.pending_maint_duration   = 0.0

        # Database Event Queue
        self.session_start_time = time.time()
        self.pending_logs = []

        # Persistent Stats for HUD (Phase 5)
        self.last_stop_data = {
            "duration": 0.0,
            "h_ratio":  0.0,
            "m_ratio":  0.0,
            "o_ratio":  0.0
        }

    def update(self,
               jig_in_juki,        # bool
               jig_coords,         # (x, y) or None
               jig_confirmed,      # bool
               tissu_in_ok,        # bool
               tissu_in_scrap,     # bool
               maint_confirmed,    # bool
               operator_confirmed, # bool
               mains_confirmed,    # bool
               fidx,               # frame index
               fps,                # fps
               mains_in_juki=False,
               maint_in_juki=False,
               jig_vide_on_table=False,
               multi_oper=False):

        current_time = time.time()
        dt = current_time - self.last_update_time
        self.last_update_time = current_time

        # ── Phase 1: Signal Stabilization & Movement Tracking ──────────
        if jig_coords:
            self.jig_history.append(jig_coords)
            if len(self.jig_history) > 30: self.jig_history.pop(0)
            if len(self.jig_history) >= 8:
                # Compare averages of oldest vs newest points to cancel out bounding box jitter
                pts = np.array(self.jig_history)
                avg_start = np.mean(pts[:4], axis=0)
                avg_end = np.mean(pts[-4:], axis=0)
                dist = np.linalg.norm(avg_end - avg_start)
                self.is_moving = dist > self.cfg.movement_threshold
        else:
            self.jig_history = []
            self.is_moving = False

        jig_active = jig_confirmed and self.is_moving

        # Accumulate actual active sewing time in this cycle
        if jig_active:
            self.current_cycle_sewing_time += dt
            if self.current_cycle_sewing_time >= self.cfg.t_sewing_min:
                self.production_credits += 1
                self.piece_completed_in_cycle = True
                print(f"[MACHINE] Active sewing threshold reached ({self.cfg.t_sewing_min}s). Credit awarded automatically! Total credits: {self.production_credits}")
                self.current_cycle_sewing_time = 0.0

        # ── Phase 2: Finite State Machine and Hysteresis ──────────────
        # Accumulate data and Visual Memory during STOPPED states
        if self.current_state in [SystemState.MACHINE_STOPPED, SystemState.RESTART_VALIDATION]:
            if self.stop_start_time > 0:
                self.total_stop_s = current_time - self.stop_start_time
            else:
                self.total_stop_s = 0.0
            
            # Flowchart Phase 2: The 60% Rule (Accumulate presence)
            if mains_in_juki:      self.acc_hands_s    += dt
            if maint_in_juki:      self.acc_maint_s    += dt
            if operator_confirmed: self.acc_operator_s += dt
            
            # Binary visual memory latches (still kept for quick checks)
            if mains_in_juki:      self.memory_hands     = True
            if maint_in_juki:      self.memory_blue_vest = True

        # ── Maintenance downtime clock ─────────────────────────────────
        if maint_confirmed and not self.maintenance_active:
            self.maintenance_active = True
            self.maintenance_start  = current_time
        elif not maint_confirmed and self.maintenance_active:
            self.maintenance_active = False
            self.total_downtime_s += (current_time - self.maintenance_start)

        # ── State Machine Transitions (Flowchart Logic) ────────────────
        if self.current_state == SystemState.IDLE:
            if jig_active:
                self.current_state   = SystemState.NORMAL_PRODUCTION
                self.sew_start_frame = fidx
                self.not_working_start = 0
            else:
                if self.not_working_start == 0: self.not_working_start = current_time
                if (current_time - self.not_working_start) >= self.cfg.t_grace_stop:
                    # Transition to STOPPED to track downtime between cycles
                    prev_start = self.not_working_start
                    self._reset_stop_memory()
                    self.current_state   = SystemState.MACHINE_STOPPED
                    self.stop_start_time = prev_start

        elif self.current_state == SystemState.NORMAL_PRODUCTION:
            if not jig_in_juki: 
                # Exit Grace for ending cycle (Jig removed from machine)
                if self.exit_timer_start == 0: self.exit_timer_start = current_time
                if (current_time - self.exit_timer_start) >= self.cfg.t_grace_exit:
                    # Enforce minimum active sewing time to prevent person-passing/temporary occlusion triggers
                    if self.piece_completed_in_cycle or self.current_cycle_sewing_time >= self.cfg.t_sewing_min:
                        self.total_sew_frames += (fidx - self.sew_start_frame)
                        self.current_state    = SystemState.QC
                        if not self.piece_completed_in_cycle:
                            self.production_credits += 1
                            print(f"[MACHINE] Cycle Finished (Jig Swapped). Credit awarded: {self.production_credits} (Sewing time: {self.current_cycle_sewing_time:.1f}s)")
                        else:
                            print(f"[MACHINE] Cycle Finished (Jig Swapped). Credit was already awarded automatically during sewing.")
                        self.current_cycle_sewing_time = 0.0 # Reset sewing time for the next piece after credit is added
                        self.piece_completed_in_cycle = False # Reset flag
                        self.qc_start_frame   = fidx
                        self.exit_timer_start = 0
                    else:
                        # Less than t_sewing_min of active sewing: temporary camera block by passing person
                        print(f"[DEBUG] Jig presence lost, but ignored: active sewing too short ({self.current_cycle_sewing_time:.1f}s < {self.cfg.t_sewing_min}s) and no piece completed. Likely camera occlusion.")
                        self.exit_timer_start = 0
            else:
                self.exit_timer_start = 0
                if not jig_active:
                    if self.not_working_start == 0: self.not_working_start = current_time
                    if (current_time - self.not_working_start) >= self.cfg.t_grace_stop:
                        # Machine stopped (Trigger from Flowchart)
                        prev_start = self.not_working_start
                        self._reset_stop_memory()
                        self.current_state   = SystemState.MACHINE_STOPPED
                        self.stop_start_time = prev_start
                else:
                    self.not_working_start = 0

        elif self.current_state == SystemState.MACHINE_STOPPED:
            if jig_active:
                # Classify stop immediately to see if it is maintenance (don't reset memory yet)
                is_maint = self._classify_muda(reset_memory=False)
                
                if is_maint:
                    # Skip RESTART_VALIDATION, start 20s repair validation immediately in NORMAL_PRODUCTION
                    self.current_state = SystemState.NORMAL_PRODUCTION
                    self.sew_start_frame = fidx
                    self.reprise_start_time = 0.0
                    self.not_working_start = 0
                    
                    self.pending_maint_validation = True
                    self.maint_validation_start   = current_time
                    self.pending_maint_duration   = self.last_stop_data["duration"]
                    # Reset memory now that we are transitioning permanently
                    self._reset_stop_memory()
                    print("[VALIDATION] Maintenance detected. Bypassing 5s stabilizing validation. Starting 20s repair validation directly.")
                else:
                    # Go to normal RESTART_VALIDATION (5s stabilizing countdown)
                    self.current_state = SystemState.RESTART_VALIDATION
                    self.reprise_start_time = current_time
                    self.not_working_start = 0
                    self.validation_active_movement_s = 0.0

        elif self.current_state == SystemState.RESTART_VALIDATION:
            if jig_active:
                self.not_working_start = 0
                self.validation_active_movement_s += dt
            else:
                if self.not_working_start == 0: self.not_working_start = current_time
            
            # If it stops moving for more than t_grace_stop (10 seconds) during validation, abort!
            if self.not_working_start > 0 and (current_time - self.not_working_start) >= self.cfg.t_grace_stop:
                self.current_state = SystemState.MACHINE_STOPPED
                self.reprise_start_time = 0.0
                self.not_working_start = 0
                self.validation_active_movement_s = 0.0
            elif (current_time - self.reprise_start_time) >= self.cfg.t_reprise and self.validation_active_movement_s >= (self.cfg.t_reprise * 0.5):
                # OUI -> Validated Restart
                self.current_state   = SystemState.NORMAL_PRODUCTION
                self.sew_start_frame = fidx
                self.reprise_start_time = 0.0
                
                # Stop has already been classified at the start of transition, so we log it and reset memory!
                self.pending_logs.append(("muda", self.last_classification, self.last_stop_data["duration"]))
                self._reset_stop_memory()

        elif self.current_state == SystemState.QC:
            if jig_active:
                self.not_working_start = 0
                if jig_in_juki:
                    # Returning to machine area (New cycle or Rework)
                    self.current_state = SystemState.NORMAL_PRODUCTION
                    # If it was QC and returned to machine, it's often a Rework
                    self.rework_count += 1 
            else:
                # Not moving in QC zone
                if self.not_working_start == 0: self.not_working_start = current_time
                if (current_time - self.not_working_start) >= self.cfg.t_grace_stop:
                    # Transition to STOPPED to allow Muda classification if they stop here
                    prev_start = self.not_working_start
                    self._reset_stop_memory()
                    self.current_state   = SystemState.MACHINE_STOPPED
                    self.stop_start_time = prev_start

        # ── Global Piece Counting (Triggers from any state to avoid misses) ──
        if tissu_in_ok:
            self.count_ok += 1
            sew_t = self.total_sew_frames / fps
            self.all_sew_times.append(sew_t)
            self.pending_logs.append(("production", self.count_ok + self.count_scrap, "OK", sew_t, 0.0, self.rework_count))
            self._reset_cycle()

        elif tissu_in_scrap:
            self.count_scrap += 1
            sew_t = self.total_sew_frames / fps
            self.all_sew_times.append(sew_t)
            self.pending_logs.append(("production", self.count_ok + self.count_scrap, "Scrap", sew_t, 0.0, self.rework_count))
            self._reset_cycle()

        # ── Special Edge Cases & Health Rules ─────────────────────────
        # Rule: Healthy Status (Support) -> Working + >1 Operator > 1 min
        if self.current_state == SystemState.NORMAL_PRODUCTION and multi_oper:
            if self.multi_oper_start == 0: self.multi_oper_start = current_time
            if (current_time - self.multi_oper_start) >= 60.0: # 1 minute
                self.support_active = True
                self.last_classification = MudaClassification.HEALTHY_SUPPORT
        else:
            self.multi_oper_start = 0
            if self.current_state == SystemState.NORMAL_PRODUCTION: self.support_active = False

        # Rule: Maintenance Validation (1 min of flawless run)
        if self.pending_maint_validation:
            if self.current_state == SystemState.NORMAL_PRODUCTION:
                if (current_time - self.maint_validation_start) >= self.cfg.t_maint_validation:
                    self.pending_maint_validation = False
                    # LOCKED as Maintenance Intervention
                    self.pending_logs.append(("muda", MudaClassification.MAINTENANCE, self.pending_maint_duration))
            elif self.current_state == SystemState.MACHINE_STOPPED:
                # Interrupted! Validation failed (revert to Operator Delay)
                self.pending_maint_validation = False
                if self.last_classification == MudaClassification.MAINTENANCE:
                    self.last_classification = MudaClassification.OPERATOR_DELAY
                
                self.pending_logs.append(("muda", self.last_classification or MudaClassification.OPERATOR_DELAY, self.pending_maint_duration))

        # Rule: Empty Jig Warning -> jig_vide on table > 3 min
        if jig_vide_on_table:
            if self.jig_vide_start == 0: self.jig_vide_start = current_time
            if (current_time - self.jig_vide_start) >= 180.0: # 3 minutes
                self.jig_warn_active = True
                self.last_classification = MudaClassification.EMPTY_JIG_WARN
        else:
            self.jig_vide_start = 0
            self.jig_warn_active = False

    def _classify_muda(self, reset_memory=True):
        # ── Phase 3: Visual Memory and Muda Classification (60% Rule) ──
        t = self.total_stop_s
        if t <= 0 or self.stop_start_time == 0: 
            # Fallback for safety (prevents timestamp bug)
            self.last_stop_data["duration"] = 0.0
            self.last_classification = MudaClassification.NORMAL_CYCLE
            return False

        # Durations to Ratios
        h_ratio = self.acc_hands_s / t
        m_ratio = self.acc_maint_s / t
        o_ratio = self.acc_operator_s / t
        is_maint = False

        # Store for HUD persistence
        self.last_stop_data = {
            "duration": t,
            "h_ratio":  h_ratio,
            "m_ratio":  m_ratio,
            "o_ratio":  o_ratio,
            "abs_maint": self.acc_maint_s
        }

        # Check maintenance first since maintenance presence overrides other classifications
        # (even if t < t_micro)
        if m_ratio >= self.cfg.s_presence_maint_pct or self.acc_maint_s >= self.cfg.t_micro_maint:
            self.last_classification = MudaClassification.MAINTENANCE
            is_maint = True
        elif t < self.cfg.t_micro:
            # Phase 1: Micro-Stoppage
            self.last_classification = MudaClassification.MICRO_STOP
        else:
            # Phase 2: Advanced Visual Classification (The 60% Rule)
            if h_ratio >= self.cfg.s_presence_retouche_pct:
                # Hands intersecting jig_charge area > 60%
                self.last_classification = MudaClassification.REWORK
            else:
                # Phase 3: Temporal Fallbacks (Diagnostic by Elimination)
                if t <= self.cfg.t_pause_min:
                    # < 20 minutes (Operator Delay / Perte non justifiée)
                    self.last_classification = MudaClassification.OPERATOR_DELAY
                elif self.cfg.t_pause_min < t <= self.cfg.t_pause_max:
                    # Between 20 and 30 minutes (Official Operator Pause)
                    self.last_classification = MudaClassification.PAUSE_OFFICIELLE
                else:
                    # > 30 minutes (Idle Time)
                    self.last_classification = MudaClassification.IDLE_TIME
        
        if reset_memory:
            self._reset_stop_memory()
        return is_maint

    def _reset_cycle(self):
        if self.current_state not in [SystemState.MACHINE_STOPPED, SystemState.RESTART_VALIDATION]:
            self.current_state = SystemState.IDLE
            self.not_working_start = 0
            
        self.total_sew_frames = 0
        self.rework_count = 0
        self.current_cycle_sewing_time = 0.0 # Reset sewing time for the next piece
        self.piece_completed_in_cycle = False

    def _reset_stop_memory(self):
        self.acc_hands_s = self.acc_maint_s = self.acc_operator_s = 0.0
        self.total_stop_s = self.stop_start_time = self.not_working_start = 0.0
        self.memory_blue_vest = self.memory_hands = False
        self.validation_active_movement_s = 0.0