"""PySide6 front end for ScanV2Ray.

A view-layer rewrite of ``scanv2ray/ui.py`` (CustomTkinter) that preserves 100%
of the original behaviour.  All business logic lives unchanged in
``engine.py`` / ``scanner.py`` / ``parser.py`` / ``configs.py`` / ``naming.py``.

The worker stays a plain daemon ``threading.Thread``; it NEVER touches a widget.
It only emits typed ``ScanSignals``; slots update widgets on the GUI thread.
"""

import csv
import json
import math
import os
import sys
import threading
import time

from PySide6.QtCore import (
    Qt, QObject, Signal, QTimer, QRectF, QPoint, QPointF,
    QPropertyAnimation, QEasingCurve, Property,
)
from PySide6.QtGui import (
    QColor, QPainter, QPen, QBrush, QFont,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFrame, QLabel, QPushButton, QLineEdit, QPlainTextEdit, QListWidget,
    QCheckBox, QScrollArea, QButtonGroup, QFileDialog, QDialog,
    QSizePolicy, QGraphicsDropShadowEffect, QAbstractItemView,
)

from .parser import extract_links, resolve_source, parse_link
from .scanner import Scanner
from . import engine
from . import naming


# ---------------------------------------------------------------------------
# Palette — the scanner's own calm indigo identity (lifted verbatim from ui.py)
# ---------------------------------------------------------------------------
COLOR_TOKENS = {
    "background": "#0F1216",
    "bgsoft":     "#12161C",
    "surface":    "#171B22",
    "surface2":   "#1E232C",
    "elev":       "#232935",
    "line":       "#2A313D",
    "border":       "rgba(109,139,255,0.20)",   # accent-tinted hairline
    "borderstrong": "rgba(109,139,255,0.55)",
    "accent":     "#6D8BFF",
    "accent2":    "#8098FF",
    "accentdim":  "#39406B",
    "text":       "#E6E9EF",
    "muted":      "#8A93A2",
    "faint":      "#5B6472",
    "fast":       "#46C48A",   # success
    "medium":     "#E6B34E",   # warning
    "slow":       "#E08A4C",
    "dead":       "#E06A6A",   # danger
    "white":      "#FFFFFF",
    "deaddim":    "#5A3A42",
    "amberhover": "#C99A3E",
    "redhover":   "#C95A5A",
}

# Resolved literals for the custom painted widgets (QPainter needs real values).
BG        = COLOR_TOKENS["background"]
SURFACE   = COLOR_TOKENS["surface"]
SURFACE2  = COLOR_TOKENS["surface2"]
ELEV      = COLOR_TOKENS["elev"]
LINE      = COLOR_TOKENS["line"]
ACCENT    = COLOR_TOKENS["accent"]
ACCENT2   = COLOR_TOKENS["accent2"]
ACCENTDIM = COLOR_TOKENS["accentdim"]
TEXT      = COLOR_TOKENS["text"]
MUTED     = COLOR_TOKENS["muted"]
FAINT     = COLOR_TOKENS["faint"]
FAST      = COLOR_TOKENS["fast"]
MEDIUM    = COLOR_TOKENS["medium"]
SLOW      = COLOR_TOKENS["slow"]
DEAD      = COLOR_TOKENS["dead"]
WHITE     = COLOR_TOKENS["white"]

PROTOCOLS = ['vmess', 'vless', 'ss', 'trojan', 'socks', 'http',
             'hysteria2', 'tuic', 'anytls']

PRESETS = {
    'Slow':   {'precheck': '80',  'test': '12', 'speed': '6',  'timeout': '5000'},
    'Medium': {'precheck': '200', 'test': '32', 'speed': '24', 'timeout': '3500'},
    'Fast':   {'precheck': '400', 'test': '64', 'speed': '40', 'timeout': '2500'},
}

SITE_TARGETS_DEFAULT = [
    ('YouTube', 'https://www.youtube.com'),
    ('Instagram', 'https://www.instagram.com'),
    ('Telegram', 'https://web.telegram.org'),
    ('ChatGPT', 'https://chatgpt.com'),
    ('Google', 'https://www.google.com'),
]


# ---------------------------------------------------------------------------
# Global stylesheet (token template + substitution helper)
# ---------------------------------------------------------------------------
STYLE = """
* { font-family: "Segoe UI"; font-size: 13px; color: $text; outline: 0; }
*[technical="true"] { font-family: "Courier New", "Cascadia Mono", "Consolas"; }

QWidget#root { background: $background; }
QScrollArea { background: transparent; border: 0; }
QScrollArea > QWidget > QWidget { background: transparent; }

/* ---- Cards ---- */
QFrame#card {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                stop:0 rgba(23,27,34,0.96), stop:1 rgba(18,22,28,0.94));
    border: 1px solid $border;
    border-radius: 16px;
}
QFrame#card:hover { border-color: $borderstrong; }
QLabel#cardTitle { font-size: 15px; font-weight: 800; color: $text; }
QLabel#cardSub   { font-size: 12px; color: $muted; }

/* ---- Header ---- */
QFrame#header      { background: $surface; border-bottom: 1px solid $line; }
QLabel#appTitle    { font-size: 26px; font-weight: 800; color: $text; }
QLabel#appSubtitle { font-size: 12px; color: $muted; }
QFrame#statusChip  { background: $surface2; border: 1px solid $line; border-radius: 20px; }
QLabel#statusText  { font-size: 12px; font-weight: 800; color: $text; }
QLabel#linkCount   { font-size: 14px; font-weight: 800; color: $accent; }
QLabel#protoCount  { font-size: 18px; font-weight: 800; color: $text; }
QLabel#folderLabel { font-size: 11px; color: $muted; }

/* ---- Buttons ---- */
QPushButton {
    min-height: 34px; padding: 8px 14px; border-radius: 10px;
    background: $surface2; border: 1px solid $line; color: $text; font-weight: 700;
}
QPushButton:hover    { background: $elev; border-color: $accentdim; }
QPushButton:disabled { background: rgba(30,35,44,0.5); color: $faint; }
QPushButton#primary  {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 $accent, stop:1 $accent2);
    border: 1px solid rgba(128,152,255,0.7); color: #0B0E14; font-weight: 800; min-height: 44px;
}
QPushButton#primary:hover    { background: $accent2; }
QPushButton#primary:disabled { background: rgba(57,64,107,0.5); border-color: $line; color: $faint; }
QPushButton#danger   { border: 1px solid $deaddim; color: $dead; }
QPushButton#danger:hover { background: rgba(224,106,106,0.12); }
QPushButton#warn     { color: $medium; }
QPushButton#pause[mode="paused"] {
    background: $accent; border-color: $accent2; color: #0B0E14;
}
QPushButton#pause[mode="run"] {
    background: $medium; border-color: $amberhover; color: #0B0E14;
}

/* ---- Inputs ---- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox {
    background: $background; border: 1px solid $line; border-radius: 10px;
    padding: 6px 10px; color: $text; selection-background-color: $accent;
}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus { border-color: $accent; }

/* ---- CheckBox ---- */
QCheckBox { spacing: 8px; color: $text; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid $faint;
    border-radius: 4px; background: $background; }
QCheckBox::indicator:hover   { border-color: $accent; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent2; }

/* ---- Segmented ---- */
QPushButton#segment         { border-radius: 8px; background: transparent; border: 1px solid transparent; color: $muted; font-weight: 700; min-height: 28px; }
QPushButton#segment:hover   { background: $elev; }
QPushButton#segment:checked { background: $accent; color: #0B0E14; }

/* ---- Frames used as inner panels ---- */
QFrame#panel { background: $surface2; border: 1px solid $line; border-radius: 10px; }
QFrame#tile  { background: $surface2; border: 1px solid $line; border-radius: 10px; }
QLabel#tileValue { font-size: 28px; font-weight: 800; color: $text; }
QLabel#tileCap   { font-size: 12px; color: $muted; }

/* ---- Lists / log ---- */
QListWidget#sources { background: $surface2; border: 1px solid $line; border-radius: 10px; }
QListWidget#sources::item:selected { background: $accent; color: $white; }
QPlainTextEdit#log { background: rgba(15,18,22,0.98); border: 1px solid $line; border-radius: 10px; }
QPlainTextEdit#sourceInput { background: $surface2; }

/* ---- Toast ---- */
QFrame#toast { background: rgba(23,27,34,0.98); border: 1px solid $border; border-radius: 12px; }
QFrame#toast[kind="success"] { border-color: rgba(70,196,138,0.6); }
QFrame#toast[kind="danger"]  { border-color: rgba(224,106,106,0.6); }
QFrame#toast[kind="warning"] { border-color: rgba(230,179,78,0.6); }
QLabel#toastText { color: $text; font-weight: 700; }

/* ---- Dialog ---- */
QDialog { background: $background; }

/* ---- Scrollbars ---- */
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: $line; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: $accentdim; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
"""


def build_style(template=STYLE):
    """Substitute $token names (longest key first) — spoofer pattern."""
    out = template
    for name, value in sorted(COLOR_TOKENS.items(), key=lambda i: -len(i[0])):
        out = out.replace(f"${name}", value)
    return out


def _restyle(w):
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


# ---------------------------------------------------------------------------
# Motion gate (lifted verbatim from the spoofer)
# ---------------------------------------------------------------------------
def _system_motion_enabled():
    v = os.environ.get("V2SCAN_REDUCED_MOTION", "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return False
    if v in ("0", "false", "no", "off"):
        return True
    if os.name == "nt":
        try:
            import ctypes
            enabled = ctypes.c_int(1)
            ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)
            return bool(enabled.value)
        except Exception:
            return True
    return True


MOTION_ENABLED = _system_motion_enabled()


def _animations_enabled():
    app = QApplication.instance()
    return MOTION_ENABLED and (app is None or app.platformName() != "offscreen")


def _has_event_loop():
    """True when a real (non-offscreen) event loop exists to service QTimers.

    Independent of the motion gate: coalescing/flushing timers should still run
    under reduced motion on a real display, and only fall back to synchronous
    flushing when there is genuinely no loop (tests / offscreen).
    """
    app = QApplication.instance()
    return app is not None and app.platformName() != "offscreen"


# ---------------------------------------------------------------------------
# Worker bridge
# ---------------------------------------------------------------------------
class ScanSignals(QObject):
    status   = Signal(str)
    progress = Signal(float)
    counts   = Signal(int, int, int, int)   # fast, medium, slow, dead
    phase    = Signal(str)                   # 'precheck' | 'test' | 'idle'
    log      = Signal(str)
    dead     = Signal(object)
    result   = Signal(object)
    toast    = Signal(str, str)              # (message, kind)
    finished = Signal(bool, int)             # (True=completed/False=aborted, scan_generation)


# ---------------------------------------------------------------------------
# Custom painted widgets
# ---------------------------------------------------------------------------
class StatusDot(QWidget):
    """A small solid status dot with a settable color."""

    def __init__(self, color=MUTED, diameter=12, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._d = diameter
        self._pulse_alpha = 1.0
        self._pulse_phase = 0.0
        self._pulse_timer = None
        self.setFixedSize(diameter + 2, diameter + 2)

    def set_color(self, color):
        self._color = QColor(color)
        self.update()

    def start_pulse(self):
        """Begin a soft breathing pulse (gated on the motion setting)."""
        if not _animations_enabled():
            self.stop_pulse()
            return
        if self._pulse_timer is None:
            self._pulse_timer = QTimer(self)
            self._pulse_timer.setInterval(70)
            self._pulse_timer.timeout.connect(self._pulse_tick)
        if not self._pulse_timer.isActive():
            self._pulse_timer.start()

    def stop_pulse(self):
        if self._pulse_timer is not None and self._pulse_timer.isActive():
            self._pulse_timer.stop()
        self._pulse_alpha = 1.0
        self.update()

    def _pulse_tick(self):
        self._pulse_phase = (self._pulse_phase + 0.18) % (2 * math.pi)
        self._pulse_alpha = 0.675 + 0.325 * math.sin(self._pulse_phase)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        col = QColor(self._color)
        col.setAlphaF(max(0.0, min(1.0, self._pulse_alpha)))
        p.setBrush(QBrush(col))
        d = self._d
        x = (self.width() - d) / 2
        y = (self.height() - d) / 2
        p.drawEllipse(QRectF(x, y, d, d))
        p.end()


class ToggleSwitch(QCheckBox):
    """A pill toggle that still behaves as a QCheckBox (isChecked / stateChanged)."""

    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self):
        base = super().sizeHint()
        return base.expandedTo(base.__class__(base.width() + 46, max(base.height(), 22)))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        track_w, track_h = 40, 20
        y = (self.height() - track_h) / 2
        rect = QRectF(0, y, track_w, track_h)
        on = self.isChecked()
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(ACCENT if on else SURFACE2)))
        p.drawRoundedRect(rect, track_h / 2, track_h / 2)
        if not on:
            p.setPen(QPen(QColor(LINE), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), track_h / 2, track_h / 2)
        knob_d = track_h - 6
        kx = (track_w - knob_d - 3) if on else 3
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(WHITE if on else MUTED)))
        p.drawEllipse(QRectF(kx, y + 3, knob_d, knob_d))
        # label
        p.setPen(QColor(TEXT))
        p.setFont(self.font())
        p.drawText(QRectF(track_w + 8, 0, self.width() - track_w - 8, self.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.end()


class CyberProgressBar(QWidget):
    """Flat progress track with an accent fill and a travelling shimmer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._phase = 0.0
        self.setFixedHeight(8)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._timer = QTimer(self)
        self._timer.setInterval(45)
        self._timer.timeout.connect(self._tick)

    def is_animating(self):
        return self._timer.isActive()

    def _tick(self):
        self._phase = (self._phase + 0.06) % 1.0
        self.update()

    def _sync_timer(self):
        want = _animations_enabled() and 0.0 < self._value < 1.0
        if want and not self._timer.isActive():
            self._timer.start()
        elif not want and self._timer.isActive():
            self._timer.stop()

    def set_value(self, value):
        try:
            self._value = max(0.0, min(1.0, float(value)))
        except Exception:
            self._value = 0.0
        self._sync_timer()
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(SURFACE2)))
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)
        fill_w = w * self._value
        if fill_w > 0:
            p.setBrush(QBrush(QColor(ACCENT)))
            p.drawRoundedRect(QRectF(0, 0, fill_w, h), r, r)
            if self._timer.isActive():
                sx = fill_w * self._phase
                p.setBrush(QBrush(QColor(ACCENT2)))
                p.drawRoundedRect(QRectF(max(0.0, sx - 14), 0, 28, h), r, r)
        p.end()


class DonutWidget(QWidget):
    """Hand-drawn donut chart — port of the CTkCanvas ``_draw_donut`` geometry."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._counts = (0, 0, 0, 0)          # target counts (rendered legend values)
        self._from_counts = (0, 0, 0, 0)     # counts at the start of the current tween
        self._anim_progress = 1.0            # 0..1 interpolation fraction
        self._count_anim = None
        self.setMinimumSize(200, 292)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def _get_anim_progress(self):
        return self._anim_progress

    def _set_anim_progress(self, value):
        self._anim_progress = value
        self.update()

    _anim_progress_prop = Property(float, _get_anim_progress, _set_anim_progress)

    def set_counts(self, fast, medium, slow, dead):
        new = (fast, medium, slow, dead)
        if new == self._counts:
            return
        if _animations_enabled():
            # Ease from the currently rendered counts to the new counts.
            self._from_counts = self._rendered_counts()
            self._counts = new
            anim = QPropertyAnimation(self, b'_anim_progress_prop', self)
            anim.setDuration(300)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            self._count_anim = anim   # anti-GC
            self._anim_progress = 0.0
            anim.start()
        else:
            self._from_counts = new
            self._counts = new
            self._anim_progress = 1.0
        self.update()

    def _rendered_counts(self):
        """The counts currently on screen (interpolated mid-tween)."""
        t = self._anim_progress
        return tuple(fr + (to - fr) * t
                     for fr, to in zip(self._from_counts, self._counts))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width() or 200
        h = self.height() or 292

        cx = w / 2
        cy = 96
        r_out = 82
        band = 26
        rm = r_out - band / 2
        rect = QRectF(cx - rm, cy - rm, 2 * rm, 2 * rm)

        # Animated (interpolated) values drive the arc geometry + center total;
        # legend shows the crisp integer target counts.
        fast_i, medium_i, slow_i, dead_i = self._rendered_counts()
        fast, medium, slow, dead = self._counts
        total = fast + medium + slow + dead
        total_anim = fast_i + medium_i + slow_i + dead_i
        segs = [(fast_i, FAST), (medium_i, MEDIUM), (slow_i, SLOW), (dead_i, DEAD)]

        track_pen = QPen(QColor(SURFACE2))
        track_pen.setWidth(band)
        track_pen.setCapStyle(Qt.FlatCap)
        p.setPen(track_pen)
        p.setBrush(Qt.NoBrush)
        p.drawArc(rect, 0, 360 * 16)

        if total_anim > 0:
            gap = 2.0
            start = 90.0
            active = [(v, col) for v, col in segs if v > 0]
            multi = len(active) > 1
            for v, col in active:
                extent = -360.0 * (v / total_anim)
                draw_extent = extent
                if multi:
                    draw_extent = extent + gap if extent + gap < 0 else extent
                if abs(draw_extent) < 0.1:
                    draw_extent = -0.1
                if draw_extent <= -359.999:
                    draw_extent = -359.999
                seg_pen = QPen(QColor(col))
                seg_pen.setWidth(band)
                seg_pen.setCapStyle(Qt.FlatCap)
                p.setPen(seg_pen)
                p.drawArc(rect, int(round(start * 16)), int(round(draw_extent * 16)))
                start += extent

        # Center readout
        p.setPen(QColor(TEXT))
        p.setFont(QFont('Courier New', 30, QFont.Bold))
        p.drawText(QRectF(0, cy - 8 - 26, w, 40), Qt.AlignHCenter | Qt.AlignVCenter, str(total))
        p.setPen(QColor(MUTED))
        p.setFont(QFont('Segoe UI', 10))
        p.drawText(QRectF(0, cy + 20 - 10, w, 20), Qt.AlignHCenter | Qt.AlignVCenter, 'TESTED')

        # Legend (single column)
        entries = [('Fast', fast, FAST), ('Medium', medium, MEDIUM),
                   ('Slow', slow, SLOW), ('Dead', dead, DEAD)]
        ly0 = 192
        lh = 23
        for i, (lbl, val, col) in enumerate(entries):
            y = ly0 + i * lh
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(col)))
            p.drawEllipse(QRectF(20, y - 4, 9, 9))
            p.setPen(QColor(MUTED))
            p.setFont(QFont('Segoe UI', 11))
            p.drawText(QRectF(38, y - 10, 120, 20), Qt.AlignVCenter | Qt.AlignLeft, lbl)
            p.setPen(QColor(col))
            p.setFont(QFont('Courier New', 12, QFont.Bold))
            p.drawText(QRectF(w - 120, y - 10, 100, 20), Qt.AlignVCenter | Qt.AlignRight, str(val))
        p.end()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('ScanV2Ray')
        self.resize(940, 940)
        self.setMinimumSize(820, 640)

        # ---- state (ported from ConfigScannerApp.__init__) ----
        self.folder_path = None
        self.loaded_links = set()
        self.link_protocols = {}
        self.fast_links = []
        self.medium_links = []
        self.slow_links = []
        self.active = []
        self.scan_state = 'idle'
        self.pause_cond = threading.Condition()
        self.log_lock = threading.Lock()
        self.log_queue = []
        self._log_flush_scheduled = False
        self.log_filepath = None
        self._scan_phase = 'idle'
        self._skip_precheck = False
        self._scan_generation = 0
        self._last_progress = 0.0
        self._donut_pending = False
        self._entrance_done = False
        self._closing = False

        if getattr(sys, 'frozen', False):
            base_dir = sys._MEIPASS
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        xray_path = os.path.join(base_dir, 'Core', 'xray', 'xray.exe')
        singbox_path = os.path.join(base_dir, 'Core', 'sing_box', 'sing-box.exe')
        self.scanner = Scanner(xray_path, singbox_path)

        # Site-check configuration state (plain Python attrs)
        self.site_urls = {name: url for name, url in SITE_TARGETS_DEFAULT}
        self.site_vars = {name: True for name, _ in SITE_TARGETS_DEFAULT}
        self.site_custom = []
        self.site_strict = True
        self._site_dialog = None

        self.sig = ScanSignals()
        self._toast = None
        self._toast_anim = None

        self._build_ui()
        self._wire()
        self.update_link_count()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _card(self, title, subtitle=None):
        card = QFrame()
        card.setObjectName('card')
        card.setAttribute(Qt.WA_Hover, True)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(8)
        t = QLabel(title)
        t.setObjectName('cardTitle')
        lay.addWidget(t)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName('cardSub')
            s.setWordWrap(True)
            lay.addWidget(s)
        return card, lay

    def _build_ui(self):
        root = QWidget()
        root.setObjectName('root')
        self.setCentralWidget(root)
        rootlay = QVBoxLayout(root)
        rootlay.setContentsMargins(0, 0, 0, 0)
        rootlay.setSpacing(0)

        rootlay.addWidget(self._build_header())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        rootlay.addWidget(scroll, 1)

        body = QWidget()
        scroll.setWidget(body)
        bodylay = QVBoxLayout(body)
        bodylay.setContentsMargins(20, 16, 20, 20)
        bodylay.setSpacing(12)

        top = QGridLayout()
        top.setSpacing(12)
        top.setColumnStretch(0, 1)
        top.setColumnStretch(1, 1)
        top.addWidget(self._build_sources_card(), 0, 0)
        top.addWidget(self._build_setup_card(), 0, 1)
        bodylay.addLayout(top)

        bodylay.addWidget(self._build_progress_card())
        bodylay.addWidget(self._build_results_card())
        bodylay.addWidget(self._build_log_card())
        bodylay.addStretch(1)

    def _build_header(self):
        header = QFrame()
        header.setObjectName('header')
        header.setFixedHeight(84)
        lay = QHBoxLayout(header)
        lay.setContentsMargins(24, 16, 24, 16)

        left = QVBoxLayout()
        left.setSpacing(2)
        title = QLabel('ScanV2Ray')
        title.setObjectName('appTitle')
        sub = QLabel('Proxy reachability & speed scanner · Xray + sing-box')
        sub.setObjectName('appSubtitle')
        left.addWidget(title)
        left.addWidget(sub)
        lay.addLayout(left)
        lay.addStretch(1)

        chip = QFrame()
        chip.setObjectName('statusChip')
        chip.setFixedHeight(34)
        chiplay = QHBoxLayout(chip)
        chiplay.setContentsMargins(14, 6, 16, 6)
        chiplay.setSpacing(6)
        self.status_dot = StatusDot(MUTED, 12)
        self.status_chip = QLabel('Idle')
        self.status_chip.setObjectName('statusText')
        chiplay.addWidget(self.status_dot)
        chiplay.addWidget(self.status_chip)
        lay.addWidget(chip)
        return header

    def _segmented(self, values, default):
        frame = QFrame()
        frame.setObjectName('panel')
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        group = QButtonGroup(frame)
        group.setExclusive(True)
        for v in values:
            b = QPushButton(v)
            b.setObjectName('segment')
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            if v == default:
                b.setChecked(True)
            group.addButton(b)
            lay.addWidget(b)
        return frame, group

    def _build_sources_card(self):
        card, lay = self._card(
            'Sources',
            'Paste links, subscription URLs, base64 text, JSON, or local file paths.')

        self.source_input = QPlainTextEdit()
        self.source_input.setObjectName('sourceInput')
        self.source_input.setProperty('technical', 'true')
        self.source_input.setFixedHeight(100)
        lay.addWidget(self.source_input)

        self.sources_listbox = QListWidget()
        self.sources_listbox.setObjectName('sources')
        self.sources_listbox.setProperty('technical', 'true')
        self.sources_listbox.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.sources_listbox.setFixedHeight(120)
        lay.addWidget(self.sources_listbox)

        actions = QGridLayout()
        actions.setSpacing(6)
        self.add_links_btn = QPushButton('Add pasted')
        self.add_files_btn = QPushButton('Add files')
        self.remove_selected_btn = QPushButton('Remove selected')
        self.remove_selected_btn.setObjectName('danger')
        self.clear_sources_btn = QPushButton('Clear')
        actions.addWidget(self.add_links_btn, 0, 0)
        actions.addWidget(self.add_files_btn, 0, 1)
        actions.addWidget(self.remove_selected_btn, 1, 0)
        actions.addWidget(self.clear_sources_btn, 1, 1)
        lay.addLayout(actions)

        # Protocol filters + per-protocol counts
        panel = QFrame()
        panel.setObjectName('panel')
        pgrid = QGridLayout(panel)
        pgrid.setContentsMargins(8, 8, 8, 8)
        pgrid.setHorizontalSpacing(8)
        pgrid.setVerticalSpacing(2)
        self.protocol_checks = {}
        self.protocol_count_labels = {}
        ncols = 5
        for i, proto in enumerate(PROTOCOLS):
            r = (i // ncols) * 2
            c = i % ncols
            chk = QCheckBox(proto.upper())
            chk.setChecked(True)
            chk.setProperty('technical', 'true')
            cnt = QLabel('0')
            cnt.setObjectName('protoCount')
            cnt.setProperty('technical', 'true')
            pgrid.addWidget(chk, r, c)
            pgrid.addWidget(cnt, r + 1, c)
            self.protocol_checks[proto] = chk
            self.protocol_count_labels[proto] = cnt
        lay.addWidget(panel)

        self.link_count_label = QLabel('0 configs loaded')
        self.link_count_label.setObjectName('linkCount')
        self.link_count_label.setProperty('technical', 'true')
        lay.addWidget(self.link_count_label)
        return card

    def _build_setup_card(self):
        card, lay = self._card('Scan setup')

        lay.addWidget(self._muted_label('Scan mode'))
        self.mode_frame, self.mode_group = self._segmented(['Quick', 'Full'], 'Quick')
        lay.addWidget(self.mode_frame)

        self.ultra_switch = ToggleSwitch('Ultra scan')
        lay.addWidget(self.ultra_switch)

        self.select_button = QPushButton('Choose folder')
        lay.addWidget(self.select_button)
        self.folder_label = QLabel('No folder chosen')
        self.folder_label.setObjectName('folderLabel')
        self.folder_label.setWordWrap(True)
        self.folder_label.setProperty('technical', 'true')
        lay.addWidget(self.folder_label)

        self.start_button = QPushButton('Start scan')
        self.start_button.setObjectName('primary')
        self.start_button.setEnabled(False)
        lay.addWidget(self.start_button)

        lay.addWidget(self._muted_label('Speed preset'))
        self.preset_frame, self.preset_group = self._segmented(['Slow', 'Medium', 'Fast'], 'Medium')
        lay.addWidget(self.preset_frame)

        # Advanced numeric fields
        adv = QFrame()
        adv.setObjectName('panel')
        agrid = QGridLayout(adv)
        agrid.setContentsMargins(10, 12, 10, 12)
        agrid.setHorizontalSpacing(10)
        agrid.setVerticalSpacing(4)

        def num_field(default):
            e = QLineEdit(default)
            e.setProperty('technical', 'true')
            return e

        agrid.addWidget(self._muted_label('Precheck workers'), 0, 0)
        agrid.addWidget(self._muted_label('Test workers'), 0, 1)
        self.precheck_entry = num_field('200')
        self.test_entry = num_field('32')
        agrid.addWidget(self.precheck_entry, 1, 0)
        agrid.addWidget(self.test_entry, 1, 1)

        agrid.addWidget(self._muted_label('Speed-test slots'), 2, 0)
        agrid.addWidget(self._muted_label('Timeout (ms)'), 2, 1)
        self.speed_entry = num_field('24')
        self.timeout_entry = num_field('3500')
        agrid.addWidget(self.speed_entry, 3, 0)
        agrid.addWidget(self.timeout_entry, 3, 1)

        agrid.addWidget(self._muted_label('Remark (optional)'), 4, 0, 1, 2)
        self.remark_entry = QLineEdit('')
        self.remark_entry.setProperty('technical', 'true')
        agrid.addWidget(self.remark_entry, 5, 0, 1, 2)

        self.detect_country_check = ToggleSwitch('Detect exit country')
        self.detect_country_check.setChecked(True)
        self.retry_failed_check = ToggleSwitch('Retry failed once')
        self.retry_failed_check.setChecked(False)
        self.dedupe_check = ToggleSwitch('Remove duplicates')
        self.dedupe_check.setChecked(True)
        self.site_check_check = ToggleSwitch('Check site reachability')
        self.site_check_check.setChecked(False)
        agrid.addWidget(self.detect_country_check, 6, 0, 1, 2)
        agrid.addWidget(self.retry_failed_check, 7, 0, 1, 2)
        agrid.addWidget(self.dedupe_check, 8, 0, 1, 2)
        agrid.addWidget(self.site_check_check, 9, 0, 1, 2)

        self.site_config_btn = QPushButton('Configure sites…')
        agrid.addWidget(self.site_config_btn, 10, 0, 1, 2)

        lay.addWidget(adv)
        lay.addStretch(1)
        return card

    def _muted_label(self, text):
        lbl = QLabel(text)
        lbl.setObjectName('cardSub')
        return lbl

    def _build_progress_card(self):
        card, lay = self._card('Progress')
        self.status = QLabel('Ready')
        self.status.setObjectName('cardSub')
        lay.addWidget(self.status)

        self.progress_bar = CyberProgressBar()
        lay.addWidget(self.progress_bar)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.pause_button = QPushButton('Pause')
        self.pause_button.setObjectName('pause')
        self.pause_button.setEnabled(False)
        self.stop_save_button = QPushButton('Stop and save')
        self.stop_save_button.setEnabled(False)
        self.stop_button = QPushButton('Stop')
        self.stop_button.setObjectName('danger')
        self.stop_button.setEnabled(False)
        controls.addWidget(self.pause_button)
        controls.addWidget(self.stop_save_button)
        controls.addWidget(self.stop_button)
        lay.addLayout(controls)
        return card

    def _build_results_card(self):
        card, lay = self._card('Results', 'Live classification of tested configs')

        content = QHBoxLayout()
        content.setSpacing(20)
        self.donut = DonutWidget()
        content.addWidget(self.donut, 0, Qt.AlignTop)

        tiles = QGridLayout()
        tiles.setSpacing(6)
        specs = [
            ('fast_value', 'Fast', FAST),
            ('medium_value', 'Medium', MEDIUM),
            ('slow_value', 'Slow', SLOW),
            ('dead_value', 'Dead', DEAD),
        ]
        for idx, (attr, label, color) in enumerate(specs):
            r, c = idx // 2, idx % 2
            tile = QFrame()
            tile.setObjectName('tile')
            tlay = QVBoxLayout(tile)
            tlay.setContentsMargins(16, 12, 16, 12)
            tlay.setSpacing(2)
            top = QHBoxLayout()
            top.setSpacing(6)
            top.addWidget(StatusDot(color, 10))
            cap = QLabel(label)
            cap.setObjectName('tileCap')
            top.addWidget(cap)
            top.addStretch(1)
            tlay.addLayout(top)
            val = QLabel('0')
            val.setObjectName('tileValue')
            val.setProperty('technical', 'true')
            val.setStyleSheet(f'color: {color};')
            tlay.addWidget(val)
            setattr(self, attr, val)
            tiles.addWidget(tile, r, c)
        content.addLayout(tiles, 1)
        lay.addLayout(content)

        copyrow = QHBoxLayout()
        copyrow.setSpacing(6)
        self.copy_fast_btn = QPushButton('Copy Fast')
        self.copy_medium_btn = QPushButton('Copy Medium')
        self.copy_slow_btn = QPushButton('Copy Slow')
        self.copy_all_btn = QPushButton('Copy All')
        self.copy_all_btn.setObjectName('primary')
        for b in (self.copy_fast_btn, self.copy_medium_btn, self.copy_slow_btn, self.copy_all_btn):
            b.setEnabled(False)
            copyrow.addWidget(b)
        lay.addLayout(copyrow)
        return card

    def _build_log_card(self):
        card, lay = self._card('Activity log')
        self.log_box = QPlainTextEdit()
        self.log_box.setObjectName('log')
        self.log_box.setProperty('technical', 'true')
        self.log_box.setReadOnly(True)
        self.log_box.setFixedHeight(180)
        lay.addWidget(self.log_box)
        return card

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------
    def _wire(self):
        self.sig.status.connect(self._set_status)
        self.sig.progress.connect(self._set_progress)
        self.sig.counts.connect(self._set_counts)
        self.sig.phase.connect(self._set_phase)
        self.sig.log.connect(self._append_log)
        self.sig.dead.connect(self._on_dead)
        self.sig.result.connect(self._on_result)
        self.sig.toast.connect(self._show_toast)
        self.sig.finished.connect(self._on_finished)

        self.add_links_btn.clicked.connect(self.add_manual_sources)
        self.add_files_btn.clicked.connect(self.add_files)
        self.remove_selected_btn.clicked.connect(self.remove_selected_sources)
        self.clear_sources_btn.clicked.connect(self.clear_sources)
        for chk in self.protocol_checks.values():
            chk.stateChanged.connect(lambda *_: self.update_link_count())
        self.mode_group.buttonClicked.connect(lambda *_: self.update_link_count())
        self.preset_group.buttonClicked.connect(
            lambda btn: self._apply_preset(btn.text()))
        self.select_button.clicked.connect(self.select_folder)
        self.start_button.clicked.connect(self.start_scan)
        self.site_config_btn.clicked.connect(self.open_site_config)

        self.pause_button.clicked.connect(self.toggle_pause)
        self.stop_save_button.clicked.connect(self._stop_save_action)
        self.stop_button.clicked.connect(self.stop_scan_now)

        self.copy_fast_btn.clicked.connect(self.copy_fast)
        self.copy_medium_btn.clicked.connect(self.copy_medium)
        self.copy_slow_btn.clicked.connect(self.copy_slow)
        self.copy_all_btn.clicked.connect(self.copy_all)

    # ------------------------------------------------------------------
    # Signal slots (run on the GUI thread)
    # ------------------------------------------------------------------
    def _set_status(self, text):
        self.status.setText(text)
        self._update_chip(text)

    def _update_chip(self, text):
        low = (text or '').lower()
        if 'paused' in low:
            dot, label = MEDIUM, 'Paused'
        elif 'complete' in low or 'completed' in low or 'done' in low:
            dot, label = FAST, 'Done'
        elif 'fail' in low or 'abort' in low:
            dot, label = DEAD, 'Stopped'
        elif 'stopping' in low or 'saving' in low:
            dot, label = SLOW, 'Stopping…'
        elif any(k in low for k in ('scan', 'test', 'precheck', 'process',
                                    'pipeline', 'starting', 'dedupe')):
            dot, label = ACCENT, 'Scanning…'
        else:
            dot, label = MUTED, 'Idle'
        try:
            self.status_dot.set_color(dot)
            self.status_chip.setText(label)
            if label in ('Scanning…', 'Stopping…'):
                self.status_dot.start_pulse()
            else:
                self.status_dot.stop_pulse()
        except Exception:
            pass

    def _set_progress(self, value):
        self._last_progress = value
        self.progress_bar.set_value(value)

    def _set_counts(self, fast, medium, slow, dead):
        self.fast_value.setText(str(fast))
        self.medium_value.setText(str(medium))
        self.slow_value.setText(str(slow))
        self.dead_value.setText(str(dead))
        # Donut coalesce (~150ms) mirrors the original throttle; immediate when
        # animations are disabled (headless) so no timer spins.
        self._donut_counts = (fast, medium, slow, dead)
        if _has_event_loop():
            if not self._donut_pending:
                self._donut_pending = True
                QTimer.singleShot(150, self._render_donut)
        else:
            self._render_donut()

    def _render_donut(self):
        self._donut_pending = False
        f, m, s, d = getattr(self, '_donut_counts', (0, 0, 0, 0))
        self.donut.set_counts(f, m, s, d)

    def _set_phase(self, phase):
        self._scan_phase = phase
        if phase == 'precheck':
            self.stop_save_button.setText('Stop → Phase 2')
        else:
            self.stop_save_button.setText('Stop and save')

    def _append_log(self, text):
        with self.log_lock:
            self.log_queue.append(text)
        if _has_event_loop():
            if not self._log_flush_scheduled:
                self._log_flush_scheduled = True
                QTimer.singleShot(180, self._flush_log)
        else:
            self._flush_log()

    def _flush_log(self):
        self._log_flush_scheduled = False
        with self.log_lock:
            lines = self.log_queue
            self.log_queue = []
        if not lines:
            return
        self.log_box.appendPlainText('\n'.join(lines))
        # Cap the box at ~500 blocks.
        try:
            doc = self.log_box.document()
            excess = doc.blockCount() - 500
            if excess > 0:
                cursor = self.log_box.textCursor()
                cursor.movePosition(cursor.MoveOperation.Start)
                for _ in range(excess):
                    cursor.select(cursor.SelectionType.BlockUnderCursor)
                    cursor.removeSelectedText()
                    cursor.deleteChar()
        except Exception:
            pass
        self.log_box.verticalScrollBar().setValue(
            self.log_box.verticalScrollBar().maximum())
        if self.log_filepath:
            try:
                with open(self.log_filepath, 'a', encoding='utf-8') as fp:
                    fp.write('\n'.join(lines) + '\n')
            except Exception:
                pass

    def _on_dead(self, _payload):
        pass

    def _on_result(self, _payload):
        pass

    def _on_finished(self, _completed, gen=-1):
        # Drop a late finish from a scan that was stopped-then-restarted.
        if gen != -1 and gen != self._scan_generation:
            return
        self.update_link_count()
        has_links = bool(self.fast_links or self.medium_links or self.slow_links)
        self._set_copy_enabled(has_links)
        self._set_control_enabled(False, False, False)
        self.scan_state = 'idle'
        self._skip_precheck = False

    # ------------------------------------------------------------------
    # Worker-facing emit wrappers (safe to call from the worker thread)
    # ------------------------------------------------------------------
    def _emit_stale(self, gen):
        """True if this emit belongs to a superseded scan generation."""
        return gen is not None and gen != self._scan_generation

    def log(self, text, gen=None):
        if self._closing or self._emit_stale(gen):
            return
        try:
            self.sig.log.emit(text)
        except RuntimeError:
            pass

    def set_status(self, text, gen=None):
        if self._closing or self._emit_stale(gen):
            return
        try:
            self.sig.status.emit(text)
        except RuntimeError:
            pass

    def set_progress(self, value, gen=None):
        if self._closing or self._emit_stale(gen):
            return
        try:
            self.sig.progress.emit(float(value))
        except RuntimeError:
            pass

    def update_live_stats(self, fast, medium, slow, dead, gen=None):
        if self._closing or self._emit_stale(gen):
            return
        try:
            self.sig.counts.emit(fast, medium, slow, dead)
        except RuntimeError:
            pass

    def set_phase(self, phase, gen=None):
        if self._closing or self._emit_stale(gen):
            return
        try:
            self.sig.phase.emit(phase)
        except RuntimeError:
            pass

    def _emit_toast(self, message, kind):
        if self._closing:
            return
        try:
            self.sig.toast.emit(message, kind)
        except RuntimeError:
            pass

    def _emit_finished(self, completed, gen):
        if self._closing:
            return
        try:
            self.sig.finished.emit(completed, gen)
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    # Button-state helpers (GUI thread only)
    # ------------------------------------------------------------------
    def _set_control_enabled(self, pause, stop_save, stop):
        self.pause_button.setEnabled(pause)
        self.stop_save_button.setEnabled(stop_save)
        self.stop_button.setEnabled(stop)

    def _set_copy_enabled(self, enabled):
        for b in (self.copy_fast_btn, self.copy_medium_btn,
                  self.copy_slow_btn, self.copy_all_btn):
            b.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Sources management (ported verbatim from ui.py)
    # ------------------------------------------------------------------
    def _selected_methods(self):
        return ['xray'] if self._scan_mode() == 'Full' else ['fast']

    def _scan_mode(self):
        btn = self.mode_group.checkedButton()
        return btn.text() if btn else 'Quick'

    def _add_links(self, links):
        added_links = 0
        for link in links:
            try:
                parsed = parse_link(link)
                proto = parsed.get('proto') if parsed else None
            except Exception:
                proto = None
            if link not in self.loaded_links:
                self.loaded_links.add(link)
                added_links += 1
                if proto:
                    self.link_protocols[link] = proto
        return added_links

    def add_files(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, 'Add config files', '',
            'Text files (*.txt);;All files (*.*)')
        if not file_paths:
            return
        added_links = 0
        for file_path in file_paths:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                added_links += self._add_links(extract_links(content) or resolve_source(content))
            except Exception as e:
                self.log(f'Error reading {os.path.basename(file_path)}: {e}')
        self.log(f'Added {len(file_paths)} files. New configs: {added_links}.')
        self.update_link_count()

    def add_manual_sources(self):
        raw = self.source_input.toPlainText().strip()
        if not raw:
            self.log('Paste at least one source before adding.')
            return
        added_links = 0
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            if os.path.isfile(line):
                try:
                    with open(line, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    links = extract_links(content) or resolve_source(content)
                except Exception:
                    links = []
            else:
                links = resolve_source(line)
            added_links += self._add_links(links)
        self.log(f'Added pasted sources. New configs: {added_links}.')
        self.update_link_count()

    def clear_sources(self):
        self.loaded_links.clear()
        self.link_protocols.clear()
        self.log('Sources cleared.')
        self.update_link_count()

    def remove_selected_sources(self):
        try:
            selection = sorted(i.row() for i in self.sources_listbox.selectedIndexes())
            if not selection:
                self.log('No source selected to remove.')
                return
            items = sorted(self.loaded_links)
            to_remove = [items[i] for i in selection if 0 <= i < len(items)]
            for item in to_remove:
                if item in self.loaded_links:
                    self.loaded_links.remove(item)
                    self.link_protocols.pop(item, None)
            self.log(f'Removed {len(to_remove)} selected source(s).')
            self.update_link_count()
        except Exception as e:
            self.log(f'Error removing selected sources: {e}')

    def refresh_sources_listbox(self):
        try:
            self.sources_listbox.clear()
            for item in sorted(self.loaded_links):
                proto = self.link_protocols.get(item)
                display = f'[{proto}] {item}' if proto else item
                if len(display) > 180:
                    display = display[:170] + '...'
                self.sources_listbox.addItem(display)
        except Exception:
            pass

    def _compute_protocol_counts(self):
        counts = {p: 0 for p in PROTOCOLS}
        for link in list(self.loaded_links):
            proto = self.link_protocols.get(link)
            if not proto:
                try:
                    parsed = parse_link(link)
                    proto = parsed.get('proto') if parsed else None
                except Exception:
                    proto = None
                if proto:
                    self.link_protocols[link] = proto
            if proto in counts:
                counts[proto] += 1
        return counts

    def _filtered_loaded_links(self):
        selected = {p for p, chk in self.protocol_checks.items() if chk.isChecked()}
        if not selected:
            return set()
        result = set()
        for link in self.loaded_links:
            proto = self.link_protocols.get(link)
            if not proto:
                try:
                    parsed = parse_link(link)
                    proto = parsed.get('proto') if parsed else None
                except Exception:
                    proto = None
                if proto:
                    self.link_protocols[link] = proto
            if proto in selected:
                result.add(link)
        return result

    def update_link_count(self):
        self.link_count_label.setText(f'{len(self.loaded_links)} configs loaded')
        self.refresh_sources_listbox()
        counts = self._compute_protocol_counts()
        for proto, lbl in self.protocol_count_labels.items():
            lbl.setText(str(counts.get(proto, 0)))
        ready = bool(self._filtered_loaded_links() and self.folder_path and self._selected_methods())
        self.start_button.setEnabled(ready)

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Choose output folder')
        if folder:
            self.folder_path = folder
            display_path = folder
            if len(display_path) > 54:
                display_path = '...' + display_path[-51:]
            self.folder_label.setText(display_path)
            self.set_status(f'Output folder selected: {self.folder_path}')
            self.update_link_count()

    def _apply_preset(self, value):
        preset = PRESETS.get(value)
        if not preset:
            return
        for entry, key in ((self.precheck_entry, 'precheck'), (self.test_entry, 'test'),
                           (self.speed_entry, 'speed'), (self.timeout_entry, 'timeout')):
            entry.setText(preset[key])

    # ------------------------------------------------------------------
    # Site-check configuration
    # ------------------------------------------------------------------
    def open_site_config(self):
        if self._site_dialog is not None and self._site_dialog.isVisible():
            self._site_dialog.raise_()
            self._site_dialog.activateWindow()
            return
        dlg = QDialog(self)
        dlg.setWindowTitle('Site check')
        dlg.setModal(True)
        dlg.resize(420, 480)
        self._site_dialog = dlg
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(8)

        header = QLabel('Sites to verify')
        header.setObjectName('cardTitle')
        lay.addWidget(header)
        info = QLabel('Each selected site must be reachable through the proxy.')
        info.setObjectName('cardSub')
        info.setWordWrap(True)
        lay.addWidget(info)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._site_list_container = QWidget()
        self._site_list_layout = QVBoxLayout(self._site_list_container)
        self._site_list_layout.setContentsMargins(6, 6, 6, 6)
        self._site_list_layout.setSpacing(4)
        scroll.setWidget(self._site_list_container)
        lay.addWidget(scroll, 1)
        self._populate_site_list()

        addrow = QHBoxLayout()
        self._site_add_entry = QLineEdit()
        self._site_add_entry.setPlaceholderText('https://example.com')
        self._site_add_entry.setProperty('technical', 'true')
        add_btn = QPushButton('Add')
        add_btn.clicked.connect(self._add_custom_site)
        addrow.addWidget(self._site_add_entry, 1)
        addrow.addWidget(add_btn)
        lay.addLayout(addrow)

        strict = QCheckBox('Strict (must reach all selected sites)')
        strict.setChecked(self.site_strict)
        strict.stateChanged.connect(lambda s: setattr(self, 'site_strict', bool(s)))
        lay.addWidget(strict)

        done = QPushButton('Done')
        done.setObjectName('primary')
        done.clicked.connect(dlg.accept)
        lay.addWidget(done)

        # Entrance fade (gated)
        if _animations_enabled():
            dlg.setWindowOpacity(0.0)
            self._site_anim = QPropertyAnimation(dlg, b'windowOpacity', dlg)
            self._site_anim.setDuration(220)
            self._site_anim.setStartValue(0.0)
            self._site_anim.setEndValue(1.0)
            self._site_anim.setEasingCurve(QEasingCurve.OutCubic)
            dlg.show()
            self._site_anim.start()
        dlg.exec()

    def _populate_site_list(self):
        while self._site_list_layout.count():
            item = self._site_list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for name in self.site_urls:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            chk = QCheckBox(name)
            chk.setChecked(bool(self.site_vars.get(name, True)))
            chk.stateChanged.connect(
                lambda s, n=name: self.site_vars.__setitem__(n, bool(s)))
            url = QLabel(self.site_urls[name])
            url.setObjectName('cardSub')
            rl.addWidget(chk)
            rl.addWidget(url, 1)
            self._site_list_layout.addWidget(row)
        self._site_list_layout.addStretch(1)

    def _add_custom_site(self):
        url = self._site_add_entry.text().strip()
        if not url:
            return
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        host = url.split('://', 1)[-1].split('/', 1)[0]
        name = host or url
        base = name
        i = 2
        while name in self.site_urls:
            name = f'{base} ({i})'
            i += 1
        self.site_urls[name] = url
        self.site_vars[name] = True
        self.site_custom.append(name)
        self._site_add_entry.clear()
        self._populate_site_list()

    def _build_site_targets(self):
        return [(name, self.site_urls[name]) for name in self.site_urls
                if self.site_vars.get(name)]

    # ------------------------------------------------------------------
    # Pause / stop control (thread primitives — ported verbatim)
    # ------------------------------------------------------------------
    def toggle_pause(self):
        if self.scan_state == 'running':
            self.scan_state = 'paused'
            self.pause_button.setText('Resume')
            self.pause_button.setProperty('mode', 'paused')
            _restyle(self.pause_button)
            self.log('Scan paused.')
            self.set_status('Scan paused')
        elif self.scan_state == 'paused':
            self.scan_state = 'running'
            self.pause_button.setText('Pause')
            self.pause_button.setProperty('mode', 'run')
            _restyle(self.pause_button)
            self.log('Scan resumed.')
            self.set_status('Scan resumed')
            with self.pause_cond:
                self.pause_cond.notify_all()

    def stop_scan_now(self):
        self.scan_state = 'stopping'
        self.log('Stopping scan and discarding partial results.')
        self.set_status('Stopping...')
        self._set_control_enabled(False, False, False)
        with self.pause_cond:
            self.pause_cond.notify_all()

    def stop_and_save(self):
        self.scan_state = 'stopping_save'
        self.log('Stopping scan and saving completed results.')
        self.set_status('Saving progress...')
        self._set_control_enabled(False, False, False)
        with self.pause_cond:
            self.pause_cond.notify_all()

    def _stop_save_action(self):
        if self._scan_phase == 'precheck':
            self._skip_precheck = True
            self.log('Skipping remaining prechecks — going straight to phase 2.')
            self.set_status('Skipping precheck → phase 2')
        else:
            self.stop_and_save()

    def _dead_result(self, link, reason, method='xray_validation', original_remark=''):
        return {
            'method': method,
            'proto': '',
            'link': link,
            'remark': original_remark or 'NoRemark',
            'latency': 0,
            'speed': 0.0,
            'success_ratio': 0.0,
            'average_latency': '',
            'score': 0.0,
            'classification': 'dead',
            'reason': reason,
            'exit_ip': '',
            'exit_country': '',
            'sites_ok': []
        }

    # ------------------------------------------------------------------
    # Scan orchestration
    # ------------------------------------------------------------------
    def start_scan(self):
        filtered_links = self._filtered_loaded_links()
        if not filtered_links:
            self.log('No configs loaded for scanning or no protocol selected.')
            return
        if not self.folder_path:
            self.log('Choose an output folder before starting the scan.')
            return
        methods = self._selected_methods()
        if not methods:
            self.log('Select a scan mode before starting.')
            return

        self.log_box.clear()
        with self.log_lock:
            self.log_queue = []
        self.log_filepath = None
        if self.folder_path:
            log_dir = os.path.join(self.folder_path, 'Scan_Results')
            os.makedirs(log_dir, exist_ok=True)
            log_filepath = os.path.join(log_dir, 'scan_log.txt')
            with open(log_filepath, 'w', encoding='utf-8') as f:
                f.write(f'=== ScanV2Ray LOG STARTED AT {time.strftime("%Y-%m-%d %H:%M:%S")} ===\n')
            self.log_filepath = log_filepath

        self.log('Starting scan...')
        self.set_progress(0)
        self.start_button.setEnabled(False)
        self._set_copy_enabled(False)
        self.fast_links = []
        self.medium_links = []
        self.slow_links = []
        self.active = []
        self.update_live_stats(0, 0, 0, 0)
        self.scan_state = 'running'
        self.pause_button.setText('Pause')
        self.pause_button.setProperty('mode', 'run')
        _restyle(self.pause_button)
        self._set_control_enabled(True, True, True)
        self._scan_generation += 1
        gen = self._scan_generation

        # Read GUI inputs on the MAIN thread.
        try:
            precheck_workers = int(self.precheck_entry.text().strip())
            if precheck_workers <= 0:
                raise ValueError
        except Exception:
            precheck_workers = 200
            self.log('Invalid precheck workers. Using 200.')

        try:
            test_workers = int(self.test_entry.text().strip())
            if test_workers <= 0:
                raise ValueError
        except Exception:
            test_workers = 32
            self.log('Invalid test workers. Using 32.')

        try:
            speed_limit = int(self.speed_entry.text().strip())
            if speed_limit <= 0:
                raise ValueError
        except Exception:
            speed_limit = 24
            self.log('Invalid speed-test slots. Using 24.')

        try:
            timeout_ms = float(self.timeout_entry.text().strip())
            if timeout_ms <= 0:
                raise ValueError
            timeout = timeout_ms / 1000.0
        except Exception:
            timeout = 3.5
            self.log('Invalid timeout. Using 3500ms.')

        try:
            remark_override = self.remark_entry.text().strip()
        except Exception as e:
            remark_override = ''
            self.log(f'Error reading Remark field: {e}')

        try:
            ultra_scan = bool(self.ultra_switch.isChecked())
        except Exception as e:
            ultra_scan = False
            self.log(f'Error reading Ultra Scan flag: {e}')

        try:
            detect_country = bool(self.detect_country_check.isChecked())
        except Exception as e:
            detect_country = True
            self.log(f'Error reading Detect exit country flag: {e}')
        try:
            retry_failed = bool(self.retry_failed_check.isChecked())
        except Exception as e:
            retry_failed = False
            self.log(f'Error reading Retry failed once flag: {e}')
        try:
            site_check = bool(self.site_check_check.isChecked())
        except Exception as e:
            site_check = False
            self.log(f'Error reading Check site reachability flag: {e}')
        try:
            dedupe = bool(self.dedupe_check.isChecked())
        except Exception as e:
            dedupe = True
            self.log(f'Error reading Remove duplicates flag: {e}')

        if site_check:
            try:
                site_targets = self._build_site_targets()
            except Exception as e:
                site_targets = []
                self.log(f'Error reading site targets: {e}')
            try:
                site_strict = bool(self.site_strict)
            except Exception:
                site_strict = True
            if not site_targets:
                self.log('Site check enabled but no sites selected; disabling site check.')
                site_check = False
                site_strict = False
        else:
            site_targets = []
            site_strict = False

        threading.Thread(
            target=self.run_scan,
            args=(methods, filtered_links),
            kwargs={
                'precheck_workers': precheck_workers,
                'test_workers': test_workers,
                'speed_limit': speed_limit,
                'timeout': timeout,
                'remark_override': remark_override,
                'ultra': ultra_scan,
                'detect_country': detect_country,
                'retry_failed': retry_failed,
                'site_check': site_check,
                'dedupe': dedupe,
                'site_targets': site_targets,
                'site_strict': site_strict,
                'generation': gen,
            },
            daemon=True
        ).start()

    def run_scan(self, methods, filtered_links, *, precheck_workers, test_workers, speed_limit,
                 timeout, remark_override, ultra, detect_country, retry_failed, site_check,
                 dedupe, site_targets, site_strict, generation=None):
        gen = generation
        completed = False
        try:
            self.scanner.reset_abort()
            self._skip_precheck = False
            self.set_phase('precheck', gen)

            self.scanner.detect_country = detect_country
            self.scanner.site_check = site_check
            self.scanner.site_strict = site_strict
            self.scanner.site_targets = list(site_targets) if site_check else []

            if methods and not os.path.exists(self.scanner.xray_path):
                self.log('xray.exe not found in Core/xray folder.', gen)
                self.set_status('Scan aborted: xray.exe missing', gen)
                self._emit_toast('xray.exe not found in Core/xray folder.', 'danger')
                return
            unique_links = sorted(filtered_links)

            if dedupe:
                before = len(unique_links)
                unique_links = engine.dedupe_links(unique_links, parse_link)
                removed = before - len(unique_links)
                self.log(f'Dedupe removed {removed} duplicate config(s).')

            total_links = len(unique_links)
            self.log(f'Processing {total_links} unique configs.')
            selected_method = 'xray' if 'xray' in methods else 'fast'

            if ultra:
                test_workers = max(test_workers, 100)
                speed_limit = max(speed_limit, 24)

            self.scanner.set_speed_test_limit(speed_limit)
            self.log(
                f'Pipeline: precheck workers={precheck_workers}, test workers={test_workers}, '
                f'speed-test slots={speed_limit}, mode={selected_method}, '
                f'ultra={"on" if ultra else "off"}.'
            )

            batch_sizes = engine.chunk_plan(total_links)
            num_chunks = max(1, len(batch_sizes))
            batches = []
            _off = 0
            for _sz in batch_sizes:
                batches.append(unique_links[_off:_off + _sz])
                _off += _sz
            if num_chunks > 1:
                precheck_workers = min(precheck_workers, 250)
                self.scanner.precheck_timeout = 0.85
                self.log(
                    f'Large input: scanning in {num_chunks} sequential batches '
                    f'(≈{batch_sizes[0]} each); precheck '
                    f'(workers={precheck_workers}, timeout=0.85s).'
                )
            else:
                self.scanner.precheck_timeout = 0.7

            results = []
            reachable = 0
            test_done = 0
            fast_count = 0
            medium_count = 0
            slow_count = 0
            dead_count = 0
            last_pct = 0.0
            chunk_index = 0

            def show_progress(pct):
                nonlocal last_pct
                overall = (chunk_index + min(pct, 1.0)) / num_chunks
                if overall > last_pct:
                    last_pct = overall
                self.set_progress(min(last_pct, 1.0), gen)

            def _batch_label():
                return f'Batch {chunk_index + 1}/{num_chunks} · ' if num_chunks > 1 else ''

            def report_dead(link, parsed, reason, stage):
                nonlocal dead_count
                dead_count += 1
                method_label = 'tcp_precheck' if stage == 'precheck' else selected_method
                orig_remark = parsed.get('remark', 'NoRemark') if parsed else 'NoRemark'
                results.append(self._dead_result(link, reason, method_label, orig_remark))
                self.update_live_stats(fast_count, medium_count, slow_count, dead_count, gen)

            def report_precheck(pd, total, reach):
                nonlocal reachable
                reachable = reach
                pct = (pd / total) * 0.15 if total else 0
                show_progress(pct)
                self.set_status(f'{_batch_label()}Prechecked {pd}/{total} ({reach} reachable)', gen)

            def report_test(item, result, td, reach):
                nonlocal test_done, reachable, fast_count, medium_count, slow_count, dead_count
                test_done = td
                reachable = reach
                if result:
                    results.append(result)
                    classification = result.get('classification', 'dead')
                    if classification == 'fast':
                        fast_count += 1
                    elif classification == 'medium':
                        medium_count += 1
                    elif classification == 'slow':
                        slow_count += 1
                    else:
                        dead_count += 1
                pct = 0.15 + (td / max(reach, 1)) * 0.85
                show_progress(pct)
                self.set_status(f'{_batch_label()}Tested {td}/{max(reach, 1)} reachable configs', gen)
                self.update_live_stats(fast_count, medium_count, slow_count, dead_count, gen)

            def should_stop():
                return self.scan_state in ('stopping', 'stopping_save')

            def wait_if_paused():
                while self.scan_state == 'paused':
                    with self.pause_cond:
                        if self.scan_state == 'paused':
                            self.pause_cond.wait(timeout=0.2)

            def should_stop_precheck():
                return self._skip_precheck

            def on_prechecks_done():
                self.set_phase('test', gen)

            cumulative_reachable = 0
            cumulative_test_done = 0
            for chunk_index in range(num_chunks):
                if self.scan_state in ('stopping', 'stopping_save'):
                    break
                batch = batches[chunk_index]
                if not batch:
                    continue
                self._skip_precheck = False
                self.set_phase('precheck', gen)
                if num_chunks > 1:
                    self.log(f'--- Batch {chunk_index + 1}/{num_chunks}: {len(batch)} configs ---')
                stats = engine.run_pipeline(
                    self.scanner, batch,
                    method=selected_method, timeout=timeout,
                    precheck_workers=precheck_workers, test_workers=test_workers,
                    should_stop=should_stop, wait_if_paused=wait_if_paused,
                    report_precheck=report_precheck, report_dead=report_dead,
                    report_test=report_test, retry_failed=retry_failed,
                    should_stop_precheck=should_stop_precheck,
                    on_prechecks_done=on_prechecks_done,
                )
                cumulative_reachable += stats.get('reachable', 0)
                cumulative_test_done += stats.get('test_done', 0)

            if self.scan_state not in ('stopping', 'stopping_save'):
                self.set_progress(1.0, gen)
                self.log(f'Precheck complete: {cumulative_reachable}/{total_links} reachable endpoints.')
                self.log(f'Testing complete: {cumulative_test_done}/{max(cumulative_reachable, 1)} reachable configs tested.')

            if self.scan_state != 'stopping':
                naming.apply_naming(results, remark_override, detect_country)
                self.fast_links = [r['link'] for r in results if r.get('classification') == 'fast']
                self.medium_links = [r['link'] for r in results if r.get('classification') == 'medium']
                self.slow_links = [r['link'] for r in results if r.get('classification') == 'slow']
                self.active = self.fast_links + self.medium_links + self.slow_links

                self.save_results(results)
                self.log('')
                self.log('Scan complete.')
                self.log(
                    f'Working configs: {len(self.active)} '
                    f'(fast: {len(self.fast_links)}, medium: {len(self.medium_links)}, '
                    f'slow: {len(self.slow_links)}).'
                )
                self.set_status('Scan completed successfully', gen)
                self._emit_toast('Scan completed successfully', 'success')
                completed = True
            else:
                self.set_status('Scan aborted', gen)
                self._emit_toast('Scan aborted', 'warning')
        except Exception as e:
            self.log(f'Scan error: {e}', gen)
            self.set_status('Scan failed', gen)
            self._emit_toast(f'Scan failed: {e}', 'danger')
        finally:
            # Only reset shared state if we are still the current scan generation,
            # so a late-finishing, stopped-then-restarted scan can't clobber a new run.
            if gen is None or gen == self._scan_generation:
                self.scan_state = 'idle'
                self._skip_precheck = False
            self.set_phase('idle', gen)
            self._emit_finished(completed, gen)

    # ------------------------------------------------------------------
    # Result persistence (pure Python — ported verbatim)
    # ------------------------------------------------------------------
    @staticmethod
    def _csv_safe(value):
        text = str(value)
        if text and text[0] in ('=', '+', '-', '@'):
            return "'" + text
        return text

    def save_results(self, results):
        if not self.folder_path:
            self.log('Choose an output folder to save result files.')
            return

        output_dir = os.path.join(self.folder_path, 'Scan_Results')
        os.makedirs(output_dir, exist_ok=True)
        self.log(f'Saving results inside: {output_dir}')

        if results:
            json_path = os.path.join(output_dir, 'scan_results.json')
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            self.log('Saved scan_results.json')

            csv_path = os.path.join(output_dir, 'scan_results.csv')
            with open(csv_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'method', 'proto', 'link', 'remark', 'latency_ms', 'speed_kbps',
                    'success_ratio', 'average_latency_ms', 'score', 'classification', 'reason',
                    'exit_ip', 'exit_country', 'sites_ok'
                ])
                for item in results:
                    writer.writerow([
                        self._csv_safe(item['method']),
                        self._csv_safe(item['proto']),
                        self._csv_safe(item['link']),
                        self._csv_safe(item['remark']),
                        self._csv_safe(item['latency']),
                        self._csv_safe(f"{item['speed']:.2f}"),
                        self._csv_safe(item['success_ratio']),
                        self._csv_safe(item.get('average_latency', '')),
                        self._csv_safe(item['score']),
                        self._csv_safe(item['classification']),
                        self._csv_safe(item.get('reason', '')),
                        self._csv_safe(item.get('exit_ip', '')),
                        self._csv_safe(item.get('exit_country', '')),
                        self._csv_safe(';'.join(item.get('sites_ok', []) or [])),
                    ])
            self.log('Saved scan_results.csv')

        groups = {'fast': [], 'medium': [], 'slow': [], 'dead': []}
        for item in results:
            groups.setdefault(item['classification'], []).append(item)

        for classification, items in groups.items():
            file_base = f'{classification}_verified.txt' if classification != 'dead' else 'dead.txt'
            file_path = os.path.join(output_dir, file_base)
            with open(file_path, 'w', encoding='utf-8') as f:
                for item in items:
                    remark = item.get('remark', '')
                    if remark and remark != 'NoRemark':
                        line = f"{item['link']} | {remark}"
                    else:
                        line = f"{item['link']}"
                    if classification == 'dead':
                        reason = item.get('reason', '')
                        if reason:
                            line = f"{line} | {reason}"
                    f.write(line + '\n')
            self.log(f'Saved {file_base}')

    # ------------------------------------------------------------------
    # Clipboard exports
    # ------------------------------------------------------------------
    def _copy_links(self, links, label):
        if links:
            QApplication.clipboard().setText('\n'.join(links))
            self.log(f'{label} configs copied.')
        else:
            self.log(f'No {label.lower()} configs are available to copy.')

    def copy_fast(self):
        self._copy_links(self.fast_links, 'Fast')

    def copy_medium(self):
        self._copy_links(self.medium_links, 'Medium')

    def copy_slow(self):
        self._copy_links(self.slow_links, 'Slow')

    def copy_all(self):
        seen = set()
        out = []
        for link in self.fast_links + self.medium_links + self.slow_links:
            if link not in seen:
                seen.add(link)
                out.append(link)
        self._copy_links(out, 'All')

    # ------------------------------------------------------------------
    # Toast + entrance motion
    # ------------------------------------------------------------------
    def _show_toast(self, message, kind='success'):
        toast = QFrame(self)
        toast.setObjectName('toast')
        toast.setProperty('kind', kind)
        lay = QHBoxLayout(toast)
        lay.setContentsMargins(16, 12, 18, 12)
        lay.setSpacing(10)
        dotcolor = {'success': FAST, 'warning': MEDIUM, 'danger': DEAD}.get(kind, ACCENT)
        lay.addWidget(StatusDot(dotcolor, 12))
        text = QLabel(message)
        text.setObjectName('toastText')
        lay.addWidget(text)
        shadow = QGraphicsDropShadowEffect(toast)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 150))
        toast.setGraphicsEffect(shadow)
        toast.adjustSize()
        self._toast = toast
        self._position_toast()
        toast.show()
        toast.raise_()
        # Only the slide-in is gated on motion; the toast itself always appears
        # and always auto-dismisses.
        if _animations_enabled():
            target = toast.pos()
            self._toast_anim = QPropertyAnimation(toast, b'pos', toast)
            self._toast_anim.setDuration(240)
            self._toast_anim.setStartValue(QPoint(target.x(), target.y() + 12))
            self._toast_anim.setEndValue(target)
            self._toast_anim.setEasingCurve(QEasingCurve.OutCubic)
            self._toast_anim.start()
        QTimer.singleShot(6000, lambda t=toast: (
            t.deleteLater(),
            setattr(self, '_toast', None) if self._toast is t else None))

    def _position_toast(self):
        if self._toast is None:
            return
        try:
            tw = self._toast.width()
            th = self._toast.height()
            x = int((self.width() - tw) / 2)
            y = int(self.height() - th - 28)
            self._toast.move(x, y)
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_toast()

    def closeEvent(self, event):
        # Tear down cleanly mid-scan: stop worker emits and ask it to abort so a
        # destroyed-QObject emit can never crash the daemon worker thread.
        self._closing = True
        self.scan_state = 'stopping'
        try:
            self.scanner.request_abort()
        except Exception:
            pass
        try:
            with self.pause_cond:
                self.pause_cond.notify_all()
        except Exception:
            pass
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if self._entrance_done:
            return
        self._entrance_done = True
        if _animations_enabled():
            self.setWindowOpacity(0.0)
            self._entrance_anim = QPropertyAnimation(self, b'windowOpacity', self)
            self._entrance_anim.setDuration(520)
            self._entrance_anim.setStartValue(0.0)
            self._entrance_anim.setEndValue(1.0)
            self._entrance_anim.setEasingCurve(QEasingCurve.OutCubic)
            self._entrance_anim.start()
