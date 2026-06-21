"""Entry point for the FORVIA AMS dashboard."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from data_service import DataService
from dashboard_ui import Dashboard


def _resolve_env() -> str:
    """Prefer parent VISION/.env (shared with vision_loop), fall back to local Dashboard/.env."""
    parent = os.path.normpath(os.path.join(HERE, "..", ".env"))
    local = os.path.join(HERE, ".env")
    if os.path.exists(parent):
        return parent
    return local


if __name__ == "__main__":
    ds = DataService(_resolve_env())
    app = Dashboard(ds)
    app.mainloop()
