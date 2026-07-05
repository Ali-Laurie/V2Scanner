import csv
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from tkinter import filedialog, StringVar, BooleanVar, Listbox, END

import customtkinter as ctk
import re
import webbrowser
import sys

from .parser import extract_links, resolve_source, parse_link
from .scanner import Scanner
from . import engine


ctk.set_appearance_mode('dark')
ctk.set_default_color_theme('blue')


class ConfigScannerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title('ScanV2Ray')
        self.geometry('840x900')
        self.minsize(820, 820)

        self.folder_path = None
        self.loaded_links = set()
        self.link_protocols = {}
        self.fast_links = []
        self.normal_links = []
        self.active_links = []
        self.scan_state = 'idle'
        self.pause_cond = threading.Condition()
        self.log_lock = threading.Lock()
        self.log_queue = []
        self.log_scheduled = False
        self.log_filepath = None
        self.advanced_visible = False

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

        self._build_ui()
        # Load About.md info for Donate popup
        try:
            self.about_info = self._load_about_info()
        except Exception:
            self.about_info = {}

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self.header_frame = ctk.CTkFrame(self, fg_color='transparent')
        self.header_frame.grid(row=0, column=0, padx=24, pady=(18, 8), sticky='ew')
        self.header_frame.grid_columnconfigure(0, weight=1)

        self.header = ctk.CTkLabel(
            self.header_frame,
            text='ScanV2Ray',
            font=ctk.CTkFont(size=28, weight='bold')
        )
        self.header.grid(row=0, column=0, sticky='w')
        # Donate button
        self.header_frame.grid_columnconfigure(1, weight=0)
        self.donate_btn = ctk.CTkButton(self.header_frame, text='Donate', command=self.open_donate_popup, fg_color='#b7791f')
        self.donate_btn.grid(row=0, column=1, sticky='e')

        self.subtitle = ctk.CTkLabel(
            self.header_frame,
            text='Import proxy configs, scan them with Xray, and export the working results.',
            text_color='#aab2bd',
            font=ctk.CTkFont(size=13)
        )
        self.subtitle.grid(row=1, column=0, sticky='w', pady=(2, 0))

        self.main_frame = ctk.CTkFrame(self, fg_color='transparent')
        self.main_frame.grid(row=1, column=0, padx=24, pady=8, sticky='nsew')
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_columnconfigure(1, weight=1)

        self._build_sources_card()
        self._build_setup_card()
        self._build_progress_card()
        self._build_results_card()

        self.log_frame = ctk.CTkFrame(self)
        self.log_frame.grid(row=2, column=0, padx=24, pady=(4, 18), sticky='nsew')
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_frame.grid_rowconfigure(1, weight=1)

        self.log_label = ctk.CTkLabel(self.log_frame, text='Activity log', font=ctk.CTkFont(size=14, weight='bold'))
        self.log_label.grid(row=0, column=0, padx=14, pady=(12, 4), sticky='w')

        self.box = ctk.CTkTextbox(self.log_frame, height=180, wrap='word')
        self.box.grid(row=1, column=0, padx=14, pady=(0, 14), sticky='nsew')

    def _build_sources_card(self):
        self.source_frame = ctk.CTkFrame(self.main_frame)
        self.source_frame.grid(row=0, column=0, padx=(0, 8), pady=(0, 12), sticky='nsew')
        self.source_frame.grid_columnconfigure(0, weight=1)

        self.source_title = ctk.CTkLabel(self.source_frame, text='Sources', font=ctk.CTkFont(size=15, weight='bold'))
        self.source_title.grid(row=0, column=0, padx=14, pady=(12, 2), sticky='w')

        self.source_hint = ctk.CTkLabel(
            self.source_frame,
            text='Paste links, subscription URLs, base64 text, JSON, or local file paths.',
            text_color='#aab2bd',
            wraplength=360,
            justify='left'
        )
        self.source_hint.grid(row=1, column=0, padx=14, pady=(0, 8), sticky='w')

        self.source_textbox = ctk.CTkTextbox(self.source_frame, height=110, wrap='word')
        self.source_textbox.grid(row=2, column=0, padx=14, pady=(0, 8), sticky='ew')

        # Visible list of loaded sources (so user can see and remove selections)
        self.sources_listbox = Listbox(self.source_frame, height=6, selectmode='extended')
        self.sources_listbox.grid(row=3, column=0, padx=14, pady=(0, 8), sticky='ew')

        self.source_actions = ctk.CTkFrame(self.source_frame, fg_color='transparent')
        self.source_actions.grid(row=4, column=0, padx=9, pady=(0, 8), sticky='ew')
        self.source_actions.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.add_links_btn = ctk.CTkButton(self.source_actions, text='Add pasted sources', command=self.add_manual_sources)
        self.add_links_btn.grid(row=0, column=0, padx=5, sticky='ew')

        self.add_files_btn = ctk.CTkButton(self.source_actions, text='Add files', command=self.add_files)
        self.add_files_btn.grid(row=0, column=1, padx=5, sticky='ew')

        self.remove_selected_btn = ctk.CTkButton(
            self.source_actions,
            text='Remove selected',
            command=self.remove_selected_sources,
            fg_color='#c53030',
            hover_color='#9b2c2c'
        )
        self.remove_selected_btn.grid(row=0, column=2, padx=5, sticky='ew')

        self.clear_sources_btn = ctk.CTkButton(
            self.source_actions,
            text='Clear',
            command=self.clear_sources,
            fg_color='#3b4252',
            hover_color='#4c566a'
        )
        self.clear_sources_btn.grid(row=0, column=3, padx=5, sticky='ew')

        # Protocol filters and counts
        self.protocols = ['vmess', 'vless', 'ss', 'trojan']
        self.protocol_vars = {p: StringVar(value='1') for p in self.protocols}
        self.protocol_count_labels = {}

        self.protocols_frame = ctk.CTkFrame(self.source_frame, fg_color='transparent')
        self.protocols_frame.grid(row=5, column=0, padx=14, pady=(6, 6), sticky='ew')
        self.protocols_frame.grid_columnconfigure(tuple(range(len(self.protocols))), weight=1)

        for i, proto in enumerate(self.protocols):
            chk = ctk.CTkCheckBox(self.protocols_frame, text=proto.upper(), variable=self.protocol_vars[proto], onvalue='1', offvalue='0', command=self.update_link_count)
            chk.grid(row=0, column=i, sticky='w')
            lbl = ctk.CTkLabel(self.protocols_frame, text='0', text_color='#aab2bd')
            lbl.grid(row=1, column=i, sticky='w', pady=(4, 0))
            self.protocol_count_labels[proto] = lbl

        self.link_count_label = ctk.CTkLabel(
            self.source_frame,
            text='0 configs loaded',
            font=ctk.CTkFont(size=13, weight='bold')
        )
        self.link_count_label.grid(row=6, column=0, padx=14, pady=(0, 12), sticky='w')

    def _build_setup_card(self):
        self.setup_frame = ctk.CTkFrame(self.main_frame)
        self.setup_frame.grid(row=0, column=1, padx=(8, 0), pady=(0, 12), sticky='nsew')
        self.setup_frame.grid_columnconfigure(0, weight=1)

        self.setup_title = ctk.CTkLabel(self.setup_frame, text='Scan setup', font=ctk.CTkFont(size=15, weight='bold'))
        self.setup_title.grid(row=0, column=0, padx=14, pady=(12, 2), sticky='w')

        self.mode_label = ctk.CTkLabel(self.setup_frame, text='Scan mode', text_color='#aab2bd')
        self.mode_label.grid(row=1, column=0, padx=14, pady=(8, 4), sticky='w')

        self.mode_selector = ctk.CTkSegmentedButton(
            self.setup_frame,
            values=['Quick', 'Full'],
            variable=self.scan_mode_var,
            command=lambda _value: self.update_link_count()
        )
        self.mode_selector.grid(row=2, column=0, padx=14, pady=(0, 12), sticky='ew')
        self.mode_selector.set('Quick')

        self.ultra_switch = ctk.CTkSwitch(
            self.setup_frame,
            text='⚡ Ultra Scan (faster real-test • more CPU/network)',
            variable=self.ultra_scan_var,
            onvalue=True, offvalue=False
        )
        self.ultra_switch.grid(row=3, column=0, padx=14, pady=(0, 12), sticky='w')

        self.select_button = ctk.CTkButton(
            self.setup_frame,
            text='Choose output folder',
            command=self.select_folder,
            font=ctk.CTkFont(weight='bold')
        )
        self.select_button.grid(row=4, column=0, padx=14, pady=(0, 8), sticky='ew')

        self.folder_label = ctk.CTkLabel(
            self.setup_frame,
            text='No output folder selected',
            text_color='#aab2bd',
            wraplength=360,
            justify='left'
        )
        self.folder_label.grid(row=5, column=0, padx=14, pady=(0, 12), sticky='w')

        self.start_button = ctk.CTkButton(
            self.setup_frame,
            text='Start scan',
            command=self.start_scan,
            state='disabled',
            height=40,
            font=ctk.CTkFont(size=14, weight='bold')
        )
        self.start_button.grid(row=6, column=0, padx=14, pady=(0, 10), sticky='ew')

        self.advanced_button = ctk.CTkButton(
            self.setup_frame,
            text='Show advanced settings',
            command=self.toggle_advanced_settings,
            fg_color='#3b4252',
            hover_color='#4c566a'
        )
        self.advanced_button.grid(row=7, column=0, padx=14, pady=(0, 10), sticky='ew')

        self.advanced_frame = ctk.CTkFrame(self.setup_frame, fg_color='#232936')
        self.advanced_frame.grid_columnconfigure((0, 1), weight=1)

        self.threads_label = ctk.CTkLabel(self.advanced_frame, text='Concurrency')
        self.threads_label.grid(row=0, column=0, padx=10, pady=(10, 4), sticky='w')
        self.threads_entry = ctk.CTkEntry(self.advanced_frame)
        self.threads_entry.insert(0, '40')
        self.threads_entry.grid(row=1, column=0, padx=10, pady=(0, 10), sticky='ew')

        self.timeout_label = ctk.CTkLabel(self.advanced_frame, text='Timeout (ms)')
        self.timeout_label.grid(row=0, column=1, padx=10, pady=(10, 4), sticky='w')
        self.timeout_entry = ctk.CTkEntry(self.advanced_frame)
        self.timeout_entry.insert(0, '3000')
        self.timeout_entry.grid(row=1, column=1, padx=10, pady=(0, 10), sticky='ew')

        # Remark: optional override for all config remarks
        self.remarker_label = ctk.CTkLabel(self.advanced_frame, text='Remark (optional)')
        self.remarker_label.grid(row=2, column=0, padx=10, pady=(6, 4), sticky='w')
        self.remarker_entry = ctk.CTkEntry(self.advanced_frame, textvariable=self.remarker_var)
        self.remarker_entry.insert(0, '')
        self.remarker_entry.grid(row=3, column=0, columnspan=2, padx=10, pady=(0, 10), sticky='ew')

    def _build_progress_card(self):
        self.progress_frame = ctk.CTkFrame(self.main_frame)
        self.progress_frame.grid(row=1, column=0, columnspan=2, pady=(0, 12), sticky='ew')
        self.progress_frame.grid_columnconfigure(0, weight=1)

        self.status = ctk.CTkLabel(self.progress_frame, text='Ready', font=ctk.CTkFont(size=13, weight='bold'))
        self.status.grid(row=0, column=0, padx=14, pady=(12, 4), sticky='w')

        self.progress_bar = ctk.CTkProgressBar(self.progress_frame)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=1, column=0, padx=14, pady=(0, 12), sticky='ew')

        self.controls_frame = ctk.CTkFrame(self.progress_frame, fg_color='transparent')
        self.controls_frame.grid(row=2, column=0, padx=9, pady=(0, 12), sticky='ew')
        self.controls_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self.pause_button = ctk.CTkButton(
            self.controls_frame,
            text='Pause',
            command=self.toggle_pause,
            state='disabled',
            fg_color='#b7791f',
            hover_color='#975a16'
        )
        self.pause_button.grid(row=0, column=0, padx=5, sticky='ew')

        self.stop_save_button = ctk.CTkButton(
            self.controls_frame,
            text='Stop and save',
            command=self.stop_and_save,
            state='disabled',
            fg_color='#2b6cb0',
            hover_color='#2c5282'
        )
        self.stop_save_button.grid(row=0, column=1, padx=5, sticky='ew')

        self.stop_button = ctk.CTkButton(
            self.controls_frame,
            text='Stop',
            command=self.stop_scan_now,
            state='disabled',
            fg_color='#c53030',
            hover_color='#9b2c2c'
        )
        self.stop_button.grid(row=0, column=2, padx=5, sticky='ew')

    def _build_results_card(self):
        self.results_frame = ctk.CTkFrame(self.main_frame)
        self.results_frame.grid(row=2, column=0, columnspan=2, sticky='ew')
        self.results_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        stat_specs = [
            ('fast_label', 'Fast', '#48bb78'),
            ('medium_label', 'Medium', '#ecc94b'),
            ('slow_label', 'Slow', '#9f7aea'),
            ('dead_label', 'Dead', '#f56565'),
        ]
        for column, (attr, label, color) in enumerate(stat_specs):
            stat = ctk.CTkLabel(
                self.results_frame,
                text=f'{label}: 0',
                text_color=color,
                font=ctk.CTkFont(size=14, weight='bold')
            )
            stat.grid(row=0, column=column, padx=12, pady=(12, 8), sticky='ew')
            setattr(self, attr, stat)

        self.copy_fast_btn = ctk.CTkButton(self.results_frame, text='Copy fast', command=self.copy_fast, state='disabled')
        self.copy_fast_btn.grid(row=1, column=0, padx=(14, 5), pady=(0, 14), sticky='ew')

        self.copy_normal_btn = ctk.CTkButton(self.results_frame, text='Copy normal', command=self.copy_normal, state='disabled')
        self.copy_normal_btn.grid(row=1, column=1, padx=5, pady=(0, 14), sticky='ew')

        self.copy_all_btn = ctk.CTkButton(self.results_frame, text='Copy active', command=self.copy_all_active, state='disabled')
        self.copy_all_btn.grid(row=1, column=2, padx=5, pady=(0, 14), sticky='ew')

        self.export_button = ctk.CTkButton(
            self.results_frame,
            text='Export TXT',
            command=self.export_active_links,
            state='disabled',
            fg_color='#3b4252',
            hover_color='#4c566a'
        )
        self.export_button.grid(row=1, column=3, padx=(5, 14), pady=(0, 14), sticky='ew')

    def _load_about_info(self):
        """Read About.md and extract wallet addresses and social links."""
        # Support running from source and from a PyInstaller bundle
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_dir = getattr(sys, '_MEIPASS', None) or script_dir
        # try several candidate locations for About.md
        candidates = [
            os.path.join(base_dir, 'About.md'),
            os.path.join(base_dir, '..', 'About.md'),
            os.path.join(script_dir, '..', 'About.md'),
        ]
        about_path = None
        for c in candidates:
            c = os.path.abspath(c)
            if os.path.exists(c):
                about_path = c
                break
        info = {'wallets': {}, 'links': {}}
        if not about_path:
            return info

        with open(about_path, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()

        # find BTC and TRX addresses (simple key:value patterns)
        for key in ('BTC', 'TRX'):
            m = re.search(rf"{key}\s*[:\-]\s*([A-Za-z0-9]+)", text)
            if m:
                info['wallets'][key] = m.group(1).strip()

        # fallback: look for long alphanumeric addresses after labels
        # extract any URLs
        urls = re.findall(r'(https?://\S+)', text)
        for u in urls:
            if 't.me' in u:
                info['links']['telegram'] = u
            elif 'instagram' in u or 'instagr' in u:
                info['links']['instagram'] = u
            elif 'github' in u:
                info['links']['github'] = u

        # also try to find Telegram mentions like 'Telegram Chanel: https://t.me/...' or 'Telegram Group : https://t.me/...'
        # If not found in urls, try simple regex patterns
        if 'telegram' not in info['links']:
            m = re.search(r'Telegram[^:\n]*[:\-]\s*(https?://t\.me/\S+)', text, re.IGNORECASE)
            if m:
                info['links']['telegram'] = m.group(1).strip()
        if 'instagram' not in info['links']:
            m = re.search(r'instagram[^:\n]*[:\-]\s*(https?://\S+)', text, re.IGNORECASE)
            if m:
                info['links']['instagram'] = m.group(1).strip()
        if 'github' not in info['links']:
            m = re.search(r'github[^:\n]*[:\-]\s*(https?://\S+)', text, re.IGNORECASE)
            if m:
                info['links']['github'] = m.group(1).strip()

        return info

    def open_donate_popup(self):
        # Create a simple popup showing wallets and social links with copy/open actions
        popup = ctk.CTkToplevel(self)
        popup.title('Donate')
        popup.geometry('420x260')

        wallets = self.about_info.get('wallets', {})
        links = self.about_info.get('links', {})

        row = 0
        lbl = ctk.CTkLabel(popup, text='Support the project — donate any amount', font=ctk.CTkFont(size=14, weight='bold'))
        lbl.grid(row=row, column=0, columnspan=3, padx=14, pady=(12, 8), sticky='w')
        row += 1

        if wallets:
            for key, addr in wallets.items():
                k_lbl = ctk.CTkLabel(popup, text=f'{key}:', width=60)
                k_lbl.grid(row=row, column=0, padx=10, pady=6, sticky='w')
                a_lbl = ctk.CTkLabel(popup, text=addr, text_color='#aab2bd')
                a_lbl.grid(row=row, column=1, padx=6, pady=6, sticky='w')
                copy_btn = ctk.CTkButton(popup, text='Copy', width=60, command=lambda a=addr: (self.clipboard_clear(), self.clipboard_append(a)))
                copy_btn.grid(row=row, column=2, padx=10, pady=6)
                row += 1
        else:
            no_lbl = ctk.CTkLabel(popup, text='No wallet info found in About.md', text_color='#aab2bd')
            no_lbl.grid(row=row, column=0, columnspan=3, padx=14, pady=6, sticky='w')
            row += 1

        # Social links
        if links:
            sep = ctk.CTkLabel(popup, text='')
            sep.grid(row=row, column=0, pady=(6, 0))
            row += 1
            for name, url in links.items():
                n_lbl = ctk.CTkLabel(popup, text=f'{name.capitalize()}:')
                n_lbl.grid(row=row, column=0, padx=10, pady=4, sticky='w')
                u_lbl = ctk.CTkLabel(popup, text=url, text_color='#63b3ed')
                u_lbl.grid(row=row, column=1, padx=6, pady=4, sticky='w')
                open_btn = ctk.CTkButton(popup, text='Open', width=60, command=lambda u=url: webbrowser.open(u))
                open_btn.grid(row=row, column=2, padx=10, pady=4)
                row += 1

        close_btn = ctk.CTkButton(popup, text='Close', command=popup.destroy, fg_color='#3b4252')
        close_btn.grid(row=row, column=0, columnspan=3, padx=14, pady=(12, 12), sticky='ew')


    def toggle_advanced_settings(self):
        if self.advanced_visible:
            self.advanced_frame.grid_forget()
            self.advanced_button.configure(text='Show advanced settings')
        else:
            self.advanced_frame.grid(row=8, column=0, padx=14, pady=(0, 14), sticky='ew')
            self.advanced_button.configure(text='Hide advanced settings')
        self.advanced_visible = not self.advanced_visible

    def log(self, text):
        with self.log_lock:
            self.log_queue.append(text)
            if not self.log_scheduled:
                self.log_scheduled = True
                self.after(10, self._process_log_queue)

    def _process_log_queue(self):
        with self.log_lock:
            lines = list(self.log_queue)
            self.log_queue.clear()
            self.log_scheduled = False

        for line in lines:
            self.box.insert('end', line + '\n')
        self.box.see('end')

        # Persist log lines to scan_log.txt (thread-safe via log_lock)
        if self.log_filepath and lines:
            try:
                with self.log_lock:
                    with open(self.log_filepath, 'a', encoding='utf-8') as f:
                        for line in lines:
                            f.write(line + '\n')
            except Exception:
                pass

    def set_status(self, text):
        self.after(0, lambda: self.status.configure(text=text))

    def set_progress(self, value):
        self.after(0, lambda: self.progress_bar.set(value))

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
            for button in (self.copy_fast_btn, self.copy_normal_btn, self.copy_all_btn, self.export_button)
        ])

    def update_live_stats(self, fast, medium, slow, dead):
        self.after(0, lambda: self._update_live_stats(fast, medium, slow, dead))

    def _update_live_stats(self, fast, medium, slow, dead):
        self.fast_label.configure(text=f'Fast: {fast}')
        self.medium_label.configure(text=f'Medium: {medium}')
        self.slow_label.configure(text=f'Slow: {slow}')
        self.dead_label.configure(text=f'Dead: {dead}')

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

            # Skip unsupported/excluded protocols like hysteria
            if proto in ('hysteria', 'hysteria2'):
                self.log(f'Skipped unsupported protocol: {proto} for {link}')
                continue

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
            self.folder_label.configure(text=display_path)
            self.set_status(f'Output folder selected: {self.folder_path}')
            self.update_link_count()

    def toggle_pause(self):
        if self.scan_state == 'running':
            self.scan_state = 'paused'
            self.pause_button.configure(text='Resume', fg_color='#38a169', hover_color='#2f855a')
            self.log('Scan paused.')
            self.set_status('Scan paused')
        elif self.scan_state == 'paused':
            self.scan_state = 'running'
            self.pause_button.configure(text='Pause', fg_color='#b7791f', hover_color='#975a16')
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
            'reason': reason
        }

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
        self.normal_links = []
        self.active_links = []
        self.update_live_stats(0, 0, 0, 0)
        self.scan_state = 'running'
        self.pause_button.configure(text='Pause', fg_color='#b7791f', hover_color='#975a16')
        self.set_control_buttons('normal', 'normal', 'normal')

        # Read GUI inputs on main thread to avoid tkinter access from worker threads
        try:
            max_workers = int(self.threads_entry.get().strip())
            if max_workers <= 0:
                raise ValueError
        except Exception:
            max_workers = 40
            self.log('Invalid thread count. Using 40.')

        try:
            timeout_ms = float(self.timeout_entry.get().strip())
            if timeout_ms <= 0:
                raise ValueError
            timeout = timeout_ms / 1000.0
        except Exception:
            timeout = 3.0
            self.log('Invalid timeout. Using 3000ms.')

        # Read the Remark override on the main thread (Tk access is not thread-safe)
        try:
            remark_override = self.remarker_var.get().strip()
        except Exception as e:
            remark_override = ''
            self.log(f'Error reading Remark field: {e}')

        # Read the Ultra Scan flag on the main thread (Tk access is not thread-safe)
        try:
            ultra_scan = bool(self.ultra_scan_var.get())
        except Exception as e:
            ultra_scan = False
            self.log(f'Error reading Ultra Scan flag: {e}')

        threading.Thread(target=self.run_scan, args=(methods, filtered_links, max_workers, timeout), kwargs={'remark_override': remark_override, 'ultra': ultra_scan}, daemon=True).start()

    def run_scan(self, methods, filtered_links, max_workers=None, timeout=3.0, remark_override=None, ultra=False):
        try:
            # Ensure defaults if not provided
            if not max_workers:
                max_workers = 40
            if not timeout:
                timeout = 3.0

            # Reset any prior abort flag before starting fresh work
            self.scanner.reset_abort()

            if methods and not os.path.exists(self.scanner.xray_path):
                self.log('xray.exe not found in Core/xray folder.')
                self.set_status('Scan aborted: xray.exe missing')
                return
            unique_links = sorted(filtered_links)
            total_links = len(unique_links)
            self.log(f'Processing {total_links} unique configs.')
            selected_method = 'xray' if 'xray' in methods else 'fast'
            precheck_workers = min(max_workers * 4, 200)
            if ultra:
                test_workers = min(max_workers, 100)
                speed_limit = min(test_workers, 24)
            else:
                test_workers = min(max_workers, 16)
                speed_limit = min(test_workers, 6)
            self.scanner.set_speed_test_limit(speed_limit)
            self.log(
                f'Pipeline: precheck workers={precheck_workers}, test workers={test_workers}, '
                f'speed-test slots={speed_limit}, mode={selected_method}, '
                f'ultra={"on" if ultra else "off"}.'
            )

            results = []
            pre_done = 0
            reachable = 0
            test_done = 0
            fast_count = 0
            medium_count = 0
            slow_count = 0
            dead_count = 0
            active_links = set()
            fast_links_set = set()
            normal_links_set = set()
            last_pct = 0.0

            def show_progress(pct):
                # Precheck and test phases overlap while streaming, so keep the
                # bar monotonic to avoid it bouncing backwards.
                nonlocal last_pct
                if pct > last_pct:
                    last_pct = pct
                self.set_progress(min(last_pct, 1.0))

            def report_dead(link, parsed, reason, stage):
                nonlocal dead_count
                dead_count += 1
                method_label = 'tcp_precheck' if stage == 'precheck' else selected_method
                orig_remark = parsed.get('remark', 'NoRemark') if parsed else 'NoRemark'
                results.append(self._dead_result(link, reason, method_label, orig_remark))
                self.update_live_stats(fast_count, medium_count, slow_count, dead_count)

            def report_precheck(pd, total, reach):
                nonlocal pre_done, reachable
                pre_done = pd
                reachable = reach
                pct = (pd / total) * 0.15 if total else 0
                show_progress(pct)
                self.set_status(f'Prechecked {pd}/{total} ({reach} reachable)')

            def report_test(item, result, td, reach):
                nonlocal test_done, reachable, fast_count, medium_count, slow_count, dead_count
                test_done = td
                reachable = reach
                if result:
                    results.append(result)
                    link = item.get('link', '') if item else result.get('link', '')
                    classification = result.get('classification', 'dead')
                    if classification == 'fast':
                        fast_count += 1
                        fast_links_set.add(link)
                    elif classification == 'medium':
                        medium_count += 1
                        normal_links_set.add(link)
                    elif classification == 'slow':
                        slow_count += 1
                        normal_links_set.add(link)
                    else:
                        dead_count += 1
                    active_links.add(link)
                pct = 0.15 + (td / max(reach, 1)) * 0.85
                show_progress(pct)
                self.set_status(f'Tested {td}/{max(reach, 1)} reachable configs')
                self.update_live_stats(fast_count, medium_count, slow_count, dead_count)

            def should_stop():
                return self.scan_state in ('stopping', 'stopping_save')

            def wait_if_paused():
                while self.scan_state == 'paused':
                    with self.pause_cond:
                        if self.scan_state == 'paused':
                            self.pause_cond.wait(timeout=0.2)

            engine.run_pipeline(
                self.scanner, unique_links,
                method=selected_method, timeout=timeout,
                precheck_workers=precheck_workers, test_workers=test_workers,
                should_stop=should_stop, wait_if_paused=wait_if_paused,
                report_precheck=report_precheck, report_dead=report_dead,
                report_test=report_test,
            )

            if self.scan_state not in ('stopping', 'stopping_save'):
                self.log(f'Precheck complete: {reachable}/{total_links} reachable endpoints.')
                self.log(f'Testing complete: {test_done}/{max(reachable, 1)} reachable configs tested.')

            if self.scan_state != 'stopping':
                self.fast_links = sorted(fast_links_set)
                self.normal_links = sorted(normal_links_set)
                self.active_links = sorted(active_links)
                
                # Apply Remark override if provided before saving
                rem = (remark_override or '').strip()

                if not rem:
                    self.log('No Remark override provided. Using original remarks.')
                else:
                    self.log(f'Applying Remark override: "{rem}" to all {len(results)} results.')
                    if results:
                        for item in results:
                            item['remark'] = rem
                    else:
                        self.log('No results to apply Remark override to.')
                
                self.save_results(results)
                self.log('')
                self.log('Scan complete.')
                self.log(f'Working configs: {len(active_links)} (fast: {len(fast_links_set)}, normal: {len(normal_links_set)}).')
                self.set_status('Scan completed successfully')
            else:
                self.set_status('Scan aborted')
        except Exception as e:
            self.log(f'Scan error: {e}')
            self.set_status('Scan failed')
        finally:
            self.set_scan_buttons('normal' if self.loaded_links and self.folder_path else 'disabled')
            self.set_copy_buttons('normal' if self.fast_links or self.normal_links else 'disabled')
            self.set_control_buttons('disabled', 'disabled', 'disabled')
            self.scan_state = 'idle'

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
                    'success_ratio', 'average_latency_ms', 'score', 'classification', 'reason'
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

    def export_active_links(self):
        active = sorted(set(self.fast_links + self.normal_links))
        if not active:
            self.log('No active configs are available to export.')
            return
        
        # Ask user for export file location
        file_path = filedialog.asksaveasfilename(
            defaultextension='.txt',
            filetypes=[('Text files', '*.txt'), ('All files', '*.*')],
            initialfile='active_configs.txt'
        )
        
        if not file_path:
            self.log('Export cancelled.')
            return
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                # Export only the links (standard format for Xray configs)
                f.write('\n'.join(active))
            self.log(f'Exported {len(active)} active configs to {os.path.basename(file_path)}.')
        except Exception as e:
            self.log(f'Error exporting configs: {e}')

    def copy_fast(self):
        if self.fast_links:
            self.clipboard_clear()
            self.clipboard_append('\n'.join(self.fast_links))
            self.update()
            self.log('Fast configs copied.')
        else:
            self.log('No fast configs are available to copy.')

    def copy_normal(self):
        if self.normal_links:
            self.clipboard_clear()
            self.clipboard_append('\n'.join(self.normal_links))
            self.update()
            self.log('Normal configs copied.')
        else:
            self.log('No normal configs are available to copy.')

    def copy_all_active(self):
        all_links = sorted(set(self.fast_links + self.normal_links))
        if all_links:
            self.clipboard_clear()
            self.clipboard_append('\n'.join(all_links))
            self.update()
            self.log('All active configs copied.')
        else:
            self.log('No active configs are available to copy.')
