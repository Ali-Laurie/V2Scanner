import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from tkinter import filedialog, IntVar

import customtkinter as ctk

from .parser import extract_links, resolve_source
from .scanner import Scanner


ctk.set_appearance_mode('dark')
ctk.set_default_color_theme('blue')


class ConfigScannerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title('ScanV2Ray | Modular Scanner')
        self.geometry('780x980')
        self.resizable(False, False)

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

        script_dir = os.path.dirname(os.path.abspath(__file__))
        xray_path = os.path.join(script_dir, '..', 'Core', 'xray', 'xray.exe')
        singbox_path = os.path.join(script_dir, '..', 'Core', 'sing_box', 'sing-box.exe')
        self.scanner = Scanner(xray_path, singbox_path)

        self.fast_mode_var = IntVar(value=1)
        self.xray_mode_var = IntVar(value=0)
        self.singbox_mode_var = IntVar(value=0)

        self._build_ui()

    def _build_ui(self):
        self.header = ctk.CTkLabel(self, text='ScanV2Ray | Modular Scanner', font=ctk.CTkFont(size=20, weight='bold'))
        self.header.pack(pady=(15, 5))

        self.help_label = ctk.CTkLabel(
            self,
            text='1. Add links, URLs or subscription strings. 2. Choose scan methods. 3. Select a folder and start scan.',
            font=ctk.CTkFont(size=12),
            wraplength=740,
            justify='center'
        )
        self.help_label.pack(padx=20, pady=(0, 10))

        self.settings_frame = ctk.CTkFrame(self)
        self.settings_frame.pack(padx=20, pady=10, fill='x')

        self.threads_label = ctk.CTkLabel(self.settings_frame, text='Threads:', font=ctk.CTkFont(size=12))
        self.threads_label.grid(row=0, column=0, padx=10, pady=10, sticky='w')
        self.threads_entry = ctk.CTkEntry(self.settings_frame, width=70)
        self.threads_entry.insert(0, '40')
        self.threads_entry.grid(row=0, column=1, padx=5, pady=10)

        self.timeout_label = ctk.CTkLabel(self.settings_frame, text='Timeout (ms):', font=ctk.CTkFont(size=12))
        self.timeout_label.grid(row=0, column=2, padx=10, pady=10, sticky='w')
        self.timeout_entry = ctk.CTkEntry(self.settings_frame, width=70)
        self.timeout_entry.insert(0, '6000')
        self.timeout_entry.grid(row=0, column=3, padx=5, pady=10)

        self.filter_label = ctk.CTkLabel(self.settings_frame, text='File Filter:', font=ctk.CTkFont(size=12))
        self.filter_label.grid(row=0, column=4, padx=10, pady=10, sticky='w')
        self.filter_combo = ctk.CTkComboBox(self.settings_frame, values=['All .txt files', 'Only sub*.txt files'], width=170)
        self.filter_combo.set('All .txt files')
        self.filter_combo.grid(row=0, column=5, padx=5, pady=10)

        self.method_frame = ctk.CTkFrame(self)
        self.method_frame.pack(padx=20, pady=5, fill='x')

        self.method_label = ctk.CTkLabel(self.method_frame, text='Scan Options:', font=ctk.CTkFont(size=12, weight='bold'))
        self.method_label.grid(row=0, column=0, padx=10, pady=10, sticky='w')
        self.fast_checkbox = ctk.CTkCheckBox(self.method_frame, text='Fast Real Check', variable=self.fast_mode_var, onvalue=1, offvalue=0)
        self.fast_checkbox.grid(row=0, column=1, padx=10, pady=10)
        self.xray_checkbox = ctk.CTkCheckBox(self.method_frame, text='Xray Core', variable=self.xray_mode_var, onvalue=1, offvalue=0)
        self.xray_checkbox.grid(row=0, column=2, padx=10, pady=10)
        self.singbox_checkbox = ctk.CTkCheckBox(self.method_frame, text='Sing-box Core', variable=self.singbox_mode_var, onvalue=1, offvalue=0)
        self.singbox_checkbox.grid(row=0, column=3, padx=10, pady=10)

        self.source_frame = ctk.CTkFrame(self)
        self.source_frame.pack(padx=20, pady=5, fill='x')

        self.source_label = ctk.CTkLabel(self.source_frame, text='Add sources: paste links, subscription URL, base64 text or local file paths.', anchor='w')
        self.source_label.pack(pady=(10, 0), padx=10, anchor='w')

        self.source_textbox = ctk.CTkTextbox(self.source_frame, width=720, height=110)
        self.source_textbox.pack(padx=10, pady=(0, 10))

        self.actions_frame = ctk.CTkFrame(self.source_frame)
        self.actions_frame.pack(padx=10, pady=(0, 10), fill='x')

        self.add_links_btn = ctk.CTkButton(self.actions_frame, text='➕ Add Links / URLs', command=self.add_manual_sources)
        self.add_links_btn.pack(side='left', expand=True, fill='x', padx=5)
        self.add_files_btn = ctk.CTkButton(self.actions_frame, text='📄 Add Files', command=self.add_files)
        self.add_files_btn.pack(side='left', expand=True, fill='x', padx=5)
        self.clear_sources_btn = ctk.CTkButton(self.actions_frame, text='🧹 Clear Sources', command=self.clear_sources)
        self.clear_sources_btn.pack(side='left', expand=True, fill='x', padx=5)

        self.link_count_label = ctk.CTkLabel(self.source_frame, text='Loaded links: 0', anchor='w')
        self.link_count_label.pack(pady=(0, 10), padx=10, anchor='w')

        self.subscription_frame = ctk.CTkFrame(self)
        self.subscription_frame.pack(padx=20, pady=5, fill='x')

        self.subscription_entry = ctk.CTkEntry(self.subscription_frame, placeholder_text='Paste a subscription URL or base64 string here...')
        self.subscription_entry.pack(side='left', expand=True, fill='x', padx=(10, 5), pady=10)
        self.add_subscription_btn = ctk.CTkButton(self.subscription_frame, text='🔗 Add Subscription', width=170, command=self.add_subscription_source)
        self.add_subscription_btn.pack(side='right', padx=(5, 10), pady=10)

        self.actions_bottom = ctk.CTkFrame(self)
        self.actions_bottom.pack(padx=20, pady=(5, 10), fill='x')

        self.select_button = ctk.CTkButton(self.actions_bottom, text='📁 Select Folder', command=self.select_folder, font=ctk.CTkFont(weight='bold'))
        self.select_button.pack(side='left', expand=True, fill='x', padx=5)
        self.start_button = ctk.CTkButton(self.actions_bottom, text='🚀 Start Scan', command=self.start_scan, state='disabled', font=ctk.CTkFont(weight='bold'))
        self.start_button.pack(side='left', expand=True, fill='x', padx=5)
        self.export_button = ctk.CTkButton(self.actions_bottom, text='💾 Export Active TXT', command=self.export_active_links, state='disabled')
        self.export_button.pack(side='left', expand=True, fill='x', padx=5)

        self.controls_frame = ctk.CTkFrame(self)
        self.controls_frame.pack(padx=20, pady=5, fill='x')

        self.pause_button = ctk.CTkButton(self.controls_frame, text='⏸️ Pause', command=self.toggle_pause, state='disabled', fg_color='#e67e22', hover_color='#d35400', font=ctk.CTkFont(weight='bold'))
        self.pause_button.pack(side='left', expand=True, fill='x', padx=5)
        self.stop_save_button = ctk.CTkButton(self.controls_frame, text='💾 Stop & Save', command=self.stop_and_save, state='disabled', fg_color='#2980b9', hover_color='#2471a3', font=ctk.CTkFont(weight='bold'))
        self.stop_save_button.pack(side='left', expand=True, fill='x', padx=5)
        self.stop_button = ctk.CTkButton(self.controls_frame, text='🛑 Stop', command=self.stop_scan_now, state='disabled', fg_color='#c0392b', hover_color='#962d22', font=ctk.CTkFont(weight='bold'))
        self.stop_button.pack(side='left', expand=True, fill='x', padx=5)

        self.status = ctk.CTkLabel(self, text='Ready', font=ctk.CTkFont(size=12, slant='italic'))
        self.status.pack(pady=(10, 2))

        self.progress_bar = ctk.CTkProgressBar(self, width=740)
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=(2, 10))

        self.stats_frame = ctk.CTkFrame(self)
        self.stats_frame.pack(padx=20, pady=5, fill='x')
        self.stats_frame.columnconfigure((0, 1, 2, 3), weight=1)

        self.fast_label = ctk.CTkLabel(self.stats_frame, text='Fast verified: 0', text_color='#2ecc71', font=ctk.CTkFont(weight='bold'))
        self.fast_label.grid(row=0, column=0, padx=10, pady=10)
        self.medium_label = ctk.CTkLabel(self.stats_frame, text='Medium verified: 0', text_color='#f39c12', font=ctk.CTkFont(weight='bold'))
        self.medium_label.grid(row=0, column=1, padx=10, pady=10)
        self.slow_label = ctk.CTkLabel(self.stats_frame, text='Slow verified: 0', text_color='#9b59b6', font=ctk.CTkFont(weight='bold'))
        self.slow_label.grid(row=0, column=2, padx=10, pady=10)
        self.dead_label = ctk.CTkLabel(self.stats_frame, text='Dead: 0', text_color='#e74c3c', font=ctk.CTkFont(weight='bold'))
        self.dead_label.grid(row=0, column=3, padx=10, pady=10)

        self.copy_frame = ctk.CTkFrame(self)
        self.copy_frame.pack(padx=20, pady=5, fill='x')

        self.copy_fast_btn = ctk.CTkButton(self.copy_frame, text='📋 Copy Fast', command=self.copy_fast, state='disabled', font=ctk.CTkFont(weight='bold'))
        self.copy_fast_btn.pack(side='left', expand=True, fill='x', padx=5)
        self.copy_normal_btn = ctk.CTkButton(self.copy_frame, text='📋 Copy Normal', command=self.copy_normal, state='disabled', font=ctk.CTkFont(weight='bold'))
        self.copy_normal_btn.pack(side='left', expand=True, fill='x', padx=5)
        self.copy_all_btn = ctk.CTkButton(self.copy_frame, text='📋 Copy All Active', command=self.copy_all_active, state='disabled', font=ctk.CTkFont(weight='bold'))
        self.copy_all_btn.pack(side='left', expand=True, fill='x', padx=5)

        self.box = ctk.CTkTextbox(self, width=740, height=220, wrap='word')
        self.box.pack(padx=20, pady=(5, 10))

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
        self.after(0, lambda: [button.configure(state=state) for button in (self.copy_fast_btn, self.copy_normal_btn, self.copy_all_btn, self.export_button)])

    def update_live_stats(self, fast, medium, slow, dead):
        self.after(0, lambda: self._update_live_stats(fast, medium, slow, dead))

    def _update_live_stats(self, fast, medium, slow, dead):
        self.fast_label.configure(text=f'Fast verified: {fast}')
        self.medium_label.configure(text=f'Medium verified: {medium}')
        self.slow_label.configure(text=f'Slow verified: {slow}')
        self.dead_label.configure(text=f'Dead: {dead}')

    def update_link_count(self):
        self.after(0, lambda: self.link_count_label.configure(text=f'Loaded links: {len(self.loaded_links)}'))
        self.set_scan_buttons('normal' if self.loaded_links and self._selected_methods() else 'disabled')

    def _selected_methods(self):
        methods = []
        if self.fast_mode_var.get():
            methods.append('fast')
        if self.xray_mode_var.get():
            methods.append('xray')
        if self.singbox_mode_var.get():
            methods.append('singbox')
        return methods

    def add_files(self):
        file_paths = filedialog.askopenfilenames(filetypes=[('Text files', '*.txt'), ('All files', '*.*')])
        if not file_paths:
            return

        added_links = 0
        for file_path in file_paths:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                links = extract_links(content) or resolve_source(content)
                for link in links:
                    if link not in self.loaded_links:
                        self.loaded_links.add(link)
                        added_links += 1
            except Exception as e:
                self.log(f'❌ Error reading {os.path.basename(file_path)}: {e}')

        self.log(f'📄 Added {len(file_paths)} files and {added_links} new links.')
        self.update_link_count()

    def add_manual_sources(self):
        raw = self.source_textbox.get('1.0', 'end').strip()
        if not raw:
            self.log('⚠️ هیچ لینکی وارد نشده است.')
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
                if not links and os.path.isfile(line):
                    try:
                        with open(line, 'r', encoding='utf-8', errors='ignore') as f:
                            links = extract_links(f.read())
                    except Exception:
                        links = []

            for link in links:
                if link not in self.loaded_links:
                    self.loaded_links.add(link)
                    added_links += 1

        self.log(f'➕ Added manual sources and found {added_links} new links.')
        self.update_link_count()

    def add_subscription_source(self):
        source = self.subscription_entry.get().strip()
        if not source:
            self.log('⚠️ لینک ساب اسکرایب وارد نشده است.')
            return

        links = resolve_source(source)
        if not links and os.path.isfile(source):
            try:
                with open(source, 'r', encoding='utf-8', errors='ignore') as f:
                    links = extract_links(f.read())
            except Exception:
                links = []

        added_links = 0
        for link in links:
            if link not in self.loaded_links:
                self.loaded_links.add(link)
                added_links += 1

        self.log(f'🔗 Subscription source added: {added_links} new links found.')
        self.update_link_count()

    def clear_sources(self):
        self.loaded_links.clear()
        self.log('🧹 همه‌ی منابع پاک شد.')
        self.update_link_count()

    def select_folder(self):
        self.folder_path = filedialog.askdirectory()
        if self.folder_path:
            self.set_status(f'Folder: {self.folder_path}')
            self.update_link_count()

    def toggle_pause(self):
        if self.scan_state == 'running':
            self.scan_state = 'paused'
            self.pause_button.configure(text='▶️ Resume', fg_color='#2ecc71', hover_color='#27ae60')
            self.log('⏸️ Scan paused.')
            self.set_status('Scan paused')
        elif self.scan_state == 'paused':
            self.scan_state = 'running'
            self.pause_button.configure(text='⏸️ Pause', fg_color='#e67e22', hover_color='#d35400')
            self.log('▶️ Scan resumed.')
            self.set_status('Scan resumed')
            with self.pause_cond:
                self.pause_cond.notify_all()

    def stop_scan_now(self):
        self.scan_state = 'stopping'
        self.log('🛑 Stopping scan and discarding results...')
        self.set_status('Stopping...')
        self.set_control_buttons('disabled', 'disabled', 'disabled')
        with self.pause_cond:
            self.pause_cond.notify_all()

    def stop_and_save(self):
        self.scan_state = 'stopping_save'
        self.log('💾 Stopping scan and saving progress...')
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

    def start_scan(self):
        if not self.loaded_links:
            self.log('⚠️ هیچ لینکی برای اسکن وجود ندارد.')
            return
        methods = self._selected_methods()
        if not methods:
            self.log('⚠️ حداقل یک روش تست را انتخاب کنید.')
            return

        self.box.delete('1.0', 'end')
        if self.folder_path:
            log_dir = os.path.join(self.folder_path, 'Scan_Results')
            os.makedirs(log_dir, exist_ok=True)
            log_filepath = os.path.join(log_dir, 'scan_log.txt')
            with open(log_filepath, 'w', encoding='utf-8') as f:
                f.write(f'=== ScanV2Ray LOG STARTED AT {time.strftime("%Y-%m-%d %H:%M:%S")} ===\n')

        self.log('🚀 Starting scan...')
        self.set_progress(0)
        self.set_scan_buttons('disabled')
        self.set_copy_buttons('disabled')
        self.fast_links = []
        self.normal_links = []
        self.active_links = []
        self.update_live_stats(0, 0, 0, 0)
        self.scan_state = 'running'
        self.pause_button.configure(text='⏸️ Pause', fg_color='#e67e22', hover_color='#d35400')
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
                self.log('⚠️ Invalid thread count. Using 40.')

            try:
                timeout_ms = float(self.timeout_entry.get().strip())
                if timeout_ms <= 0:
                    raise ValueError
                timeout = timeout_ms / 1000.0  # تبدیل میلی‌ثانیه به ثانیه
            except ValueError:
                timeout = 6.0
                self.log('⚠️ Invalid timeout. Using 6000ms (6.0s).')

            if 'xray' in methods and not os.path.exists(self.scanner.xray_path):
                self.log('❌ xray.exe not found in Core/xray/ folder!')
                self.set_status('Scan aborted: xray.exe missing')
                return
            if 'singbox' in methods and not os.path.exists(self.scanner.singbox_path):
                self.log('❌ sing-box.exe not found in Core/sing_box/ folder!')
                self.set_status('Scan aborted: sing-box.exe missing')
                return

            unique_links = sorted(self.loaded_links)
            total_links = len(unique_links)
            self.log(f'📄 Processing {total_links} unique links...')

            results = []
            completed = 0
            fast_count = 0
            medium_count = 0
            slow_count = 0
            dead_count = 0
            active_links = set()
            fast_links_set = set()
            normal_links_set = set()

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(self.scanner.process_link, link, timeout, methods): link for link in unique_links}
                for future in as_completed(futures):
                    if self.scan_state == 'stopping':
                        self.log('🛑 Scan aborted by user. Results discarded.')
                        break
                    elif self.scan_state == 'stopping_save':
                        self.log('💾 Scan stopped by user. Saving completed results...')
                        break

                    while self.scan_state == 'paused':
                        time.sleep(0.2)

                    completed += 1
                    link = futures[future]
                    try:
                        link_results = future.result()
                    except Exception:
                        link_results = []

                    if link_results:
                        link_classifications = set()
                        for item in link_results:
                            results.append(item)
                            classification = item.get('classification', 'dead')
                            link_classifications.add(classification)
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

                    pct = completed / total_links
                    self.set_progress(pct)
                    self.set_status(f'Scanned: {completed}/{total_links} ({pct*100:.1f}%)')
                    self.update_live_stats(fast_count, medium_count, slow_count, dead_count)

            if self.scan_state != 'stopping':
                self.fast_links = sorted(fast_links_set)
                self.normal_links = sorted(normal_links_set)
                self.active_links = sorted(active_links)
                self.save_results(results)
                self.log('\n✅ SCAN COMPLETE')
                self.log(f'📊 Verified links: {len(active_links)} (fast: {len(fast_links_set)}, medium/slow: {len(normal_links_set)})')
                self.set_status('Scan completed successfully')
            else:
                self.set_status('Scan aborted')
        except Exception as e:
            self.log(f'💥 Scan error: {e}')
            self.set_status('Scan failed')
        finally:
            self.set_scan_buttons('normal')
            self.set_copy_buttons('normal')
            self.set_control_buttons('disabled', 'disabled', 'disabled')
            self.scan_state = 'idle'

    def save_results(self, results):
        if not self.folder_path:
            self.log('⚠️ برای ذخیره نتایج باید یک پوشه انتخاب کنید.')
            return

        output_dir = os.path.join(self.folder_path, 'Scan_Results')
        os.makedirs(output_dir, exist_ok=True)
        self.log(f'💾 Saving results inside: {output_dir}')

        if results:
            json_path = os.path.join(output_dir, 'scan_results.json')
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            self.log(f'  └─ Saved scan_results.json')

            csv_path = os.path.join(output_dir, 'scan_results.csv')
            with open(csv_path, 'w', encoding='utf-8') as f:
                f.write('method,proto,link,remark,latency_ms,speed_kbps,success_ratio,average_latency_ms,score,classification\n')
                for item in results:
                    f.write(
                        f"{item['method']},{item['proto']},\"{item['link']}\",\"{item['remark']}\"," +
                        f"{item['latency']},{item['speed']:.2f},{item['success_ratio']},{item.get('average_latency','')},{item['score']},{item['classification']}\n"
                    )
            self.log(f'  └─ Saved scan_results.csv')

        groups = {'fast': [], 'medium': [], 'slow': [], 'dead': []}
        for item in results:
            groups.setdefault(item['classification'], []).append(item)

        for classification, items in groups.items():
            file_base = f'{classification}_verified.txt' if classification != 'dead' else 'dead.txt'
            file_path = os.path.join(output_dir, file_base)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join([item['link'] for item in items]))
            self.log(f'  └─ Saved {file_base}')

    def export_active_links(self):
        active = sorted(set(self.fast_links + self.normal_links))
        if not active:
            self.log('⚠️ هیچ کانفیگ فعالی برای خروجی وجود ندارد.')
            return
        if not self.folder_path:
            self.log('⚠️ ابتدا پوشه را انتخاب کنید تا خروجی ذخیره شود.')
            return
        output_dir = os.path.join(self.folder_path, 'Scan_Results')
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, 'active_connected_configs.txt')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(active))
        self.log(f'💾 Exported active configs to {os.path.basename(file_path)}')

    def copy_fast(self):
        if self.fast_links:
            self.clipboard_clear()
            self.clipboard_append('\n'.join(self.fast_links))
            self.update()
            self.log('📋 Fast configs copied.')
        else:
            self.log('⚠️ هیچ کانفیگ سریع برای کپی وجود ندارد.')

    def copy_normal(self):
        if self.normal_links:
            self.clipboard_clear()
            self.clipboard_append('\n'.join(self.normal_links))
            self.update()
            self.log('📋 Normal configs copied.')
        else:
            self.log('⚠️ هیچ کانفیگ نرمال برای کپی وجود ندارد.')

    def copy_all_active(self):
        all_links = sorted(set(self.fast_links + self.normal_links))
        if all_links:
            self.clipboard_clear()
            self.clipboard_append('\n'.join(all_links))
            self.update()
            self.log('📋 All active configs copied.')
        else:
            self.log('⚠️ هیچ کانفیگ فعالی برای کپی وجود ندارد.')
