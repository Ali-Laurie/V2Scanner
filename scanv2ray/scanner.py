import json
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from urllib.request import ProxyHandler, build_opener, Request

from . import configs
from . import parser

# Suppress the console window every xray child would otherwise flash on Windows.
# 0 on non-Windows so Popen stays valid there (also unblocks headless/server use).
CREATE_NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0


def get_free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Scanner:
    def __init__(self, xray_path, singbox_path):
        self.xray_path = xray_path
        self.singbox_path = singbox_path
        self.speed_test_semaphore = threading.BoundedSemaphore(6)
        self._active_procs = set()
        self._proc_lock = threading.Lock()
        self._aborted = False
        # Set by ui.run_scan before each scan (features A and B).
        self.detect_country = False
        self.site_check = False
        self.site_strict = False
        self.site_targets = []

    def request_abort(self):
        # mark aborted and kill every currently-running xray process immediately
        self._aborted = True
        with self._proc_lock:
            procs = list(self._active_procs)
        for p in procs:
            try:
                p.kill()
            except Exception:
                pass

    def reset_abort(self):
        self._aborted = False

    def set_speed_test_limit(self, limit):
        self.speed_test_semaphore = threading.BoundedSemaphore(max(1, int(limit)))

    def _write_config(self, config_data):
        config_filename = f'temp_config_{uuid.uuid4().hex}.json'
        config_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Core', config_filename))
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f)
        return config_path

    def _run_core_process(self, args):
        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW
            )
            time.sleep(0.2)
            if proc.poll() is not None:
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    debug_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Core', 'process_launch_error.log'))
                    with open(debug_path, 'a', encoding='utf-8') as df:
                        df.write(f"[EARLY_EXIT] rc={proc.returncode} args={args}\n")
                except Exception:
                    pass
                return None
            with self._proc_lock:
                self._active_procs.add(proc)
            return proc
        except Exception:
            try:
                # write debug info
                debug_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Core', 'process_launch_error.log'))
                with open(debug_path, 'a', encoding='utf-8') as df:
                    df.write(f"[RUN_ERROR] args={args}\n")
            except Exception:
                pass
            return None

    def _cleanup_process(self, proc, config_path):
        if proc is not None:
            with self._proc_lock:
                self._active_procs.discard(proc)
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=1)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        try:
            if os.path.exists(config_path):
                os.remove(config_path)
        except Exception:
            pass

    def _wait_for_local_port(self, port, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._aborted:
                return False
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=0.5):
                    return True
            except Exception:
                time.sleep(0.1)
        return False

    def _validate_xray_config(self, binary_path, config_path):
        # Run `xray -test` via a REGISTERED Popen so request_abort() can kill an
        # in-flight validation immediately on stop (subprocess.run could not be).
        try:
            proc = subprocess.Popen(
                [binary_path, '-test', '-c', config_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW
            )
        except Exception:
            return False
        with self._proc_lock:
            self._active_procs.add(proc)
        try:
            try:
                out, err = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                    proc.communicate()
                except Exception:
                    pass
                return False
            if proc.returncode != 0:
                try:
                    debug_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Core', 'xray_config_test.log'))
                    with open(debug_path, 'a', encoding='utf-8') as df:
                        df.write(f"[XRAY_TEST_FAIL] cmd={[binary_path, '-test', '-c', config_path]}\n")
                        df.write(out.decode('utf-8', errors='ignore') + '\n')
                        df.write(err.decode('utf-8', errors='ignore') + '\n')
                except Exception:
                    pass
            return proc.returncode == 0
        except Exception:
            try:
                debug_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Core', 'xray_config_test.log'))
                with open(debug_path, 'a', encoding='utf-8') as df:
                    df.write(f"[XRAY_TEST_EXCEPTION] binary={binary_path} config={config_path}\n")
            except Exception:
                pass
            return False
        finally:
            with self._proc_lock:
                self._active_procs.discard(proc)

    def _validate_singbox_config(self, binary_path, config_path):
        # Mirror _validate_xray_config: run `sing-box check` via a REGISTERED
        # Popen so request_abort() can kill an in-flight validation immediately.
        try:
            proc = subprocess.Popen(
                [binary_path, 'check', '-c', config_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW
            )
        except Exception:
            return False
        with self._proc_lock:
            self._active_procs.add(proc)
        try:
            try:
                out, err = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                    proc.communicate()
                except Exception:
                    pass
                return False
            if proc.returncode != 0:
                try:
                    debug_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Core', 'singbox_config_test.log'))
                    with open(debug_path, 'a', encoding='utf-8') as df:
                        df.write(f"[SINGBOX_TEST_FAIL] cmd={[binary_path, 'check', '-c', config_path]}\n")
                        df.write(out.decode('utf-8', errors='ignore') + '\n')
                        df.write(err.decode('utf-8', errors='ignore') + '\n')
                except Exception:
                    pass
            return proc.returncode == 0
        except Exception:
            try:
                debug_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Core', 'singbox_config_test.log'))
                with open(debug_path, 'a', encoding='utf-8') as df:
                    df.write(f"[SINGBOX_TEST_EXCEPTION] binary={binary_path} config={config_path}\n")
            except Exception:
                pass
            return False
        finally:
            with self._proc_lock:
                self._active_procs.discard(proc)

    def _measure_proxy(self, local_port, timeout, quick=False):
        proxy_url = f'http://127.0.0.1:{local_port}'
        proxy_handler = ProxyHandler({'http': proxy_url, 'https': proxy_url})
        opener = build_opener(proxy_handler)

        endpoints = [
            'https://www.gstatic.com/generate_204',
            'https://www.cloudflare.com/cdn-cgi/trace',
            'https://www.google.com/generate_204'
        ]
        if quick:
            # Probe the cloudflare trace first when we want exit country, so the
            # `if quick: break` after the first success still reads the trace body.
            if self.detect_country:
                endpoints = ['https://www.cloudflare.com/cdn-cgi/trace',
                             'https://www.gstatic.com/generate_204']
            else:
                endpoints = endpoints[:2]
        endpoint_timeout = min(timeout, 2.5) if quick else timeout

        metrics = {
            'requests': 0,
            'successes': 0,
            'latencies': [],
            'first_response_ms': None,
            'download_kbps': 0.0,
            'error_count': 0,
            'exit_ip': '',
            'exit_country': '',
            'sites_ok': []
        }

        for endpoint in endpoints:
            if self._aborted:
                break
            req = Request(endpoint, headers={'User-Agent': 'Mozilla/5.0'})
            metrics['requests'] += 1
            start_time = time.time()
            try:
                with opener.open(req, timeout=endpoint_timeout) as response:
                    status = response.getcode()
                    elapsed = int((time.time() - start_time) * 1000)
                    if status in (200, 204):
                        metrics['successes'] += 1
                        metrics['latencies'].append(elapsed)
                        if metrics['first_response_ms'] is None:
                            metrics['first_response_ms'] = elapsed
                        # Feature A: parse exit ip/country from the cloudflare trace body.
                        if (self.detect_country and status == 200
                                and 'cdn-cgi/trace' in endpoint
                                and not metrics['exit_ip'] and not metrics['exit_country']):
                            try:
                                body = response.read(4096).decode('utf-8', errors='ignore')
                                for line in body.splitlines():
                                    if line.startswith('ip='):
                                        metrics['exit_ip'] = line[3:].strip()
                                    elif line.startswith('loc='):
                                        metrics['exit_country'] = line[4:].strip()
                            except Exception:
                                pass
                        if quick:
                            break
                    else:
                        metrics['error_count'] += 1
            except Exception:
                metrics['error_count'] += 1

        # Feature B: site reachability probes, only for connectable configs.
        if (self.site_check and self.site_targets and metrics['successes'] > 0
                and not self._aborted):
            site_timeout = min(timeout, 3.0)
            for name, url in self.site_targets:
                if self._aborted:
                    break
                try:
                    site_req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                    with opener.open(site_req, timeout=site_timeout) as site_resp:
                        site_status = site_resp.getcode()
                        if site_status is None or site_status < 400:
                            metrics['sites_ok'].append(name)
                except Exception:
                    pass

        # success_ratio reflects the connectivity PROBE requests only, so it
        # means the same thing on both the early-return and full paths. The
        # download outcome is tracked separately below.
        connectivity_ratio = metrics['successes'] / metrics['requests'] if metrics['requests'] else 0.0
        metrics['success_ratio'] = connectivity_ratio
        metrics['download_requested'] = False
        metrics['download_success'] = False
        if metrics['successes'] == 0:
            metrics['average_latency'] = int(sum(metrics['latencies']) / len(metrics['latencies'])) if metrics['latencies'] else None
            return metrics

        if self._aborted:
            metrics['average_latency'] = int(sum(metrics['latencies']) / len(metrics['latencies'])) if metrics['latencies'] else None
            return metrics

        download_bytes = 10000 if quick else 50000
        download_url = f'https://speed.cloudflare.com/__down?bytes={download_bytes}'
        metrics['download_requested'] = True
        dl_start = time.time()
        try:
            with self.speed_test_semaphore:
                dl_req = Request(download_url, headers={'User-Agent': 'Mozilla/5.0'})
                download_timeout = max(endpoint_timeout, 4.0) if quick else max(timeout, 8.0)
                total_bytes = 0
                with opener.open(dl_req, timeout=download_timeout) as response:
                    while total_bytes < download_bytes:
                        chunk = response.read(min(65536, download_bytes - total_bytes))
                        if not chunk:
                            break
                        total_bytes += len(chunk)
            duration = time.time() - dl_start
            if duration > 0 and total_bytes > 0:
                metrics['download_kbps'] = total_bytes / 1024 / duration
                metrics['download_success'] = True
                if metrics['first_response_ms'] is None:
                    metrics['first_response_ms'] = int(duration * 1000)
            else:
                metrics['error_count'] += 1
        except Exception:
            metrics['error_count'] += 1

        metrics['average_latency'] = int(sum(metrics['latencies']) / len(metrics['latencies'])) if metrics['latencies'] else None
        return metrics

    def _score_metrics(self, metrics):
        if metrics['success_ratio'] < 0.3 and metrics['download_kbps'] < 1.0:
            return 0.0, 'dead'

        speed_score = min(metrics['download_kbps'] / 200.0 * 100.0, 100.0)
        delay = metrics.get('first_response_ms') or 1000
        delay_score = max(0.0, min(1.0, (1000.0 - delay) / 1000.0)) * 100.0
        stability_score = metrics['success_ratio'] * 100.0
        success_score = 100.0 if metrics['success_ratio'] >= 0.9 else 50.0 if metrics['success_ratio'] >= 0.75 else 0.0

        score = speed_score * 0.4 + delay_score * 0.3 + stability_score * 0.2 + success_score * 0.1
        if score >= 75.0:
            classification = 'fast'
        elif score >= 55.0:
            classification = 'medium'
        else:
            classification = 'slow'

        return round(score, 2), classification

    def _build_benchmark_result(self, link, parsed, engine, metrics):
        score, classification = self._score_metrics(metrics)
        return {
            'method': engine,
            'proto': parsed['proto'],
            'link': link,
            'remark': parsed.get('remark') or 'NoRemark',
            'latency': metrics.get('first_response_ms') or 0,
            'speed': metrics.get('download_kbps', 0.0),
            'success_ratio': round(metrics.get('success_ratio', 0.0), 2),
            'average_latency': metrics.get('average_latency'),
            'score': score,
            'classification': classification,
            'exit_ip': metrics.get('exit_ip', ''),
            'exit_country': metrics.get('exit_country', ''),
            'sites_ok': metrics.get('sites_ok', [])
        }

    def _build_config(self, parsed, local_port, engine):
        if engine == 'singbox':
            return configs.make_singbox_config(parsed, local_port)
        return configs.make_xray_config(parsed, local_port)

    def _validate_config(self, binary_path, config_path, engine):
        if engine == 'singbox':
            return self._validate_singbox_config(binary_path, config_path)
        return self._validate_xray_config(binary_path, config_path)

    def _test_core(self, parsed, timeout, binary_path, engine, quick=False, prevalidated=False):
        if not os.path.exists(binary_path):
            return None

        startup_timeout = 2.0 if quick else min(max(timeout, 2.0), 4.0)

        # Retry the launch ONCE with a freshly acquired port if the core fails
        # to start or the local port never opens (mitigates get_free_port races).
        for attempt in range(2):
            local_port = get_free_port()
            config_data = self._build_config(parsed, local_port, engine)
            if not config_data:
                return None

            config_path = self._write_config(config_data)
            if self._aborted:
                self._cleanup_process(None, config_path)
                return None
            if not prevalidated and not self._validate_config(binary_path, config_path, engine):
                self._cleanup_process(None, config_path)
                return None

            if engine == 'singbox':
                args = [binary_path, 'run', '-c', config_path]
            else:
                args = [binary_path, '-c', config_path]
            proc = self._run_core_process(args)
            if not proc:
                self._cleanup_process(proc, config_path)
                if attempt == 0:
                    continue
                return None

            if not self._wait_for_local_port(local_port, timeout=startup_timeout):
                self._cleanup_process(proc, config_path)
                if attempt == 0:
                    continue
                return None

            try:
                metrics = self._measure_proxy(local_port, timeout, quick=quick)
                if metrics['success_ratio'] < 0.3 and metrics['download_kbps'] < 1.0:
                    return None

                # Strict site-check: the config must reach EVERY target site or
                # it is treated as dead. Only enforced when strict mode is on.
                if self.site_check and self.site_strict and self.site_targets:
                    required = {name for name, _ in self.site_targets}
                    if not required.issubset(set(metrics.get('sites_ok', []))):
                        return None

                return self._build_benchmark_result(parsed.get('link', ''), parsed, engine, metrics)
            finally:
                self._cleanup_process(proc, config_path)

        return None

    def precheck_link(self, link, timeout=0.7):
        parsed = parser.parse_link(link)
        if not parsed or not parsed.get('host') or not parsed.get('port'):
            return {'ok': False, 'link': link, 'reason': 'parse_failed'}

        valid, reason = parser.validate_parsed_config(parsed)
        if not valid:
            return {'ok': False, 'link': link, 'reason': reason or 'parser_validation_failed'}

        parsed['link'] = link

        # sing-box protocols (hysteria/hysteria2/tuic/anytls/wireguard) are UDP/QUIC
        # based, so a TCP reachability probe is meaningless (and would falsely reject
        # them). Skip the TCP precheck and let the real sing-box test decide liveness.
        if configs.engine_for(parsed.get('proto')) == 'singbox':
            return {'ok': True, 'link': link, 'parsed': parsed}

        try:
            with socket.create_connection((parsed['host'], parsed['port']), timeout=timeout):
                return {'ok': True, 'link': link, 'parsed': parsed}
        except socket.gaierror:
            return {'ok': False, 'link': link, 'reason': 'tcp_dns_failed'}
        except TimeoutError:
            return {'ok': False, 'link': link, 'reason': 'tcp_timeout'}
        except OSError as e:
            return {'ok': False, 'link': link, 'reason': f'tcp_failed:{getattr(e, "errno", "") or e.__class__.__name__}'}

    def validate_prechecked_link(self, item):
        parsed = item.get('parsed')
        link = item.get('link', '')
        if not parsed:
            return {'ok': False, 'link': link, 'reason': item.get('reason', 'parse_failed')}

        if not os.path.exists(self.xray_path):
            return {'ok': False, 'link': link, 'reason': 'xray_missing'}

        config_data = configs.make_xray_config(parsed, get_free_port())
        if not config_data:
            return {'ok': False, 'link': link, 'reason': 'xray_unsupported_protocol'}

        config_path = self._write_config(config_data)
        try:
            if not self._validate_xray_config(self.xray_path, config_path):
                return {'ok': False, 'link': link, 'reason': 'xray_json_invalid'}
        finally:
            self._cleanup_process(None, config_path)

        return {'ok': True, 'link': link, 'parsed': parsed}

    def _fast_core_test(self, parsed, timeout):
        if os.path.exists(self.xray_path):
            return self._test_core(parsed, timeout, self.xray_path, 'xray', quick=True)
        return None

    def prepare_link(self, link):
        parsed = parser.parse_link(link)
        if not parsed or not parsed.get('host') or not parsed.get('port'):
            return {'ok': False, 'link': link, 'reason': 'parse_failed'}

        valid, reason = parser.validate_parsed_config(parsed)
        if not valid:
            return {'ok': False, 'link': link, 'reason': reason or 'parser_validation_failed'}

        parsed['link'] = link
        if not os.path.exists(self.xray_path):
            return {'ok': False, 'link': link, 'reason': 'xray_missing'}

        config_data = configs.make_xray_config(parsed, get_free_port())
        if not config_data:
            return {'ok': False, 'link': link, 'reason': 'xray_unsupported_protocol'}

        config_path = self._write_config(config_data)
        try:
            if not self._validate_xray_config(self.xray_path, config_path):
                return {'ok': False, 'link': link, 'reason': 'xray_json_invalid'}
        finally:
            self._cleanup_process(None, config_path)

        return {'ok': True, 'link': link, 'parsed': parsed}

    def test_prepared_link(self, prepared, timeout, method):
        parsed = prepared.get('parsed')
        if not parsed:
            return None
        quick = method == 'fast'
        result = self._test_core(parsed, timeout, self.xray_path, 'xray', quick=quick, prevalidated=True)
        if result:
            result['method'] = method
        return result

    def validate_and_test(self, item, timeout, method):
        parsed = item.get('parsed')
        link = item.get('link', '')
        if self._aborted or not parsed:
            return None
        engine = configs.engine_for(parsed['proto'])
        binary = self.singbox_path if engine == 'singbox' else self.xray_path
        if not os.path.exists(binary):
            return None
        quick = (method != 'xray')   # 'fast' -> quick=True ; 'xray' -> quick=False
        # _test_core with prevalidated=False performs core validation, then launches & measures.
        result = self._test_core(parsed, timeout, binary, engine, quick=quick, prevalidated=False)
        if result:
            result['method'] = method   # preserve the run's method label ('fast'/'xray')
        return result

    def process_link(self, link, timeout, methods):
        parsed = parser.parse_link(link)
        if not parsed or not parsed.get('host') or not parsed.get('port'):
            return []

        valid, reason = parser.validate_parsed_config(parsed)
        if not valid:
            return []

        parsed['link'] = link
        results = []

        if 'fast' in methods:
            core_result = self._fast_core_test(parsed, timeout)
            if core_result:
                results.append({**core_result, 'method': 'fast'})

        if 'xray' in methods and os.path.exists(self.xray_path):
            core_result = self._test_core(parsed, timeout, self.xray_path, 'xray')
            if core_result:
                results.append(core_result)

        return results
