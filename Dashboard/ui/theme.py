"""Centralized design tokens. Edit here to re-skin the whole dashboard."""
import customtkinter as ctk


# ── Brand ────────────────────────────────────────────────
BRAND_PRIMARY = "#1F20C3"   # FORVIA brand
BRAND_DARK    = "#15166B"
BRAND_LIGHT   = "#EEF0FF"

# ── Surfaces ─────────────────────────────────────────────
BG_APP          = "#F8F9FC"
BG_CARD         = "#FFFFFF"
BG_HEADER       = "#FFFFFF"
BG_TABLE_HEADER = "#F8FAFC"
BG_TABLE_ALT    = "#F1F5F9"
BG_FOOTER       = "#FFFFFF"

BORDER_LIGHT  = "#E2E4EE"
BORDER_MEDIUM = "#C9CCE0"

# ── Text ─────────────────────────────────────────────────
TEXT_PRIMARY   = "#161629"
TEXT_SECONDARY = "#5C6178"
TEXT_MUTED     = "#9499AB"
TEXT_INVERSE   = "#FFFFFF"

# ── Semantic ─────────────────────────────────────────────
COLOR_OK     = "#16A34A"
COLOR_WARN   = "#F59E0B"
COLOR_DANGER = "#DC2626"
COLOR_INFO   = BRAND_PRIMARY
GAUGE_TRACK  = "#E2E8F0"

# ── Per-classification colors for the donut chart ────────
CLASSIFICATION_COLORS = {
    "Arret Maintenance":            "#1F20C3",   # brand
    "Retouche":              "#7B7CFB",
    "Attente Operateur":            "#F59E0B",
    "Planned Minor Stop":           "#16A34A",
    "Pause Officielle":             "#0EA5E9",
    "Idle Time (Abandone)":         "#DC2626",
    "Cycle Normal":                 "#94A3B8",
    "Healthy Status: Support":      "#22C55E",
    "Warning: Empty Jig on Table":  "#F97316",
}
DEFAULT_CHART_COLOR = "#6B7280"

# ── Spacing ──────────────────────────────────────────────
PAD_XS, PAD_SM, PAD_MD, PAD_LG, PAD_XL = 4, 8, 12, 18, 24

# ── Radii ────────────────────────────────────────────────
RADIUS_SM = 6
RADIUS_MD = 10
RADIUS_LG = 14

# ── Typography ───────────────────────────────────────────
FAMILY = "Segoe UI"


def font(size=12, weight="normal", family=None):
    slant = "roman"
    if weight == "italic":
        weight = "normal"
        slant = "italic"
    return ctk.CTkFont(family=family or FAMILY, size=size, weight=weight, slant=slant)
