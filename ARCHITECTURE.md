# ScanV2Ray (xrayscan) — Authoritative Architecture Map

Repo root: `/root/xrayscan` · Python (customtkinter GUI) + bundled `xray.exe`/`sing-box.exe` under `Core/`. Total app code ≈ 2164 LOC across `Scan.py` + `scanv2ray/`.

---

## 1. Overview

ScanV2Ray is a **Windows desktop GUI** (customtkinter) that imports V2Ray/Xray proxy share-links from pasted text, local files, subscription URLs, base64 blobs, or JSON, then runs a **3-stage pipeline** to find working proxies: (1) a raw-TCP **precheck** to the remote host:port, (2) **config validation** by writing a generated Xray JSON and running `xray.exe -test -c`, and (3) a **real connectivity/speed test** that launches `xray.exe` as a local HTTP proxy on an ephemeral 127.0.0.1 port and drives real HTTP requests through it to Google/Cloudflare `generate_204`, `trace`, and `speed.cloudflare.com/__down` endpoints. Each surviving config is **scored** (weighted latency/speed/stability/success) and classified **fast / medium / slow / dead**, with live counters in the UI, then exported to `Scan_Results/` as JSON, CSV, and grouped `.txt` files (plus clipboard/TXT export). `Scan.py` is a 5-line launcher; all logic lives in the `scanv2ray` package. A `sing-box` engine path exists throughout but is **entirely dead code** — the engine is hardwired to Xray.

---

## 2. Architecture Diagram

```
                                 ┌──────────────────────────────────────────────────┐
  USER INPUT                     │                  scanv2ray/ui.py                 │
  ─────────                      │              ConfigScannerApp (ctk.CTk)          │
  pasted text ─┐                 │                                                  │
  local files ─┤  add_files /    │  Sources card ── protocol filter (vmess/vless/   │
  sub URLs   ──┤  add_manual_    │                    ss/trojan) + Quick/Full mode  │
  base64 blob ─┤  sources        │                                                  │
  JSON       ──┘                 │  Start ─► run_scan() on daemon Thread            │
        │                        └───────────────┬──────────────────────────────────┘
        ▼                                        │ (3 sequential ThreadPoolExecutor stages)
  ┌──────────────────────┐                       │
  │  scanv2ray/parser.py │◄──────────────────────┘ parse_link / resolve_source /
  │  resolve_source      │                          extract_links (proto tagging, dedupe)
  │  parse_vmess/generic │
  │  validate_parsed_… │──► normalized `parsed` dict
  └──────────┬───────────┘        {proto,host,port,credentials,transport_type,
             │                     security_mode,sni,path,host_header,flow,extra{}}
             ▼
  ┌──────────────────────┐   make_xray_config(parsed, local_port)
  │ scanv2ray/configs.py │──────────────────────► xray JSON dict
  │ build_xray_stream_…│   (http inbound 127.0.0.1:port ─► remote outbound)
  └──────────┬───────────┘   [make_singbox_config = DEAD]
             ▼
  ┌───────────────────────────────────────────────────────────────────────┐
  │                         scanv2ray/scanner.py                            │
  │  Stage 1 precheck_link ── raw socket.create_connection(host,port)       │
  │  Stage 2 validate_prechecked_link ── xray.exe -test -c temp_config.json │
  │  Stage 3 test_prepared_link ─► _test_core:                             │
  │            get_free_port ─► write JSON ─► Popen(xray.exe -c) ─►         │
  │            _wait_for_local_port ─► _measure_proxy (HTTP via 127.0.0.1)  │
  │            ─► _score_metrics ─► result dict                            │
  └───────────────────────────────┬────────────────────────────────────────┘
                                   ▼
                       results (fast/medium/slow/dead)
                                   │
            ┌──────────────────────┴───────────────────────┐
            ▼                                               ▼
   live counters (self.after)              save_results ─► <folder>/Scan_Results/
   copy_fast/normal/active                   scan_results.json / .csv
   export_active_links                       fast|medium|slow_verified.txt / dead.txt

  EXTERNAL: Core/xray/xray.exe (used) · Core/sing_box/sing-box.exe (referenced, never invoked)
  TEST TARGETS: gstatic /generate_204 · cloudflare /cdn-cgi/trace · google /generate_204 · speed.cloudflare.com/__down
```

---

## 3. Module-by-Module Reference

### `Scan.py` (entry point) — 5 lines
- **Purpose:** launcher. Imports `ConfigScannerApp` from `scanv2ray` and calls `.mainloop()`.
- **API:** none; only consumes `scanv2ray.ConfigScannerApp`.
- **Deps:** `scanv2ray`. Named as PyInstaller entry point in `ScanV2Ray.spec:5` and `build_exe.ps1:12`.

### `scanv2ray/__init__.py` — 3 lines
- **Purpose:** package façade; re-exports `ConfigScannerApp` from `.ui`.
- **API:** `scanv2ray.ConfigScannerApp`.

### `scanv2ray/parser.py` — 364 lines
- **Purpose:** turn arbitrary user input / subscription sources into normalized `parsed` config dicts; validate them.
- **Module constants:** `SUPPORTED_PROTOCOLS` (`parser.py:7`, tuple: vmess/vless/trojan/ss/hysteria/hysteria2), `LINK_RE` (`:8`), `UUID_RE` (`:9`, strict 8-4-4-4-12), `SUPPORTED_SS_METHODS` (`:10-15`, includes insecure legacy ciphers rc4/des-cfb/*-cfb).
- **Public API / key functions:**
  - `try_decode_base64_content(content)` `:18-31` — pad + b64decode a whole blob. **The `if LINK_RE.search` branch and `else` both return `decoded` → search is dead.**
  - `extract_links(text)` `:34-40` — `LINK_RE.findall` over CR/LF-normalized text.
  - `extract_links_from_json(payload)` `:43-53` — recursive string harvest, order-preserving dedupe via `dict.fromkeys`.
  - `fetch_subscription_source(source)` `:56-67` — `urllib` GET, 15s timeout, base64→links→JSON fallback; swallows all exceptions → `[]`.
  - `resolve_source(source)` `:70-96` — top dispatch: http(s) URL → fetch; else regex → base64 → raw JSON.
  - `parse_vmess(link)` `:99-160` — base64-JSON body (`link[8:]`, strip `#`/`?`), maps v2rayN fields, TLS inferred from `tls` or port 443.
  - `parse_generic(link)` `:163-313` — URI parser for vless/trojan/ss/hysteria/hysteria2 via `urlparse`; SS base64 userinfo handling; large `extra` dict.
  - `validate_parsed_config(parsed)` `:316-355` — returns `(bool, error_message)`; per-proto credential rules; xtls restricted to vless.
  - `parse_link(link)` `:358-364` — router: vmess → `parse_vmess`, else `parse_generic`.
- **Deps:** stdlib only (`base64`, `json`, `re`, `urllib.request`, `urllib.parse`). **Fully cross-platform.**

### `scanv2ray/configs.py` — 316 lines
- **Purpose:** pure dict construction of Xray/sing-box config documents from a `parsed` dict + `local_port`. No I/O, no subprocess.
- **Public API / key functions:**
  - `_parse_alpn(value)` `:4-9` — normalize ALPN; falsy → default `['h2','http/1.1']`.
  - `build_xray_stream_settings(parsed)` `:12-88` — `streamSettings` for ws/grpc/h2/quic/kcp + tls/xtls/reality. Reality defaults fp `chrome`, spiderX `/`. Hardcoded KCP tuning (mtu 1350, tti 20, up 5, down 20).
  - `make_xray_config(parsed, local_port)` `:91-201` — **the sole config path actually used.** Early `return None` for falsy/hysteria/hysteria2 (`:94`). Builds vmess (vnext, alterId 0, security auto), vless (encryption none, optional flow), trojan, ss (`credentials.split(':',1)`, default cipher `aes-256-gcm`). **Dead hysteria branch `:158-188` is unreachable behind the `:94` guard.** Wraps with loglevel `none` + http inbound 127.0.0.1:local_port.
  - `build_singbox_transport(parsed)` `:204-249` — **DEAD** (never reached).
  - `make_singbox_config(parsed, local_port)` `:252-316` — **DEAD**; forces insecure TLS; no hysteria/reality handling.
- **Deps:** `os` imported `:1` but **unused**. Cross-platform.

### `scanv2ray/scanner.py` — 379 lines
- **Purpose:** `Scanner` class — generate/validate/launch Xray, measure, score. Staged entrypoints for a pipelined worker pool.
- **Module helper:** `get_free_port()` `:14-19` — bind-then-close ephemeral port (race-prone).
- **Public API / key functions:**
  - `Scanner(xray_path, singbox_path)` `:23-26` — stores paths, `BoundedSemaphore(6)` for speed tests.
  - `set_speed_test_limit(limit)` `:28-29` — **replaces** the semaphore object (in-flight threads keep the old one).
  - `_write_config(config_data)` `:31-36` — writes `../Core/temp_config_<uuid4hex>.json`.
  - `_run_core_process(args)` `:38-57` — `Popen` with `CREATE_NO_WINDOW=0x08000000`, sleep 0.2s; logs to `Core/process_launch_error.log`.
  - `_cleanup_process(proc, config_path)` `:59-73` — terminate→wait(1s)→kill, remove temp config.
  - `_wait_for_local_port(port, timeout=5.0)` `:75-83` — poll `create_connection` every 0.1s.
  - `_validate_xray_config(binary, cfg)` `:85-105` — `xray.exe -test -c`, 10s; logs to `Core/xray_config_test.log`.
  - `_validate_singbox_config(...)` `:107-118` — **DEAD** (`sing-box check`, never called).
  - `_measure_proxy(local_port, timeout, quick)` `:120-192` — 2–3 `generate_204`/`trace` probes + Cloudflare download (10KB quick / 50KB full) under the semaphore. Returns metrics dict.
  - `_score_metrics(metrics)` `:194-212` — weighted score + classification (see §Data model).
  - `_build_benchmark_result(...)` `:214-227` — assembles result dict.
  - `_build_config(parsed, local_port, engine)` `:229-232` — xray only; None otherwise.
  - `_validate_config(...)` `:234-235` — **ignores engine, always xray.**
  - `_test_core(parsed, timeout, binary, engine, quick, prevalidated)` `:237-269` — core lifecycle with `finally` cleanup.
  - `precheck_link(link, timeout=0.7)` `:271-292` — Stage 1; rejects hysteria/hysteria2; raw TCP with reason codes.
  - `validate_prechecked_link(item)` `:294-314` — Stage 2; builds config, `xray -test`.
  - `_fast_core_test(...)` `:316-319` — **DEAD-ish** helper.
  - `prepare_link(link)` `:321-345` — **unused alternate** (near-dup of validate_prechecked_link).
  - `test_prepared_link(prepared, timeout, method)` `:347-355` — Stage 3; `prevalidated=True`, `quick=(method=='fast')`.
  - `process_link(link, timeout, methods)` `:357-379` — **unused** all-in-one entry.
- **Deps:** stdlib + `scanv2ray.configs.make_xray_config`, `scanv2ray.parser.{parse_link, validate_parsed_config}`.

### `scanv2ray/ui.py` — 1097 lines
- **Purpose:** the entire GUI + scan orchestration. `ConfigScannerApp(ctk.CTk)`.
- **Public API:** `ConfigScannerApp()`.
- **Key functions:**
  - `__init__` `:22-54` — window 840x900 / minsize 820x820; scan state (`loaded_links` set, `link_protocols` dict, `scan_state='idle'`, `pause_cond`, `log_lock`/`log_queue`); builds `xray_path`=`../Core/xray/xray.exe` (`:42`), `singbox_path`=`../Core/sing_box/sing-box.exe` (`:43`); constructs `Scanner`; `scan_mode_var` default `'Fast'` (`:46`, later overridden).
  - UI builders: `_build_ui` `:56-102`, `_build_sources_card` `:104-177` (`self.protocols=['vmess','vless','ss','trojan']` `:157`), `_build_setup_card` `:179-255` (segmented `['Quick','Full']` `:191`; defaults Concurrency `40` `:241`, Timeout `3000` `:247`), `_build_progress_card` `:257-301`, `_build_results_card` `:303-341`.
  - About/Donate: `_load_about_info` `:343-399` (regex BTC/TRX + t.me/instagram/github; `sys._MEIPASS` support `:347`), `open_donate_popup` `:401-444` (`webbrowser.open` `:439`).
  - Threading marshals: `log` `:456-461`, `_process_log_queue` `:463-471`, `set_status/set_progress/set_control_buttons/set_scan_buttons/set_copy_buttons/update_live_stats` `:473-503` (all wrap `self.after(...)`).
  - Source mgmt: `update_link_count` `:505-516`, `refresh_sources_listbox` `:518-529`, `remove_selected_sources` `:531-548`, `_compute_protocol_counts` `:550-565`, `_filtered_loaded_links` `:567-585`, `_selected_methods` `:587-588` (`['xray']` if Full else `['fast']`), `_add_links` `:590-609` (skips hysteria/2 `:600`), `add_files` `:611-626`, `add_manual_sources` `:628-652`, `add_subscription_source` `:654-655` (**dead alias**), `clear_sources`/`select_folder` `:657-671`.
  - Control: `toggle_pause` `:673-685`, `stop_scan_now`/`stop_and_save` `:687-701`, `check_pause_and_stop` `:703-710` (**defined, never called**), `_dead_result` `:712-724` (**`reason` arg discarded**).
  - `start_scan` `:726-777` — validates, writes `scan_log.txt` header, reads threads/timeout on main thread, spawns `run_scan` daemon Thread.
  - `run_scan(methods, filtered_links, max_workers=None, timeout=3.0)` `:779-1002` — **the orchestrator**: aborts if `xray.exe` missing (`:787`); worker math `:795-798`; 3 `ThreadPoolExecutor` stages with `wait(FIRST_COMPLETED, timeout=0.5)` loops honoring pause/stop; accumulates results + live counts; progress weighting `:851/896/959`; Remark override `:973`; `save_results`; button reset in `finally`.
  - `save_results(results)` `:1004-1044` — writes `scan_results.json`, hand-rolled `scan_results.csv`, grouped `fast/medium/slow_verified.txt` + `dead.txt` (`link | remark`).
  - `export_active_links` `:1046-1069`, `copy_fast/copy_normal/copy_all_active` `:1071-1098`.
- **Deps:** stdlib (`json, os, threading, time, re, webbrowser, sys`, `concurrent.futures` — `as_completed` imported but unused), `tkinter`, `customtkinter`, `.parser`, `.scanner`.

### Build & meta files
- `ScanV2Ray.spec` — PyInstaller onefile/windowed; entry `Scan.py:5`; `datas=[('About.md','.'),('scanv2ray','scanv2ray'),('Core','Core')]` `:8`; `hiddenimports=[]`; `console=False`, `upx=True`, `runtime_tmpdir=None`.
- `build_exe.ps1` — CLI mirror of the spec (`--add-data` with **Windows `;` separator**, `:9-11`); re-`pip install --upgrade pyinstaller` `:5`; `Write-Host` `:15`. **Two build definitions that can drift.**
- `requirements.txt` — single unpinned line `customtkinter`; **omits pyinstaller.**
- `configtest.txt` — 97 real proxy URIs (vmess/ss/vless/trojan) as regression fixture; string ports/aid, missing `type`/`tls`, ss `plugin=` querystrings, base64 padding edge cases.
- `About.md` — live BTC/TRX wallets + social links rendered in Donate popup.
- `Core/xray/{xray.exe,wintun.dll,...}` (used), `Core/sing_box/{sing-box.exe,libcronet.dll}` (bundled, never invoked).

---

## 4. Data Model

A single **`parsed` dict** flows end-to-end. Produced by `parse_vmess` (`parser.py:144-158`) / `parse_generic` (`:297-311`) — both must stay schema-identical.

| Field | Meaning | Source |
|---|---|---|
| `proto` | vmess/vless/trojan/ss/hysteria/hysteria2 | scheme |
| `host` | remote address | `add`/authority |
| `port` | int 1–65535 | (⚠ vmess JSON `port` is a **string**, coerced) |
| `remark` | display name | `#fragment` / `ps` |
| `is_tls` | bool | `tls` field or port==443 heuristic |
| `security_mode` | none/tls/xtls/reality | query `security` |
| `sni` | TLS SNI (**falls back to host, possibly an IP**) | `sni`/`peer`/host |
| `credentials` | uuid (vmess/vless) · password (trojan) · `method:password` (ss) · auth (hysteria) | userinfo |
| `transport_type` | tcp/ws/grpc/h2/quic/kcp (hysteria→udp) | `type`/`net`/`protocol` |
| `path` | ws path / grpc serviceName | `path`/`serviceName` |
| `host_header` | Host header | `host` |
| `flow` | xtls flow (vless) | query |
| `extra{}` | alpn, fp, pbk, sid, spx, obfs, up, down, auth, peer, headerType, serviceName, security, key | query |

**Build stage** (`make_xray_config`): `parsed` → xray JSON `{log{loglevel:none}, inbounds:[http 127.0.0.1:local_port], outbounds:[<proto outbound + streamSettings>]}`.

**Test → metrics dict** (`_measure_proxy`, `scanner.py:120-192`): `{latency, average_latency, download_kbps, successes, requests, success_ratio, ...}`.

**Result dict** (`_build_benchmark_result`, `:214-227`): `{method, proto, link, remark, latency, speed, success_ratio, average_latency, score, classification}`. Dead results from `_dead_result` (`ui.py:712-724`) share `{latency 0, speed 0.0, score 0.0, classification 'dead'}` — **but the failure `reason` is never stored.**

**Scoring** (`_score_metrics`, `scanner.py:194-212`): `score = speed*0.4 + delay*0.3 + stability*0.2 + success*0.1`, where speed normalized `200 kbps == 100`, delay baseline 1000ms. **dead** if `success_ratio<0.3 AND download<1.0 kbps`; else **fast ≥75**, **medium ≥55**, else **slow**.

---

## 5. Supported Protocols

| Proto | Parsed by | Xray outbound mapping | Status |
|---|---|---|---|
| **vmess** | `parse_vmess` (base64 JSON) | `vnext`, alterId 0, security auto (`configs.py:103-119`) | ✅ full |
| **vless** | `parse_generic` (URI+query) | encryption none, optional `flow`; only proto allowed xtls (`parser.py:validate`, `configs.py`) | ✅ full |
| **trojan** | `parse_generic` | `servers`/`password` | ✅ full |
| **ss** | `parse_generic` (SIP002 base64 userinfo) | `shadowsocks`, `credentials.split(':',1)`, default cipher `aes-256-gcm` (`configs.py:147`) | ✅ but accepts **insecure legacy ciphers** (rc4/des-cfb/*-cfb, `parser.py:10-15`) that `xray.exe` may reject at runtime; SIP002 `plugin=` querystrings not handled |
| **hysteria** | `parse_generic` (parses) | `make_xray_config` returns None at `:94`; dead branch `:158-188` | ❌ **rejected** — precheck marks `xray_unsupported_protocol` (`scanner.py:280`) |
| **hysteria2** | `parse_generic` (parses) | same rejection | ❌ **rejected** |

**Transports** (`build_xray_stream_settings`, `configs.py:12-88`): ws / grpc / h2 / quic / kcp + tcp. **Security modes:** none / tls / xtls / reality (reality via `pbk/sid/spx/fp`, `configs.py:37-48`).

**Gaps:** hysteria/hysteria2 listed in `SUPPORTED_PROTOCOLS` but universally rejected (also filtered out at UI import, `ui.py:600`). No tuic/wireguard/shadowtls. ss plugins unsupported. sing-box path (which *does* handle ss/vmess/vless/trojan but **not** reality/hysteria) is dead.

---

## 6. The Scan Pipeline

Orchestrated by `run_scan` (`ui.py:779-1002`) on a **daemon thread**. Three sequential `ThreadPoolExecutor` stages over `sorted(set(filtered_links))`, each with a `wait(FIRST_COMPLETED, timeout=0.5)` loop polling `scan_state` for pause/stop.

**Concurrency (max_workers = GUI threads, default 40):**
- Stage 1 workers: `min(mw*4, 200)` · Stage 2: `min(mw, 80)` · Stage 3: `min(mw, 12)` · speed-test semaphore: `min(real, 6)`, hard cap `BoundedSemaphore(6)` (`ui.py:795-798`, `scanner.py:26`).
- Executors torn down with `shutdown(wait=False, cancel_futures=True)` (`ui.py:856/901/964`) — **requires Python ≥3.9**.

**Stage 1 — precheck** (`Scanner.precheck_link`, `scanner.py:271-292`, progress 0→0.15): `parse_link`+`validate_parsed_config`; reject hysteria/2; `socket.create_connection((host,port), timeout=0.7)` with reason codes `tcp_dns_failed`/`tcp_timeout`/`tcp_failed:<errno>`. No subprocess.

**Stage 2 — validate** (`validate_prechecked_link`, `:294-314`, progress 0.15→0.40): `make_xray_config` at a fresh `get_free_port()` → `_write_config` → `subprocess.run([xray.exe, '-test', '-c', cfg], timeout=10)` (`scanner.py:87`). Returncode 0 → `ok`; else `xray_json_invalid`, stderr appended to `Core/xray_config_test.log`.

**Stage 3 — real test** (`test_prepared_link`→`_test_core`, `:347-355`/`:237-269`, progress 0.40→1.00): `get_free_port` → write config → `subprocess.Popen([xray.exe, '-c', cfg], creationflags=CREATE_NO_WINDOW)` + sleep 0.2s (`:41-47`) → `_wait_for_local_port` (poll 0.1s, connect timeout 0.5s, startup clamped `[2.0,4.0]`s, quick 2.0s) → `_measure_proxy` → `_score_metrics` → drop dead → `_cleanup_process` in `finally`.

**`_measure_proxy` subprocess/network** (`:120-192`): HTTP opener to `http://127.0.0.1:<port>`; probes (Quick=first 2, Full=3): `https://www.gstatic.com/generate_204`, `https://www.cloudflare.com/cdn-cgi/trace`, `https://www.google.com/generate_204` (success = HTTP 200/204, endpoint timeout `min(timeout,2.5)`, break on first success). Then download `https://speed.cloudflare.com/__down?bytes=N` (Quick 10000B / Full 50000B) under the speed semaphore, download timeout `max(timeout,8.0)` (quick `max(endpoint,4.0)`).

**Mode mapping:** UI `Quick`→`['fast']` (quick=True), `Full`→`['xray']` (`_selected_methods`, `ui.py:587-588`). Save unless `scan_state=='stopping'` (so `stopping_save` keeps completed work, `ui.py:966`).

---

## 7. External Binaries & Files

- **`Core/xray/xray.exe`** — the only invoked core. Two calls: `-test -c <cfg>` (validate, 10s) and `-c <cfg>` (run as local proxy). Companion `wintun.dll` present.
- **`Core/sing_box/sing-box.exe`** (+`libcronet.dll`) — **bundled and path-constructed (`ui.py:43`) but never executed.** `make_singbox_config`/`build_singbox_transport`/`_validate_singbox_config` are all unreachable.
- **Temp configs:** `Core/temp_config_<uuid4hex>.json` (`scanner.py:32-33`), JSON no-indent, removed in `_cleanup_process` — **leak on hard crash/kill.**
- **Debug logs (append-only):** `Core/process_launch_error.log`, `Core/xray_config_test.log`, `Core/singbox_config_test.log` (last never written).
- **Outputs:** `<folder>/Scan_Results/`: `scan_log.txt` (header only — see bugs), `scan_results.json`, `scan_results.csv`, `fast_verified.txt`, `medium_verified.txt`, `slow_verified.txt`, `dead.txt` (`link | remark`), plus user-chosen `active_configs.txt`.
- **`About.md`** — read at startup (via `sys._MEIPASS` or `../` candidates) for the Donate popup.

---

## 8. Windows-Only Assumptions & Portability Risks

1. **`.exe` binary paths** hardcoded: `../Core/xray/xray.exe`, `../Core/sing_box/sing-box.exe` (`ui.py:42-43`). On POSIX `os.path.exists` fails → `run_scan` aborts at `:787` ("xray.exe not found"); every scan dies.
2. **`CREATE_NO_WINDOW = 0x08000000`** creationflag (`scanner.py:39/45`) — Win32-only; passing it on Linux/macOS makes `Popen` raise (caught → logged → returns None → silent launch failure).
3. **Build is Windows-bound:** `build_exe.ps1` uses `;` `--add-data` separator (`:9-11`), `Write-Host`, targets `.exe`; PowerShell-only.
4. **PyInstaller onefile fragility:** `_MEIPASS` is used only for `About.md` (`ui.py:347`), **not** for `xray_path` — in a frozen onefile build `__file__` points into the temp extraction dir, so `../Core/xray/xray.exe` likely resolves wrong.
5. Portable modules: `parser.py` and `configs.py` are pure stdlib/dict — no OS assumptions leak in.

---

## 9. Change Hotspots (ranked for likely future work)

1. **Cross-platform / headless core** *(highest leverage)*: parameterize binary paths + strip `.exe` (`ui.py:41-44`); guard `CREATE_NO_WINDOW` behind `sys.platform=='win32'` (`scanner.py:39/45`); resolve binaries via `_MEIPASS`. Decouple `Scanner`+pipeline from the ctk app so it can run without Tk.
2. **Add/enable a protocol** (tuic, wireguard, or *actually* hysteria2): edit **all four** — `parser.SUPPORTED_PROTOCOLS`+`LINK_RE` (`parser.py:7-8`, they can drift), `parse_generic`/`parse_vmess`, `validate_parsed_config` (`:316`), `make_xray_config` if/elif ladder + remove the `:94` guard & reconcile dead branch `:158-188`, and UI `self.protocols` (`ui.py:157`) + hysteria skip (`ui.py:600`). Update `configtest.txt` fixture.
3. **Enable the sing-box engine:** `_build_config` (`scanner.py:229`) and `_validate_config` (`:234`) hardwire xray; generalize engine dispatch, then the whole `make_singbox_config`/`build_singbox_transport`/`_validate_singbox_config` chain becomes reachable. sing-box also needs reality support added.
4. **Add/modify a transport** (httpupgrade, xhttp/splithttp): `build_xray_stream_settings` (`configs.py:12`) [+ `build_singbox_transport` `:204` if reviving sing-box].
5. **Scoring / classification / test endpoints** (important for Iran censorship context — google/gstatic/cloudflare may be throttled): `_score_metrics` (`scanner.py:194-212`) thresholds/weights, `_measure_proxy` endpoint list (`:125-129,170`).
6. **Concurrency / pipeline stages:** worker math + the three executor loops in `run_scan` (`ui.py:795-798`).
7. **Different UI / Telegram / server-side mode:** the pipeline is embedded in `run_scan` on the ctk app — extract it into an engine module; results already serialize cleanly via `save_results` (`ui.py:1004`).
8. **Output formats:** `save_results` (`ui.py:1004`), `export_active_links` (`:1046`).
9. **Packaging:** `ScanV2Ray.spec` + `build_exe.ps1` (keep in lockstep), `requirements.txt`.

---

## 10. Bugs / Fragility / Tech Debt

**Correctness bugs**
- **Failure reason discarded:** `_dead_result` accepts `reason` (`ui.py:712`, called `:849/894/934/957`) but never stores it → no diagnostics reach JSON/CSV/`dead.txt`.
- **`scan_log.txt` never populated:** `start_scan` writes only a header (`ui.py:743-745`); `log()`/`_process_log_queue` write to the textbox only — the file stays one line.
- **Fragile hand-rolled CSV:** `save_results` (`ui.py:1020-1026`) wraps `link`/`remark` in quotes but never escapes embedded quotes/commas/newlines and never neutralizes formula chars → CSV corruption **and spreadsheet formula-injection** from a crafted remark. Use the `csv` module.
- **Dead base64 logic:** `try_decode_base64_content` (`parser.py:27-29`) — both branches return `decoded`; non-base64 ASCII that "decodes" is silently mangled instead of preserved, breaking downstream extraction.
- **sing-box invalid outbound (latent):** `make_singbox_config` emits an outbound with no `type` for unknown/hysteria protos (would be rejected) — masked only because the path is dead.
- **`scan_mode_var` default trap:** default `'Fast'` (`ui.py:46`) but segmented values are `['Quick','Full']`; only works because `mode_selector.set('Quick')` runs at `:197`. Remove that `set()` and the mapping breaks.

**Concurrency / race fragility**
- **Port race:** `get_free_port` binds-then-closes (`scanner.py:14-19`); with many parallel workers another thread/process can grab the port before `xray.exe` binds it → startup failure or **`_wait_for_local_port` false-positive connecting to the wrong service** (`:75-83`).
- **Semaphore swap:** `set_speed_test_limit` replaces the object (`:28-29`); threads inside `with self.speed_test_semaphore` hold the old one → inconsistent throttling.
- **Cross-thread Tk call:** worker reads `remarker_var.get()` (`ui.py:973`) directly off the daemon thread, not marshaled through `self.after` — unsafe under Tk. `scan_state` is a bare string shared across threads with no lock (relies on GIL/assignment atomicity; only `pause_cond` waits are synchronized).
- **No Popen stdout/stderr draining:** pipes set on the long-running `xray.exe` but never read (`scanner.py:41-46`); a chatty core could fill the buffer and deadlock (mitigated only because loglevel is `none`).
- **No poll after launch:** `_run_core_process` sleeps 0.2s and returns without `proc.poll()`; an instantly-dying core wastes up to the startup timeout before detection.

**Metrics / scoring**
- **Muddled `success_ratio`:** the download request is added to `metrics['requests']` after connectivity ratio is computed, mixing connectivity probes with the download so semantics differ between the early-return and full paths (`scanner.py:163-190`).
- **Short reads:** `response.read(download_bytes)` (`:178`) may return fewer bytes with no drain loop → under-reported `download_kbps`.

**Robustness / debuggability**
- **Silent-everything:** every `parse`/`fetch` swallows exceptions (`parser.py` returns None/`[]`), broad `except Exception: pass` throughout `scanner.py`; `parse_generic` captures `e` at `:312` and never uses it — parse failures are un-debuggable.
- **SSRF / resource risk:** `fetch_subscription_source` (`parser.py:56-67`) has no scheme restriction when called directly (file:// etc.), no `response.read()` size limit → memory exhaustion / local-file read.
- **SNI = host fallback** (`parser.py:119/295`) may send an IP as SNI → TLS handshake failures / false-negatives.
- **`security_mode==''` + vless + port≠443 → `none`** even when server expects reality/tls → false-negative.

**Dead / vestigial code (confusion tax)**
- Entire sing-box chain; `Scanner.process_link`/`prepare_link`/`_fast_core_test` (`scanner.py:316-379`); `ui.check_pause_and_stop` (`:703`), `add_subscription_source` alias (`:654`); `configs.py` hysteria branch `:158-188` + unused `os` import `:1`; `as_completed` import in `ui.py`.
- Dead hysteria/2: listed as supported yet universally rejected.

**Build / packaging**
- Dual build definitions (`.spec` vs `.ps1`) drift silently; `requirements.txt` unpinned and **omits pyinstaller** → `pip install -r` yields a non-buildable env; `hiddenimports=[]` + onefile + `console=False` means any dynamic import ImportError is invisible at runtime; `upx=True` + unsigned onefile spawning `xray.exe` is a strong AV/SmartScreen false-positive trigger.
- **Temp file leakage:** `Core/temp_config_<uuid>.json` orphaned on crash/kill; `Core/*.log` grow unbounded.
- **Public repo ships live crypto wallets** in `About.md` — impersonation/supply-chain risk if forked or address-swapped.

---

*Relevant absolute paths:* `/root/xrayscan/Scan.py`, `/root/xrayscan/scanv2ray/{__init__,ui,scanner,parser,configs}.py`, `/root/xrayscan/{ScanV2Ray.spec,build_exe.ps1,requirements.txt,configtest.txt,About.md}`, `/root/xrayscan/Core/{xray/xray.exe,sing_box/sing-box.exe}`.