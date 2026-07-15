import csv
import json
import os
import threading
import time
from tkinter import filedialog, StringVar, BooleanVar, Listbox, END

import customtkinter as ctk
import sys

from .parser import extract_links, resolve_source, parse_link
from .scanner import Scanner
from . import engine
from . import naming


# ---------------------------------------------------------------------------
# Design system — modern analytics dashboard (calm, restrained, no neon)
# ---------------------------------------------------------------------------
BG = '#0F1216'
SURFACE = '#171B22'
SURFACE2 = '#1E232C'
ELEV = '#232935'
LINE = '#2A313D'

ACCENT = '#6D8BFF'         # one soft-indigo accent, used sparingly
ACCENT_HOVER = '#8098FF'
ACCENT_DIM = '#39406b'

TEXT = '#E6E9EF'
MUTED = '#8A93A2'
FAINT = '#5B6472'

# semantic result colors (muted; only used in charts / tiles)
FAST = '#46C48A'
MEDIUM = '#E6B34E'
SLOW = '#E08A4C'
DEAD = '#E06A6A'

WHITE = '#FFFFFF'
DEAD_DIM = '#5A3A42'       # soft, muted DEAD border for danger buttons

# radii
CARD_R = 16
INNER_R = 10
BTN_R = 10

# --- back-compat aliases so untouched widget code keeps working ------------
PANEL = SURFACE
PANEL2 = SURFACE2
RAISE = ELEV
CYAN = ACCENT
CYAN_DIM = ACCENT_DIM
CYAN_HOVER = ACCENT_HOVER
MAGENTA = SLOW
AMBER = MEDIUM
AMBER_HOVER = '#c99a3e'
ACID = ACCENT
RED = DEAD
RED_HOVER = '#c95a5a'
FAST_COLOR = FAST
MEDIUM_COLOR = MEDIUM
SLOW_COLOR = SLOW
DEAD_COLOR = DEAD
HERO_TOP = BG
HERO_BOTTOM = SURFACE
RADIUS = CARD_R
PILL = 20


ctk.set_appearance_mode('dark')
ctk.set_default_color_theme('blue')


def _lerp_color(c1, c2, t):
    """Linear interpolate two '#rrggbb' colors, return '#rrggbb'."""
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f'#{r:02x}{g:02x}{b:02x}'


class ConfigScannerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title('ScanV2Ray')
        self.geometry('900x920')
        self.minsize(820, 600)
        self.configure(fg_color=BG)

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
        self.log_scheduled = False
        self.log_filepath = None
        self.advanced_visible = False

        # Live donut chart state
        self.donut_canvas = None
        self._donut_counts = (0, 0, 0, 0)
        self._donut_pending = False
        # Coalesced UI state: the worker thread only writes these; a single
        # ~8 fps refresh loop on the main thread applies the latest values, so
        # a 50k-config scan can't flood Tk with per-config after() callbacks
        # (that was freezing the UI and lagging scroll).
        self._pending_status = None
        self._pending_progress = None
        self._pending_counts = None
        self._pending_phase = None
        self._scan_phase = 'idle'        # 'precheck' | 'test' | 'idle'
        self._skip_precheck = False      # "Stop & go to phase 2" flag

        if getattr(sys, 'frozen', False):
            base_dir = sys._MEIPASS
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        xray_path = os.path.join(base_dir, 'Core', 'xray', 'xray.exe')
        singbox_path = os.path.join(base_dir, 'Core', 'sing_box', 'sing-box.exe')
        self.scanner = Scanner(xray_path, singbox_path)

        self.scan_mode_var = StringVar(value='Quick')
        self.remarker_var = StringVar(value='')
        self.ultra_scan_var = BooleanVar(value=False)
        self.detect_country_var = BooleanVar(value=True)
        self.retry_failed_var = BooleanVar(value=False)
        self.site_check_var = BooleanVar(value=False)
        self.dedupe_var = BooleanVar(value=True)

        # Site-check configuration
        self.site_targets_default = [
            ('YouTube', 'https://www.youtube.com'),
            ('Instagram', 'https://www.instagram.com'),
            ('Telegram', 'https://web.telegram.org'),
            ('ChatGPT', 'https://chatgpt.com'),
            ('Google', 'https://www.google.com'),
        ]
        self.site_urls = {name: url for name, url in self.site_targets_default}
        self.site_vars = {name: BooleanVar(value=True) for name, _ in self.site_targets_default}
        self.site_custom = []  # list of custom names appended to site_urls/site_vars
        self.site_strict_var = BooleanVar(value=True)
        self.site_popup = None

        self._build_ui()
        # Single coalesced UI refresh loop (decouples UI rate from scan rate).
        self.after(120, self._ui_refresh)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _font(self, size=13, weight='normal'):
        return ctk.CTkFont(size=size, weight=weight)

    def _mono(self, size=12, weight='normal'):
        return ctk.CTkFont(family='Courier New', size=size, weight=weight)

    @staticmethod
    def _spaced(text):
        """Letter-spaced uppercase label for section headers."""
        return ' '.join(text.upper())

    def _accent_stripe(self, card, color):
        """Thin colored top-stripe that makes a card read like a control module."""
        stripe = ctk.CTkFrame(card, fg_color=color, width=1, height=3, corner_radius=0)
        stripe.place(relx=0.0, y=0, relwidth=1.0)
        return stripe

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()

        # Scrollable body so the full layout works on any screen size.
        self.scroll = ctk.CTkScrollableFrame(self, fg_color='transparent')
        self.scroll.grid(row=1, column=0, sticky='nsew')
        self.scroll.grid_columnconfigure(0, weight=1)

        self.main_frame = ctk.CTkFrame(self.scroll, fg_color='transparent')
        self.main_frame.grid(row=0, column=0, padx=24, pady=(16, 8), sticky='ew')
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_columnconfigure(1, weight=1)

        self._build_sources_card()
        self._build_setup_card()
        self._build_progress_card()
        self._build_results_card()

        self.log_frame = ctk.CTkFrame(self.scroll, fg_color=SURFACE, corner_radius=CARD_R,
                                      border_color=LINE, border_width=1)
        self.log_frame.grid(row=1, column=0, padx=24, pady=(4, 20), sticky='ew')
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_frame.grid_rowconfigure(1, weight=1)

        self.log_label = ctk.CTkLabel(self.log_frame, text='Activity log',
                                      font=self._font(15, 'bold'), text_color=TEXT)
        self.log_label.grid(row=0, column=0, padx=20, pady=(18, 4), sticky='w')

        self.box = ctk.CTkTextbox(self.log_frame, height=180, wrap='word',
                                  fg_color=SURFACE2, text_color=TEXT,
                                  border_color=LINE, border_width=1, corner_radius=INNER_R,
                                  font=self._mono(12))
        self.box.grid(row=1, column=0, padx=20, pady=(0, 20), sticky='nsew')

    # ---- Header (clean top bar) --------------------------------------
    def _build_header(self):
        bar = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0,
                           border_width=0, height=84)
        bar.grid(row=0, column=0, sticky='ew')
        bar.grid_columnconfigure(0, weight=1)
        bar.grid_propagate(False)

        left = ctk.CTkFrame(bar, fg_color='transparent')
        left.grid(row=0, column=0, padx=24, pady=16, sticky='w')
        ctk.CTkLabel(left, text='ScanV2Ray', font=self._font(26, 'bold'),
                     text_color=TEXT).grid(row=0, column=0, sticky='w')
        ctk.CTkLabel(left, text='Proxy reachability & speed scanner · Xray + sing-box',
                     font=self._font(12), text_color=MUTED).grid(row=1, column=0, sticky='w')

        chip = ctk.CTkFrame(bar, fg_color=SURFACE2, corner_radius=20,
                            border_width=1, border_color=LINE)
        chip.grid(row=0, column=1, padx=24, pady=16, sticky='e')
        self.status_dot = ctk.CTkLabel(chip, text='●', text_color=MUTED,
                                       font=self._font(13))
        self.status_dot.grid(row=0, column=0, padx=(14, 5), pady=6)
        self.status_chip = ctk.CTkLabel(chip, text='Idle', text_color=TEXT,
                                        font=self._font(12, 'bold'))
        self.status_chip.grid(row=0, column=1, padx=(0, 16), pady=6)

        # thin separator line under the bar
        sep = ctk.CTkFrame(self, fg_color=LINE, height=1, corner_radius=0)
        sep.grid(row=0, column=0, sticky='ews')

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
            self.status_dot.configure(text_color=dot)
            self.status_chip.configure(text=label)
        except Exception:
            pass

    # ---- Sources card -------------------------------------------------
    def _build_sources_card(self):
        self.source_frame = ctk.CTkFrame(self.main_frame, fg_color=SURFACE, corner_radius=CARD_R,
                                         border_color=LINE, border_width=1)
        self.source_frame.grid(row=0, column=0, padx=(0, 8), pady=(0, 12), sticky='nsew')
        self.source_frame.grid_columnconfigure(0, weight=1)

        self.source_title = ctk.CTkLabel(self.source_frame, text='Sources',
                                         font=self._font(15, 'bold'), text_color=TEXT)
        self.source_title.grid(row=0, column=0, padx=20, pady=(18, 2), sticky='w')

        self.source_hint = ctk.CTkLabel(
            self.source_frame,
            text='Paste links, subscription URLs, base64 text, JSON, or local file paths.',
            text_color=MUTED, font=self._font(12), wraplength=360, justify='left')
        self.source_hint.grid(row=1, column=0, padx=20, pady=(0, 10), sticky='w')

        self.source_textbox = ctk.CTkTextbox(self.source_frame, height=100, wrap='word',
                                             fg_color=SURFACE2, text_color=TEXT,
                                             border_color=LINE, border_width=1, corner_radius=INNER_R,
                                             font=self._mono(12))
        self.source_textbox.grid(row=2, column=0, padx=20, pady=(0, 8), sticky='ew')
        self._focusable(self.source_textbox)

        # Visible list of loaded sources (so user can see and remove selections)
        self.sources_listbox = Listbox(
            self.source_frame, height=6, selectmode='extended',
            background=SURFACE2, foreground=TEXT, borderwidth=0, highlightthickness=1,
            highlightbackground=LINE, selectbackground=ACCENT, selectforeground=WHITE,
            activestyle='none', font=('Courier New', 9))
        self.sources_listbox.grid(row=3, column=0, padx=20, pady=(0, 10), sticky='ew')

        self.source_actions = ctk.CTkFrame(self.source_frame, fg_color='transparent')
        self.source_actions.grid(row=4, column=0, padx=15, pady=(0, 10), sticky='ew')
        self.source_actions.grid_columnconfigure((0, 1), weight=1)

        self.add_links_btn = self._secondary_btn(self.source_actions, 'Add pasted', self.add_manual_sources)
        self.add_links_btn.grid(row=0, column=0, padx=5, pady=(0, 6), sticky='ew')

        self.add_files_btn = self._secondary_btn(self.source_actions, 'Add files', self.add_files)
        self.add_files_btn.grid(row=0, column=1, padx=5, pady=(0, 6), sticky='ew')

        self.remove_selected_btn = self._danger_btn(self.source_actions, 'Remove selected', self.remove_selected_sources)
        self.remove_selected_btn.grid(row=1, column=0, padx=5, sticky='ew')

        self.clear_sources_btn = self._secondary_btn(self.source_actions, 'Clear', self.clear_sources)
        self.clear_sources_btn.grid(row=1, column=1, padx=5, sticky='ew')

        # Protocol filters and counts
        self.protocols = ['vmess', 'vless', 'ss', 'trojan', 'socks', 'http',
                          'hysteria2', 'tuic', 'anytls']
        self.protocol_vars = {p: StringVar(value='1') for p in self.protocols}
        self.protocol_count_labels = {}

        self.protocols_frame = ctk.CTkFrame(self.source_frame, fg_color=SURFACE2, corner_radius=INNER_R,
                                            border_color=LINE, border_width=1)
        self.protocols_frame.grid(row=5, column=0, padx=20, pady=(6, 6), sticky='ew')
        ncols = 5
        for c in range(ncols):
            self.protocols_frame.grid_columnconfigure(c, weight=1)

        for i, proto in enumerate(self.protocols):
            row = (i // ncols) * 2
            col = i % ncols
            chk = ctk.CTkCheckBox(
                self.protocols_frame, text=proto.upper(), variable=self.protocol_vars[proto],
                onvalue='1', offvalue='0', command=self.update_link_count,
                font=self._mono(11), text_color=TEXT, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                checkmark_color=WHITE, border_color=LINE, checkbox_width=18, checkbox_height=18)
            chk.grid(row=row, column=col, sticky='w', padx=8, pady=(8, 0))
            lbl = ctk.CTkLabel(self.protocols_frame, text='0', text_color=TEXT,
                               font=self._mono(18, 'bold'))
            lbl.grid(row=row + 1, column=col, sticky='w', padx=8, pady=(0, 8))
            self.protocol_count_labels[proto] = lbl

        self.link_count_label = ctk.CTkLabel(
            self.source_frame, text='0 configs loaded',
            font=self._mono(14, 'bold'), text_color=ACCENT)
        self.link_count_label.grid(row=6, column=0, padx=20, pady=(4, 18), sticky='w')

    # ---- Setup card ---------------------------------------------------
    def _build_setup_card(self):
        self.setup_frame = ctk.CTkFrame(self.main_frame, fg_color=SURFACE, corner_radius=CARD_R,
                                        border_color=LINE, border_width=1)
        self.setup_frame.grid(row=0, column=1, padx=(8, 0), pady=(0, 12), sticky='nsew')
        self.setup_frame.grid_columnconfigure(0, weight=1)

        self.setup_title = ctk.CTkLabel(self.setup_frame, text='Scan setup',
                                        font=self._font(15, 'bold'), text_color=TEXT)
        self.setup_title.grid(row=0, column=0, padx=20, pady=(18, 2), sticky='w')

        self.mode_label = ctk.CTkLabel(self.setup_frame, text='Scan mode',
                                       text_color=MUTED, font=self._font(12))
        self.mode_label.grid(row=1, column=0, padx=20, pady=(8, 4), sticky='w')

        self.mode_selector = ctk.CTkSegmentedButton(
            self.setup_frame, values=['Quick', 'Full'], variable=self.scan_mode_var,
            command=lambda _value: self.update_link_count(),
            selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
            unselected_color=SURFACE2, unselected_hover_color=ELEV,
            text_color=TEXT, fg_color=SURFACE2, font=self._font(13, 'bold'))
        self.mode_selector.grid(row=2, column=0, padx=20, pady=(0, 12), sticky='ew')
        self.mode_selector.set('Quick')

        self.ultra_switch = ctk.CTkSwitch(
            self.setup_frame, text='Ultra scan',
            variable=self.ultra_scan_var, onvalue=True, offvalue=False,
            progress_color=ACCENT, button_color=TEXT, button_hover_color=MUTED,
            text_color=TEXT, font=self._font(12))
        self.ultra_switch.grid(row=3, column=0, padx=20, pady=(0, 14), sticky='w')

        self.select_button = self._secondary_btn(self.setup_frame, 'Choose folder', self.select_folder)
        self.select_button.grid(row=4, column=0, padx=20, pady=(0, 8), sticky='ew')

        self.folder_label = ctk.CTkLabel(
            self.setup_frame, text='No folder chosen',
            text_color=MUTED, font=self._mono(11), wraplength=220, justify='left')
        self.folder_label.grid(row=5, column=0, padx=20, pady=(0, 12), sticky='w')

        self.start_button = ctk.CTkButton(
            self.setup_frame, text='Start scan', command=self.start_scan, state='disabled',
            height=44, corner_radius=BTN_R, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color=WHITE, text_color_disabled='#C8CED8', font=self._font(15, 'bold'))
        self.start_button.grid(row=6, column=0, padx=20, pady=(0, 10), sticky='ew')

        # Speed preset — fills the numeric fields below (still editable by hand).
        self.preset_var = StringVar(value='Medium')
        ctk.CTkLabel(self.setup_frame, text='Speed preset', text_color=MUTED,
                     font=self._font(12)).grid(row=7, column=0, padx=20, pady=(2, 2), sticky='w')
        self.preset_selector = ctk.CTkSegmentedButton(
            self.setup_frame, values=['Slow', 'Medium', 'Fast'], variable=self.preset_var,
            command=self._apply_preset, fg_color=SURFACE2, selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER, unselected_color=SURFACE2,
            unselected_hover_color=ELEV, text_color=TEXT, font=self._font(12, 'bold'))
        self.preset_selector.grid(row=8, column=0, padx=20, pady=(0, 10), sticky='ew')
        self.preset_selector.set('Medium')

        # Advanced settings are always visible (no show/hide toggle).
        self._build_advanced_frame()
        self.advanced_frame.grid(row=9, column=0, padx=20, pady=(0, 14), sticky='ew')

    PRESETS = {
        'Slow':   {'precheck': '80',  'test': '12', 'speed': '6',  'timeout': '5000'},
        'Medium': {'precheck': '200', 'test': '32', 'speed': '24', 'timeout': '3500'},
        'Fast':   {'precheck': '400', 'test': '64', 'speed': '40', 'timeout': '2500'},
    }

    def _apply_preset(self, value):
        preset = self.PRESETS.get(value)
        if not preset:
            return
        for entry, key in ((self.precheck_entry, 'precheck'), (self.test_entry, 'test'),
                           (self.speed_entry, 'speed'), (self.timeout_entry, 'timeout')):
            entry.delete(0, END)
            entry.insert(0, preset[key])

    def _build_advanced_frame(self):
        self.advanced_frame = ctk.CTkFrame(self.setup_frame, fg_color=SURFACE2, corner_radius=INNER_R,
                                           border_color=LINE, border_width=1)
        self.advanced_frame.grid_columnconfigure((0, 1), weight=1)

        def num_entry(default):
            e = ctk.CTkEntry(self.advanced_frame, fg_color=BG, text_color=TEXT,
                             border_color=LINE, border_width=1, corner_radius=INNER_R,
                             font=self._mono(13, 'bold'))
            e.insert(0, default)
            self._focusable(e)
            return e

        def field_label(text):
            return ctk.CTkLabel(self.advanced_frame, text=text, text_color=MUTED, font=self._font(12))

        # Row 0/1: precheck workers | test workers
        field_label('Precheck workers').grid(row=0, column=0, padx=10, pady=(12, 4), sticky='w')
        field_label('Test workers').grid(row=0, column=1, padx=10, pady=(12, 4), sticky='w')
        self.precheck_entry = num_entry('200')
        self.precheck_entry.grid(row=1, column=0, padx=10, pady=(0, 8), sticky='ew')
        self.test_entry = num_entry('32')
        self.test_entry.grid(row=1, column=1, padx=10, pady=(0, 8), sticky='ew')

        # Row 2/3: speed-test slots | timeout
        field_label('Speed-test slots').grid(row=2, column=0, padx=10, pady=(6, 4), sticky='w')
        field_label('Timeout (ms)').grid(row=2, column=1, padx=10, pady=(6, 4), sticky='w')
        self.speed_entry = num_entry('24')
        self.speed_entry.grid(row=3, column=0, padx=10, pady=(0, 8), sticky='ew')
        self.timeout_entry = num_entry('3500')
        self.timeout_entry.grid(row=3, column=1, padx=10, pady=(0, 8), sticky='ew')

        # Remark override
        field_label('Remark (optional)').grid(row=4, column=0, padx=10, pady=(6, 4), sticky='w')
        self.remarker_entry = ctk.CTkEntry(
            self.advanced_frame, textvariable=self.remarker_var, fg_color=BG,
            text_color=TEXT, border_color=LINE, border_width=1, corner_radius=INNER_R,
            font=self._mono(12))
        self.remarker_entry.grid(row=5, column=0, columnspan=2, padx=10, pady=(0, 10), sticky='ew')
        self._focusable(self.remarker_entry)

        # Feature toggles — single column so labels never clip in the narrow card
        self.detect_country_switch = self._switch(self.advanced_frame, 'Detect exit country', self.detect_country_var)
        self.detect_country_switch.grid(row=6, column=0, columnspan=2, padx=10, pady=(4, 4), sticky='w')

        self.retry_failed_switch = self._switch(self.advanced_frame, 'Retry failed once', self.retry_failed_var)
        self.retry_failed_switch.grid(row=7, column=0, columnspan=2, padx=10, pady=(4, 4), sticky='w')

        self.dedupe_switch = self._switch(self.advanced_frame, 'Remove duplicates', self.dedupe_var)
        self.dedupe_switch.grid(row=8, column=0, columnspan=2, padx=10, pady=(4, 4), sticky='w')

        self.site_check_switch = self._switch(self.advanced_frame, 'Check site reachability', self.site_check_var)
        self.site_check_switch.grid(row=9, column=0, columnspan=2, padx=10, pady=(4, 4), sticky='w')

        self.site_config_btn = ctk.CTkButton(
            self.advanced_frame, text='Configure sites…', command=self.open_site_config,
            width=140, height=28, corner_radius=BTN_R, fg_color=BG,
            border_width=1, border_color=LINE, hover_color=ELEV,
            text_color=TEXT, font=self._font(12))
        self.site_config_btn.grid(row=10, column=0, columnspan=2, padx=10, pady=(2, 12), sticky='w')

    # ---- Progress card ------------------------------------------------
    def _build_progress_card(self):
        self.progress_frame = ctk.CTkFrame(self.main_frame, fg_color=SURFACE, corner_radius=CARD_R,
                                           border_color=LINE, border_width=1)
        self.progress_frame.grid(row=1, column=0, columnspan=2, pady=(0, 12), sticky='ew')
        self.progress_frame.grid_columnconfigure(0, weight=1)

        self.progress_title = ctk.CTkLabel(self.progress_frame, text='Progress',
                                           font=self._font(15, 'bold'), text_color=TEXT)
        self.progress_title.grid(row=0, column=0, padx=20, pady=(18, 2), sticky='w')

        self.status = ctk.CTkLabel(self.progress_frame, text='Ready',
                                   font=self._font(13), text_color=MUTED)
        self.status.grid(row=1, column=0, padx=20, pady=(0, 8), sticky='w')

        self.progress_bar = ctk.CTkProgressBar(
            self.progress_frame, progress_color=ACCENT, fg_color=SURFACE2, height=8, corner_radius=4)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=2, column=0, padx=20, pady=(0, 12), sticky='ew')

        self.controls_frame = ctk.CTkFrame(self.progress_frame, fg_color='transparent')
        self.controls_frame.grid(row=3, column=0, padx=15, pady=(6, 16), sticky='ew')
        self.controls_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self.pause_button = ctk.CTkButton(
            self.controls_frame, text='Pause', command=self.toggle_pause, state='disabled',
            corner_radius=BTN_R, height=40, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color=WHITE, text_color_disabled='#C8CED8', font=self._font(13, 'bold'))
        self.pause_button.grid(row=0, column=0, padx=5, sticky='ew')

        self.stop_save_button = ctk.CTkButton(
            self.controls_frame, text='Stop and save', command=self._stop_save_action, state='disabled',
            corner_radius=BTN_R, height=40, fg_color=SURFACE2, border_width=1,
            border_color=LINE, hover_color=ELEV, text_color=TEXT,
            text_color_disabled='#C8CED8', font=self._font(13, 'bold'))
        self.stop_save_button.grid(row=0, column=1, padx=5, sticky='ew')

        self.stop_button = ctk.CTkButton(
            self.controls_frame, text='Stop', command=self.stop_scan_now, state='disabled',
            corner_radius=BTN_R, height=40, fg_color=SURFACE2, border_width=1,
            border_color=DEAD_DIM, hover_color=ELEV, text_color=DEAD,
            text_color_disabled='#C8CED8', font=self._font(13, 'bold'))
        self.stop_button.grid(row=0, column=2, padx=5, sticky='ew')

    # ---- Results card (mini dashboard: donut + tiles + copy) ----------
    def _build_results_card(self):
        self.results_frame = ctk.CTkFrame(self.main_frame, fg_color=SURFACE, corner_radius=CARD_R,
                                          border_color=LINE, border_width=1)
        self.results_frame.grid(row=2, column=0, columnspan=2, sticky='ew')
        self.results_frame.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(self.results_frame, text='Results',
                             font=self._font(15, 'bold'), text_color=TEXT)
        title.grid(row=0, column=0, padx=20, pady=(18, 2), sticky='w')
        sub = ctk.CTkLabel(self.results_frame, text='Live classification of tested configs',
                           font=self._font(12), text_color=MUTED)
        sub.grid(row=1, column=0, padx=20, pady=(0, 12), sticky='w')

        content = ctk.CTkFrame(self.results_frame, fg_color='transparent')
        content.grid(row=2, column=0, padx=20, pady=(0, 4), sticky='ew')
        content.grid_columnconfigure(1, weight=1)

        # Live donut chart (centerpiece)
        self.donut_canvas = ctk.CTkCanvas(content, width=200, height=292,
                                          highlightthickness=0, bd=0, bg=SURFACE)
        self.donut_canvas.grid(row=0, column=0, padx=(0, 20), pady=0, sticky='n')
        self.donut_canvas.bind('<Configure>', self._draw_donut)

        # Result tiles (2x2)
        tiles = ctk.CTkFrame(content, fg_color='transparent')
        tiles.grid(row=0, column=1, sticky='nsew')
        tiles.grid_columnconfigure((0, 1), weight=1)
        tiles.grid_rowconfigure((0, 1), weight=1)

        stat_specs = [
            ('fast_label', 'Fast', FAST),
            ('medium_label', 'Medium', MEDIUM),
            ('slow_label', 'Slow', SLOW),
            ('dead_label', 'Dead', DEAD),
        ]
        for idx, (attr, label, color) in enumerate(stat_specs):
            r, cc = idx // 2, idx % 2
            tile = ctk.CTkFrame(tiles, fg_color=SURFACE2, corner_radius=INNER_R,
                                border_color=LINE, border_width=1)
            tile.grid(row=r, column=cc, padx=6, pady=6, sticky='nsew')
            tile.grid_columnconfigure(1, weight=1)
            dot = ctk.CTkLabel(tile, text='●', text_color=color, font=self._font(12))
            dot.grid(row=0, column=0, padx=(16, 6), pady=(14, 0), sticky='w')
            cap = ctk.CTkLabel(tile, text=label, text_color=MUTED, font=self._font(12))
            cap.grid(row=0, column=1, padx=(0, 16), pady=(14, 0), sticky='w')
            num = ctk.CTkLabel(tile, text='0', text_color=color, font=self._mono(28, 'bold'))
            num.grid(row=1, column=0, columnspan=2, padx=18, pady=(0, 14), sticky='w')
            setattr(self, attr, num)

        # Copy buttons row
        copy_frame = ctk.CTkFrame(self.results_frame, fg_color='transparent')
        copy_frame.grid(row=3, column=0, padx=15, pady=(10, 16), sticky='ew')
        copy_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.copy_fast_btn = self._copy_btn(copy_frame, 'Copy Fast', self.copy_fast)
        self.copy_fast_btn.grid(row=0, column=0, padx=5, sticky='ew')

        self.copy_medium_btn = self._copy_btn(copy_frame, 'Copy Medium', self.copy_medium)
        self.copy_medium_btn.grid(row=0, column=1, padx=5, sticky='ew')

        self.copy_slow_btn = self._copy_btn(copy_frame, 'Copy Slow', self.copy_slow)
        self.copy_slow_btn.grid(row=0, column=2, padx=5, sticky='ew')

        self.copy_all_btn = ctk.CTkButton(
            copy_frame, text='Copy All', command=self.copy_all, state='disabled',
            corner_radius=BTN_R, height=40, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color=WHITE, font=self._font(13, 'bold'))
        self.copy_all_btn.grid(row=0, column=3, padx=5, sticky='ew')

        # Initial empty-state render
        self._draw_donut()

    # ---- Styled-widget helpers ---------------------------------------
    def _secondary_btn(self, parent, text, command):
        return ctk.CTkButton(parent, text=text, command=command, corner_radius=BTN_R,
                             height=38, fg_color=SURFACE2, border_width=1,
                             border_color=LINE, hover_color=ELEV,
                             text_color=TEXT, font=self._font(13, 'bold'))

    def _danger_btn(self, parent, text, command):
        return ctk.CTkButton(parent, text=text, command=command, corner_radius=BTN_R,
                             height=38, fg_color=SURFACE2, border_width=1,
                             border_color=DEAD_DIM, hover_color=ELEV,
                             text_color=DEAD, font=self._font(13, 'bold'))

    def _copy_btn(self, parent, text, command):
        return ctk.CTkButton(parent, text=text, command=command, state='disabled',
                             corner_radius=BTN_R, height=40, fg_color=SURFACE2, border_width=1,
                             border_color=LINE, hover_color=ELEV, text_color=TEXT,
                             text_color_disabled='#C8CED8', font=self._font(13, 'bold'))

    def _switch(self, parent, text, variable):
        return ctk.CTkSwitch(parent, text=text, variable=variable, onvalue=True, offvalue=False,
                             progress_color=ACCENT, button_color=TEXT, button_hover_color=MUTED,
                             text_color=TEXT, font=self._font(12))

    def _focusable(self, widget):
        """Give an input an ACCENT focus border (falls back silently)."""
        try:
            widget.bind('<FocusIn>', lambda e: widget.configure(border_color=ACCENT))
            widget.bind('<FocusOut>', lambda e: widget.configure(border_color=LINE))
        except Exception:
            pass
        return widget

    # ------------------------------------------------------------------
    # Live graphics — donut chart
    # ------------------------------------------------------------------
    def _draw_donut(self, event=None):
        # Throttle: coalesce bursts of redraws (live stats + <Configure>) to
        # at most one render per ~150 ms so the main loop never gets flooded.
        if self._donut_pending:
            return
        self._donut_pending = True
        self.after(150, self._render_donut)

    def _render_donut(self):
        self._donut_pending = False
        c = getattr(self, 'donut_canvas', None)
        if c is None:
            return
        try:
            if not c.winfo_exists():
                return
        except Exception:
            return
        c.delete('all')
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 1:
            w = 200
        if h <= 1:
            h = 292

        cx = w / 2
        cy = 96
        r_out = 82
        band = 26                      # ring thickness
        rm = r_out - band / 2          # mid radius the arc stroke follows
        bbox = (cx - rm, cy - rm, cx + rm, cy + rm)

        fast, medium, slow, dead = self._donut_counts
        total = fast + medium + slow + dead
        segs = [(fast, FAST), (medium, MEDIUM), (slow, SLOW), (dead, DEAD)]

        # Background track ring (always visible / neutral empty state)
        c.create_arc(bbox, start=0, extent=359.999, style='arc',
                     outline=SURFACE2, width=band)

        if total > 0:
            gap = 2.0                  # small angular gap between segments
            start = 90.0               # start at top, go clockwise
            active = [(v, col) for v, col in segs if v > 0]
            multi = len(active) > 1
            for v, col in active:
                extent = -360.0 * (v / total)
                draw_extent = extent
                if multi:
                    # leave a 2px surface gap between adjacent arcs
                    draw_extent = extent + gap if extent + gap < 0 else extent
                if abs(draw_extent) < 0.1:
                    draw_extent = -0.1
                # clamp so a full-circle single segment still renders
                if draw_extent <= -359.999:
                    draw_extent = -359.999
                c.create_arc(bbox, start=start, extent=draw_extent, style='arc',
                             outline=col, width=band)
                start += extent

        # Center readout
        c.create_text(cx, cy - 8, text=str(total), fill=TEXT,
                      font=('Courier New', 30, 'bold'))
        c.create_text(cx, cy + 20, text='TESTED', fill=MUTED,
                      font=('Segoe UI', 10))

        # Legend (single column) below the ring
        entries = [('Fast', fast, FAST), ('Medium', medium, MEDIUM),
                   ('Slow', slow, SLOW), ('Dead', dead, DEAD)]
        ly0 = 192
        lh = 23
        for i, (lbl, val, col) in enumerate(entries):
            y = ly0 + i * lh
            c.create_oval(20, y - 4, 29, y + 5, fill=col, outline='')
            c.create_text(38, y, text=lbl, anchor='w', fill=MUTED,
                          font=('Segoe UI', 11))
            c.create_text(w - 20, y, text=str(val), anchor='e', fill=col,
                          font=('Courier New', 12, 'bold'))

    # ------------------------------------------------------------------
    # Site-check configuration popup
    # ------------------------------------------------------------------
    def open_site_config(self):
        if self.site_popup is not None and self.site_popup.winfo_exists():
            self.site_popup.focus()
            return

        popup = ctk.CTkToplevel(self)
        popup.title('Site check')
        popup.geometry('420x480')
        popup.configure(fg_color=BG)
        self.site_popup = popup

        # Force the popup to the front and make it modal so it never hides
        # behind the main window (notably on Windows where CTkToplevel drops back).
        popup.transient(self)
        popup.update_idletasks()
        popup.lift()
        popup.focus_force()
        popup.attributes('-topmost', True)
        popup.after(300, lambda: popup.winfo_exists() and popup.attributes('-topmost', False))
        popup.grab_set()

        header = ctk.CTkLabel(popup, text='Sites to verify',
                              font=self._font(16, 'bold'), text_color=TEXT)
        header.pack(padx=18, pady=(16, 2), anchor='w')
        ctk.CTkLabel(popup, text='Each selected site must be reachable through the proxy.',
                     text_color=MUTED, font=self._font(12), wraplength=380,
                     justify='left').pack(padx=18, pady=(0, 8), anchor='w')

        self.site_list_frame = ctk.CTkScrollableFrame(popup, fg_color=PANEL, corner_radius=RADIUS,
                                                      height=220)
        self.site_list_frame.pack(padx=18, pady=(0, 10), fill='both', expand=True)
        self._populate_site_list()

        add_frame = ctk.CTkFrame(popup, fg_color='transparent')
        add_frame.pack(padx=18, pady=(0, 8), fill='x')
        add_frame.grid_columnconfigure(0, weight=1)
        self.site_add_entry = ctk.CTkEntry(add_frame, placeholder_text='https://example.com',
                                           fg_color=PANEL2, text_color=TEXT, border_color=LINE,
                                           border_width=1, corner_radius=8, font=self._mono(12))
        self.site_add_entry.grid(row=0, column=0, padx=(0, 6), sticky='ew')
        add_btn = ctk.CTkButton(add_frame, text='Add', width=70, command=self._add_custom_site,
                                corner_radius=PILL, fg_color=CYAN, hover_color=CYAN_HOVER,
                                text_color=BG, font=self._font(12, 'bold'))
        add_btn.grid(row=0, column=1)

        strict = ctk.CTkCheckBox(popup, text='Strict (must reach all selected sites)',
                                 variable=self.site_strict_var, onvalue=True, offvalue=False,
                                 fg_color=CYAN, hover_color=CYAN_HOVER, checkmark_color=BG,
                                 border_color=LINE, text_color=TEXT, font=self._font(12))
        strict.pack(padx=18, pady=(4, 10), anchor='w')

        done_btn = ctk.CTkButton(popup, text='Done', command=popup.destroy,
                                 corner_radius=PILL, height=40, fg_color=CYAN,
                                 hover_color=CYAN_HOVER, text_color=BG,
                                 font=self._font(14, 'bold'))
        done_btn.pack(padx=18, pady=(0, 16), fill='x')

    def _populate_site_list(self):
        for child in self.site_list_frame.winfo_children():
            child.destroy()
        for name in self.site_urls:
            row = ctk.CTkFrame(self.site_list_frame, fg_color='transparent')
            row.pack(fill='x', pady=3)
            chk = ctk.CTkCheckBox(row, text=name, variable=self.site_vars[name],
                                  onvalue=True, offvalue=False, fg_color=CYAN,
                                  hover_color=CYAN_HOVER, checkmark_color=BG,
                                  border_color=LINE, text_color=TEXT, font=self._font(13))
            chk.pack(side='left', anchor='w')
            ctk.CTkLabel(row, text=self.site_urls[name], text_color=MUTED,
                         font=self._mono(11)).pack(side='left', padx=(10, 0))

    def _add_custom_site(self):
        url = self.site_add_entry.get().strip()
        if not url:
            return
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        # derive a readable name from the host
        host = url.split('://', 1)[-1].split('/', 1)[0]
        name = host or url
        base = name
        i = 2
        while name in self.site_urls:
            name = f'{base} ({i})'
            i += 1
        self.site_urls[name] = url
        self.site_vars[name] = BooleanVar(value=True)
        self.site_custom.append(name)
        self.site_add_entry.delete(0, END)
        self._populate_site_list()

    def _build_site_targets(self):
        return [(name, self.site_urls[name]) for name in self.site_urls
                if self.site_vars[name].get()]


    # ------------------------------------------------------------------
    # Thread-safe logging / UI marshaling
    # ------------------------------------------------------------------
    def log(self, text):
        # Worker threads only enqueue; the refresh loop flushes (bounded).
        with self.log_lock:
            self.log_queue.append(text)

    def _ui_refresh(self):
        # Runs on the main thread ~8x/sec; applies only the latest pending
        # values so a fast scan can never flood the event loop.
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        try:
            if self._pending_status is not None:
                s = self._pending_status
                self._pending_status = None
                self.status.configure(text=s)
                self._update_chip(s)
            if self._pending_progress is not None:
                p = self._pending_progress
                self._pending_progress = None
                self.progress_bar.set(p)
            if self._pending_counts is not None:
                f, m, s, d = self._pending_counts
                self._pending_counts = None
                self.fast_label.configure(text=str(f))
                self.medium_label.configure(text=str(m))
                self.slow_label.configure(text=str(s))
                self.dead_label.configure(text=str(d))
                self._donut_counts = (f, m, s, d)
                self._draw_donut()
            if self._pending_phase is not None:
                ph = self._pending_phase
                self._pending_phase = None
                self._scan_phase = ph
                if ph == 'precheck':
                    self.stop_save_button.configure(text='Stop → Phase 2')
                else:
                    self.stop_save_button.configure(text='Stop and save')
            self._flush_log()
        except Exception:
            pass
        self.after(120, self._ui_refresh)

    def _flush_log(self):
        with self.log_lock:
            lines = self.log_queue
            self.log_queue = []
        if not lines:
            return
        self.box.insert('end', '\n'.join(lines) + '\n')
        # Cap the textbox so a huge scan doesn't bloat it (kept ~500 lines).
        try:
            total = int(self.box.index('end-1c').split('.')[0])
            if total > 500:
                self.box.delete('1.0', f'{total - 500}.0')
        except Exception:
            pass
        self.box.see('end')
        if self.log_filepath:
            try:
                with open(self.log_filepath, 'a', encoding='utf-8') as fp:
                    fp.write('\n'.join(lines) + '\n')
            except Exception:
                pass

    def set_status(self, text):
        self._pending_status = text

    def set_progress(self, value):
        self._pending_progress = value

    def set_control_buttons(self, pause, stop_save, stop):
        self.after(0, lambda: self._set_control_buttons(pause, stop_save, stop))

    def _set_control_buttons(self, pause, stop_save, stop):
        self.pause_button.configure(state=pause)
        self.stop_save_button.configure(state=stop_save)
        self.stop_button.configure(state=stop)

    def set_scan_buttons(self, start_state):
        self.after(0, lambda: self.start_button.configure(state=start_state))

    def set_copy_buttons(self, state):
        self.after(0, lambda: [
            button.configure(state=state)
            for button in (self.copy_fast_btn, self.copy_medium_btn,
                           self.copy_slow_btn, self.copy_all_btn)
        ])

    def update_live_stats(self, fast, medium, slow, dead):
        self._pending_counts = (fast, medium, slow, dead)

    def update_link_count(self):
        # Update total loaded count
        self.after(0, lambda: self.link_count_label.configure(text=f'{len(self.loaded_links)} configs loaded'))
        # keep the listbox in sync
        self.after(0, lambda: self.refresh_sources_listbox())
        # update protocol counts display
        counts = self._compute_protocol_counts()
        for proto, lbl in getattr(self, 'protocol_count_labels', {}).items():
            self.after(0, lambda p=proto, l=lbl: l.configure(text=str(counts.get(p, 0))))

        ready_to_scan = bool(self._filtered_loaded_links() and self.folder_path and self._selected_methods())
        self.set_scan_buttons('normal' if ready_to_scan else 'disabled')

    def refresh_sources_listbox(self):
        try:
            self.sources_listbox.delete(0, END)
            for item in sorted(self.loaded_links):
                proto = self.link_protocols.get(item)
                display = f'[{proto}] {item}' if proto else item
                if len(display) > 180:
                    display = display[:170] + '...'
                self.sources_listbox.insert(END, display)
        except Exception:
            # If listbox not available yet or error occurs, ignore silently
            pass

    def remove_selected_sources(self):
        try:
            selection = list(self.sources_listbox.curselection())
            if not selection:
                self.log('No source selected to remove.')
                return
            # Map visible indices to sorted loaded_links
            items = sorted(self.loaded_links)
            to_remove = [items[i] for i in selection if 0 <= i < len(items)]
            for item in to_remove:
                if item in self.loaded_links:
                    self.loaded_links.remove(item)
                    if item in self.link_protocols:
                        self.link_protocols.pop(item, None)
            self.log(f'Removed {len(to_remove)} selected source(s).')
            self.update_link_count()
        except Exception as e:
            self.log(f'Error removing selected sources: {e}')

    def _compute_protocol_counts(self):
        counts = {p: 0 for p in self.protocols}
        # Use cached parsed protocols when available; parse only missing ones
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
        # Return subset of loaded_links matching selected protocol checkboxes
        selected = {p for p, var in self.protocol_vars.items() if var.get() in ('1', 1, True, 'True')}
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

    def _selected_methods(self):
        return ['xray'] if self.scan_mode_var.get() == 'Full' else ['fast']

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
        file_paths = filedialog.askopenfilenames(filetypes=[('Text files', '*.txt'), ('All files', '*.*')])
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
        raw = self.source_textbox.get('1.0', 'end').strip()
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

    def add_subscription_source(self):
        self.add_manual_sources()

    def clear_sources(self):
        self.loaded_links.clear()
        self.link_protocols.clear()
        self.log('Sources cleared.')
        self.update_link_count()

    def select_folder(self):
        self.folder_path = filedialog.askdirectory()
        if self.folder_path:
            display_path = self.folder_path
            if len(display_path) > 54:
                display_path = '...' + display_path[-51:]
            self.folder_label.configure(text=display_path, text_color=TEXT)
            self.set_status(f'Output folder selected: {self.folder_path}')
            self.update_link_count()

    # ------------------------------------------------------------------
    # Pause / stop control
    # ------------------------------------------------------------------
    def toggle_pause(self):
        if self.scan_state == 'running':
            self.scan_state = 'paused'
            self.pause_button.configure(text='Resume', fg_color=CYAN, hover_color=CYAN_HOVER)
            self.log('Scan paused.')
            self.set_status('Scan paused')
        elif self.scan_state == 'paused':
            self.scan_state = 'running'
            self.pause_button.configure(text='Pause', fg_color=AMBER, hover_color=AMBER_HOVER)
            self.log('Scan resumed.')
            self.set_status('Scan resumed')
            with self.pause_cond:
                self.pause_cond.notify_all()

    def stop_scan_now(self):
        self.scan_state = 'stopping'
        self.log('Stopping scan and discarding partial results.')
        self.set_status('Stopping...')
        self.set_control_buttons('disabled', 'disabled', 'disabled')
        with self.pause_cond:
            self.pause_cond.notify_all()

    def stop_and_save(self):
        self.scan_state = 'stopping_save'
        self.log('Stopping scan and saving completed results.')
        self.set_status('Saving progress...')
        self.set_control_buttons('disabled', 'disabled', 'disabled')
        with self.pause_cond:
            self.pause_cond.notify_all()

    def set_phase(self, phase):
        # Called from the worker thread; the refresh loop swaps the button label.
        self._pending_phase = phase

    def _stop_save_action(self):
        # Dual-purpose middle button. In phase 1 (precheck) it skips the rest of
        # the prechecks and jumps to phase 2 without discarding anything; in
        # phase 2 (real test) it stops and saves what has completed.
        if self._scan_phase == 'precheck':
            self._skip_precheck = True
            self.log('Skipping remaining prechecks — going straight to phase 2.')
            self.set_status('Skipping precheck → phase 2')
        else:
            self.stop_and_save()

    def check_pause_and_stop(self):
        if self.scan_state in ('stopping', 'stopping_save'):
            return False
        if self.scan_state == 'paused':
            with self.pause_cond:
                while self.scan_state == 'paused':
                    self.pause_cond.wait(timeout=0.5)
        return self.scan_state not in ('stopping', 'stopping_save')

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

        self.box.delete('1.0', 'end')
        self.log_filepath = None
        if self.folder_path:
            log_dir = os.path.join(self.folder_path, 'Scan_Results')
            os.makedirs(log_dir, exist_ok=True)
            log_filepath = os.path.join(log_dir, 'scan_log.txt')
            with open(log_filepath, 'w', encoding='utf-8') as f:
                f.write(f'=== ScanV2Ray LOG STARTED AT {time.strftime("%Y-%m-%d %H:%M:%S")} ===\n')
            # Store the path so log lines get persisted to disk during the scan
            self.log_filepath = log_filepath

        self.log('Starting scan...')
        self.set_progress(0)
        self.set_scan_buttons('disabled')
        self.set_copy_buttons('disabled')
        self.fast_links = []
        self.medium_links = []
        self.slow_links = []
        self.active = []
        self.update_live_stats(0, 0, 0, 0)
        self.scan_state = 'running'
        self.pause_button.configure(text='Pause', fg_color=AMBER, hover_color=AMBER_HOVER)
        self.set_control_buttons('normal', 'normal', 'normal')

        # Read GUI inputs on the MAIN thread (Tk access is not thread-safe).
        try:
            precheck_workers = int(self.precheck_entry.get().strip())
            if precheck_workers <= 0:
                raise ValueError
        except Exception:
            precheck_workers = 200
            self.log('Invalid precheck workers. Using 200.')

        try:
            test_workers = int(self.test_entry.get().strip())
            if test_workers <= 0:
                raise ValueError
        except Exception:
            test_workers = 32
            self.log('Invalid test workers. Using 32.')

        try:
            speed_limit = int(self.speed_entry.get().strip())
            if speed_limit <= 0:
                raise ValueError
        except Exception:
            speed_limit = 24
            self.log('Invalid speed-test slots. Using 24.')

        try:
            timeout_ms = float(self.timeout_entry.get().strip())
            if timeout_ms <= 0:
                raise ValueError
            timeout = timeout_ms / 1000.0
        except Exception:
            timeout = 3.5
            self.log('Invalid timeout. Using 3500ms.')

        try:
            remark_override = self.remarker_var.get().strip()
        except Exception as e:
            remark_override = ''
            self.log(f'Error reading Remark field: {e}')

        try:
            ultra_scan = bool(self.ultra_scan_var.get())
        except Exception as e:
            ultra_scan = False
            self.log(f'Error reading Ultra Scan flag: {e}')

        try:
            detect_country = bool(self.detect_country_var.get())
        except Exception as e:
            detect_country = True
            self.log(f'Error reading Detect exit country flag: {e}')
        try:
            retry_failed = bool(self.retry_failed_var.get())
        except Exception as e:
            retry_failed = False
            self.log(f'Error reading Retry failed once flag: {e}')
        try:
            site_check = bool(self.site_check_var.get())
        except Exception as e:
            site_check = False
            self.log(f'Error reading Check site reachability flag: {e}')
        try:
            dedupe = bool(self.dedupe_var.get())
        except Exception as e:
            dedupe = True
            self.log(f'Error reading Remove duplicates flag: {e}')

        # Build site-check targets on the main thread
        if site_check:
            try:
                site_targets = self._build_site_targets()
            except Exception as e:
                site_targets = []
                self.log(f'Error reading site targets: {e}')
            try:
                site_strict = bool(self.site_strict_var.get())
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
            },
            daemon=True
        ).start()

    def run_scan(self, methods, filtered_links, *, precheck_workers, test_workers, speed_limit,
                 timeout, remark_override, ultra, detect_country, retry_failed, site_check,
                 dedupe, site_targets, site_strict):
        try:
            # Reset any prior abort flag before starting fresh work
            self.scanner.reset_abort()
            self._skip_precheck = False
            self.set_phase('precheck')

            # Configure scanner-driven features for this run
            self.scanner.detect_country = detect_country
            self.scanner.site_check = site_check
            self.scanner.site_strict = site_strict
            self.scanner.site_targets = list(site_targets) if site_check else []

            if methods and not os.path.exists(self.scanner.xray_path):
                self.log('xray.exe not found in Core/xray folder.')
                self.set_status('Scan aborted: xray.exe missing')
                return
            unique_links = sorted(filtered_links)

            # Optionally drop duplicate configs (same normalized identity)
            if dedupe:
                before = len(unique_links)
                unique_links = engine.dedupe_links(unique_links, parse_link)
                removed = before - len(unique_links)
                self.log(f'Dedupe removed {removed} duplicate config(s).')

            total_links = len(unique_links)
            self.log(f'Processing {total_links} unique configs.')
            selected_method = 'xray' if 'xray' in methods else 'fast'

            # Ultra scan boosts real-test throughput.
            if ultra:
                test_workers = max(test_workers, 100)
                speed_limit = max(speed_limit, 24)

            self.scanner.set_speed_test_limit(speed_limit)
            self.log(
                f'Pipeline: precheck workers={precheck_workers}, test workers={test_workers}, '
                f'speed-test slots={speed_limit}, mode={selected_method}, '
                f'ultra={"on" if ultra else "off"}.'
            )

            # Split very large inputs into sequential batches so the pipeline
            # never holds hundreds of thousands of futures at once (which hangs
            # the app). Each batch is fully prechecked+tested before the next
            # starts; results/counters accumulate across batches. Small inputs
            # (<= 5000) stay a single batch = original behavior.
            batch_sizes = engine.chunk_plan(total_links)
            num_chunks = max(1, len(batch_sizes))
            batches = []
            _off = 0
            for _sz in batch_sizes:
                batches.append(unique_links[_off:_off + _sz])
                _off += _sz
            if num_chunks > 1:
                # Batching already bounds the load, so phase 1 keeps most of its
                # parallelism. Only a light governor against pathological worker
                # counts, plus a small timeout bump over the 0.7s default so
                # slow-connecting configs aren't missed.
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
                # `pct` is progress WITHIN the current batch (0..1). Map it onto
                # the overall bar across all batches, and keep it monotonic so it
                # never bounces backwards while precheck/test streams overlap.
                nonlocal last_pct
                overall = (chunk_index + min(pct, 1.0)) / num_chunks
                if overall > last_pct:
                    last_pct = overall
                self.set_progress(min(last_pct, 1.0))

            def _batch_label():
                return f'Batch {chunk_index + 1}/{num_chunks} · ' if num_chunks > 1 else ''

            def report_dead(link, parsed, reason, stage):
                nonlocal dead_count
                dead_count += 1
                method_label = 'tcp_precheck' if stage == 'precheck' else selected_method
                orig_remark = parsed.get('remark', 'NoRemark') if parsed else 'NoRemark'
                results.append(self._dead_result(link, reason, method_label, orig_remark))
                self.update_live_stats(fast_count, medium_count, slow_count, dead_count)

            def report_precheck(pd, total, reach):
                nonlocal reachable
                reachable = reach
                pct = (pd / total) * 0.15 if total else 0
                show_progress(pct)
                self.set_status(f'{_batch_label()}Prechecked {pd}/{total} ({reach} reachable)')

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
                self.set_status(f'{_batch_label()}Tested {td}/{max(reach, 1)} reachable configs')
                self.update_live_stats(fast_count, medium_count, slow_count, dead_count)

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
                # Phase 1 finished (or was skipped) -> phase 2 begins.
                self.set_phase('test')

            cumulative_reachable = 0
            cumulative_test_done = 0
            for chunk_index in range(num_chunks):
                if self.scan_state in ('stopping', 'stopping_save'):
                    break
                batch = batches[chunk_index]
                if not batch:
                    continue
                # Each batch is its own precheck -> test pass.
                self._skip_precheck = False
                self.set_phase('precheck')
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
                # A fully completed scan is 100% even if the final batch had zero
                # reachable configs (report_test never fires for an all-dead batch,
                # which would otherwise leave the overall bar short of full).
                self.set_progress(1.0)
                self.log(f'Precheck complete: {cumulative_reachable}/{total_links} reachable endpoints.')
                self.log(f'Testing complete: {cumulative_test_done}/{max(cumulative_reachable, 1)} reachable configs tested.')

            if self.scan_state != 'stopping':
                # Rename each result's remark + link fragment, then derive the copy
                # lists from the (renamed) results grouped by classification.
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
                self.set_status('Scan completed successfully')
            else:
                self.set_status('Scan aborted')
        except Exception as e:
            self.log(f'Scan error: {e}')
            self.set_status('Scan failed')
        finally:
            self.set_scan_buttons('normal' if self.loaded_links and self.folder_path else 'disabled')
            has_links = bool(self.fast_links or self.medium_links or self.slow_links)
            self.set_copy_buttons('normal' if has_links else 'disabled')
            self.set_control_buttons('disabled', 'disabled', 'disabled')
            self.scan_state = 'idle'
            self._skip_precheck = False
            self.set_phase('idle')

    @staticmethod
    def _csv_safe(value):
        """Neutralize spreadsheet formula-injection by prefixing risky cells with '."""
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
                # Format: link | remark   (dead entries also append the failure reason)
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
            self.clipboard_clear()
            self.clipboard_append('\n'.join(links))
            self.update()
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
