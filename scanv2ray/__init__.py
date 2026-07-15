# The legacy CustomTkinter UI needs tkinter; the PySide6 UI (ui_qt) does not.
# Import the legacy app lazily/optionally so the Qt entry point works in
# environments without tkinter installed.
try:
    from .ui import ConfigScannerApp
except Exception:  # pragma: no cover - tkinter not available
    ConfigScannerApp = None

__all__ = ["ConfigScannerApp"]
