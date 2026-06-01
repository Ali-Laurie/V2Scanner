import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from tkinter import filedialog, StringVar

import customtkinter as ctk

from .parser import extract_links, resolve_source
from .scanner import Scanner


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
        self.fast_links = []
        self.normal_links = []
        self.active_links = []
        self.scan_state = 'idle'
        self.pause_cond = threading.Condition()
        self.log_lock = threading.Lock()
        self.log_queue = []
        self.log_scheduled = False
        self.advanced_visible = False

        script_dir = os.path.dirname(os.path.abspath(__file__))
        xray_path = os.path.join(script_dir, '..', 'Core', 'xray', 'xray.exe')
        singbox_path = os.path.join(script_dir, '..', 'Core', 'sing_box', 'sing-box.exe')
        self.scanner = Scanner(xray_path, singbox_path)

        self.scan_mode_var = StringVar(value='Fast')

        self._build_ui()

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

        self.source_textbox = ctk.CTkTextbox(self.source_frame, height=150, wrap='word')
        self.source_textbox.grid(row=2, column=0, padx=14, pady=(0, 10), sticky='ew')

        self.source_actions = ctk.CTkFrame(self.source_frame, fg_color='transparent')
        self.source_actions.grid(row=3, column=0, padx=9, pady=(0, 8), sticky='ew')
        self.source_actions.grid_columnconfigure((0, 1, 2), weight=1)

        self.add_links_btn = ctk.CTkButton(self.source_actions, text='Add pasted sources', command=self.add_manual_sources)
        self.add_links_btn.grid(row=0, column=0, padx=5, sticky='ew')

        self.add_files_btn = ctk.CTkButton(self.source_actions, text='Add files', command=self.add_files)
        self.add_files_btn.grid(row=0, column=1, padx=5, sticky='ew')

        self.clear_sources_btn = ctk.CTkButton(
            self.source_actions,
            text='Clear',
            command=self.clear_sources,
            fg_color='#3b4252',
            hover_color='#4c566a'
        )
        self.clear_sources_btn.grid(row=0, column=2, padx=5, sticky='ew')

        self.link_count_label = ctk.CTkLabel(
            self.source_frame,
            text='0 configs loaded',
            font=ctk.CTkFont(size=13, weight='bold')
        )
        self.link_count_label.grid(row=4, column=0, padx=14, pady=(0, 12), sticky='w')

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

        self.select_button = ctk.CTkButton(
            self.setup_frame,
            text='Choose output folder',
            command=self.select_folder,
            font=ctk.CTkFont(weight='bold')
        )
        self.select_button.grid(row=3, column=0, padx=14, pady=(0, 8), sticky='ew')

        self.folder_label = ctk.CTkLabel(
            self.setup_frame,
            text='No output folder selected',
            text_color='#aab2bd',
            wraplength=360,
            justify='left'
        )
        self.folder_label.grid(row=4, column=0, padx=14, pady=(0, 12), sticky='w')

        self.start_button = ctk.CTkButton(
            self.setup_frame,
            text='Start scan',
            command=self.start_scan,
            state='disabled',
            height=40,
            font=ctk.CTkFont(size=14, weight='bold')
        )
        self.start_button.grid(row=5, column=0, padx=14, pady=(0, 10), sticky='ew')

        self.advanced_button = ctk.CTkButton(
            self.setup_frame,
            text='Show advanced settings',
            command=self.toggle_advanced_settings,
            fg_color='#3b4252',
            hover_color='#4c566a'
        )
        self.advanced_button.grid(row=6, column=0, padx=14, pady=(0, 10), sticky='ew')

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

    def toggle_advanced_settings(self):
        if self.advanced_visible:
            self.advanced_frame.grid_forget()
            self.advanced_button.configure(text='Show advanced settings')
        else:
            self.advanced_frame.grid(row=7, column=0, padx=14, pady=(0, 14), sticky='ew')
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
        self.after(0, lambda: self.link_count_label.configure(text=f'{len(self.loaded_links)} configs loaded'))
        ready_to_scan = bool(self.loaded_links and self.folder_path and self._selected_methods())
        self.set_scan_buttons('normal' if ready_to_scan else 'disabled')

    def _selected_methods(self):
        return ['xray'] if self.scan_mode_var.get() == 'Full' else ['fast']

    def _add_links(self, links):
        added_links = 0
        for link in links:
            if link not in self.loaded_links:
                self.loaded_links.add(link)
                added_links += 1
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

    def _dead_result(self, link, reason, method='xray_validation'):
        return {
            'method': method,
            'proto': '',
            'link': link,
            'remark': reason,
            'latency': 0,
            'speed': 0.0,
            'success_ratio': 0.0,
            'average_latency': '',
            'score': 0.0,
            'classification': 'dead'
        }

    def start_scan(self):
        if not self.loaded_links:
            self.log('No configs loaded for scanning.')
            return
        if not self.folder_path:
            self.log('Choose an output folder before starting the scan.')
            return
        methods = self._selected_methods()
        if not methods:
            self.log('Select a scan mode before starting.')
            return

        self.box.delete('1.0', 'end')
        if self.folder_path:
            log_dir = os.path.join(self.folder_path, 'Scan_Results')
            os.makedirs(log_dir, exist_ok=True)
            log_filepath = os.path.join(log_dir, 'scan_log.txt')
            with open(log_filepath, 'w', encoding='utf-8') as f:
                f.write(f'=== ScanV2Ray LOG STARTED AT {time.strftime("%Y-%m-%d %H:%M:%S")} ===\n')

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

        threading.Thread(target=self.run_scan, args=(methods,), daemon=True).start()

    def run_scan(self, methods):
        try:
            try:
                max_workers = int(self.threads_entry.get().strip())
                if max_workers <= 0:
                    raise ValueError
            except ValueError:
                max_workers = 40
                self.log('Invalid thread count. Using 40.')

            try:
                timeout_ms = float(self.timeout_entry.get().strip())
                if timeout_ms <= 0:
                    raise ValueError
                timeout = timeout_ms / 1000.0
            except ValueError:
                timeout = 3.0
                self.log('Invalid timeout. Using 3000ms.')

            if methods and not os.path.exists(self.scanner.xray_path):
                self.log('xray.exe not found in Core/xray folder.')
                self.set_status('Scan aborted: xray.exe missing')
                return
            unique_links = sorted(self.loaded_links)
            total_links = len(unique_links)
            self.log(f'Processing {total_links} unique configs.')
            selected_method = 'xray' if 'xray' in methods else 'fast'
            precheck_workers = min(max_workers * 4, 200)
            validation_workers = min(max_workers, 80)
            real_workers = min(max_workers, 12)
            self.scanner.set_speed_test_limit(min(real_workers, 6))
            self.log(
                f'Pipeline: precheck workers={precheck_workers}, validation workers={validation_workers}, '
                f'real-test workers={real_workers}, mode={selected_method}.'
            )

            results = []
            prechecked_items = []
            prepared_items = []
            precheck_done = 0
            validation_done = 0
            real_done = 0
            fast_count = 0
            medium_count = 0
            slow_count = 0
            dead_count = 0
            active_links = set()
            fast_links_set = set()
            normal_links_set = set()

            with ThreadPoolExecutor(max_workers=precheck_workers) as executor:
                futures = {executor.submit(self.scanner.precheck_link, link): link for link in unique_links}
                for future in as_completed(futures):
                    if self.scan_state == 'stopping':
                        self.log('Scan aborted by user. Results discarded.')
                        break
                    elif self.scan_state == 'stopping_save':
                        self.log('Scan stopped by user. Saving completed results.')
                        break

                    while self.scan_state == 'paused':
                        time.sleep(0.2)

                    precheck_done += 1
                    link = futures[future]
                    try:
                        prechecked = future.result()
                    except Exception as e:
                        prechecked = {'ok': False, 'link': link, 'reason': f'precheck_exception: {e}'}

                    if prechecked.get('ok'):
                        prechecked_items.append(prechecked)
                    else:
                        dead_count += 1
                        results.append(self._dead_result(link, prechecked.get('reason', 'tcp_precheck_failed'), 'tcp_precheck'))

                    pct = (precheck_done / total_links) * 0.15 if total_links else 0
                    self.set_progress(pct)
                    self.set_status(f'Prechecked {precheck_done}/{total_links} ({len(prechecked_items)} reachable)')
                    self.update_live_stats(fast_count, medium_count, slow_count, dead_count)

            if self.scan_state not in ('stopping', 'stopping_save'):
                self.log(f'Precheck complete: {len(prechecked_items)}/{total_links} reachable endpoints.')

            validation_total = len(prechecked_items)
            if validation_total and self.scan_state not in ('stopping', 'stopping_save'):
                with ThreadPoolExecutor(max_workers=validation_workers) as executor:
                    futures = {executor.submit(self.scanner.validate_prechecked_link, item): item for item in prechecked_items}
                    for future in as_completed(futures):
                        if self.scan_state == 'stopping':
                            self.log('Scan aborted by user. Results discarded.')
                            break
                        elif self.scan_state == 'stopping_save':
                            self.log('Scan stopped by user. Saving completed results.')
                            break

                        while self.scan_state == 'paused':
                            time.sleep(0.2)

                        validation_done += 1
                        prechecked = futures[future]
                        link = prechecked['link']
                        try:
                            prepared = future.result()
                        except Exception as e:
                            prepared = {'ok': False, 'link': link, 'reason': f'validation_exception: {e}'}

                        if prepared.get('ok'):
                            prepared_items.append(prepared)
                        else:
                            dead_count += 1
                            results.append(self._dead_result(link, prepared.get('reason', 'xray_validation_failed'), 'xray_validation'))

                        pct = 0.15 + ((validation_done / validation_total) * 0.25 if validation_total else 0)
                        self.set_progress(pct)
                        self.set_status(f'Validated {validation_done}/{validation_total} ({len(prepared_items)} Xray-ready)')
                        self.update_live_stats(fast_count, medium_count, slow_count, dead_count)

            if self.scan_state not in ('stopping', 'stopping_save'):
                self.log(f'Validation complete: {len(prepared_items)}/{len(prechecked_items)} reachable configs accepted.')

            real_total = len(prepared_items)
            if real_total and self.scan_state not in ('stopping', 'stopping_save'):
                with ThreadPoolExecutor(max_workers=real_workers) as executor:
                    futures = {executor.submit(self.scanner.test_prepared_link, item, timeout, selected_method): item for item in prepared_items}
                    for future in as_completed(futures):
                        if self.scan_state == 'stopping':
                            self.log('Scan aborted by user. Results discarded.')
                            break
                        elif self.scan_state == 'stopping_save':
                            self.log('Scan stopped by user. Saving completed results.')
                            break

                        while self.scan_state == 'paused':
                            time.sleep(0.2)

                        real_done += 1
                        prepared = futures[future]
                        link = prepared['link']
                        try:
                            item = future.result()
                        except Exception as e:
                            item = None
                            results.append(self._dead_result(link, f'real_test_exception: {e}', selected_method))

                        if item:
                            results.append(item)
                            classification = item.get('classification', 'dead')
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
                        else:
                            dead_count += 1
                            if not any(result.get('link') == link and result.get('classification') == 'dead' for result in results):
                                results.append(self._dead_result(link, 'connectivity_or_speed_failed', selected_method))

                        pct = 0.40 + ((real_done / real_total) * 0.60 if real_total else 0)
                        self.set_progress(pct)
                        self.set_status(f'Tested {real_done}/{real_total} ready configs')
                        self.update_live_stats(fast_count, medium_count, slow_count, dead_count)

            if self.scan_state != 'stopping':
                self.fast_links = sorted(fast_links_set)
                self.normal_links = sorted(normal_links_set)
                self.active_links = sorted(active_links)
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
            with open(csv_path, 'w', encoding='utf-8') as f:
                f.write('method,proto,link,remark,latency_ms,speed_kbps,success_ratio,average_latency_ms,score,classification\n')
                for item in results:
                    f.write(
                        f"{item['method']},{item['proto']},\"{item['link']}\",\"{item['remark']}\"," +
                        f"{item['latency']},{item['speed']:.2f},{item['success_ratio']},{item.get('average_latency','')},{item['score']},{item['classification']}\n"
                    )
            self.log('Saved scan_results.csv')

        groups = {'fast': [], 'medium': [], 'slow': [], 'dead': []}
        for item in results:
            groups.setdefault(item['classification'], []).append(item)

        for classification, items in groups.items():
            file_base = f'{classification}_verified.txt' if classification != 'dead' else 'dead.txt'
            file_path = os.path.join(output_dir, file_base)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join([item['link'] for item in items]))
            self.log(f'Saved {file_base}')

    def export_active_links(self):
        active = sorted(set(self.fast_links + self.normal_links))
        if not active:
            self.log('No active configs are available to export.')
            return
        if not self.folder_path:
            self.log('Choose an output folder before exporting.')
            return
        output_dir = os.path.join(self.folder_path, 'Scan_Results')
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, 'active_connected_configs.txt')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(active))
        self.log(f'Exported active configs to {os.path.basename(file_path)}.')

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
