import json
import os
import socket
import subprocess
import time
import uuid
from urllib.request import ProxyHandler, build_opener, Request

from . import configs
from . import parser


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

    def _write_config(self, config_data):
        config_filename = f'temp_config_{uuid.uuid4().hex}.json'
        config_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Core', config_filename))
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f)
        return config_path

    def _run_core_process(self, args):
        CREATE_NO_WINDOW = 0x08000000
        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW
            )
            time.sleep(0.8)
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
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=0.5):
                    return True
            except Exception:
                time.sleep(0.1)
        return False

    def _validate_xray_config(self, binary_path, config_path):
        try:
            result = subprocess.run([binary_path, '-test', '-c', config_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            if result.returncode != 0:
                try:
                    debug_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Core', 'xray_config_test.log'))
                    with open(debug_path, 'a', encoding='utf-8') as df:
                        df.write(f"[XRAY_TEST_FAIL] cmd={[binary_path, '-test', '-c', config_path]}\n")
                        df.write(result.stdout.decode('utf-8', errors='ignore') + '\n')
                        df.write(result.stderr.decode('utf-8', errors='ignore') + '\n')
                except Exception:
                    pass
            return result.returncode == 0
        except Exception:
            try:
                debug_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Core', 'xray_config_test.log'))
                with open(debug_path, 'a', encoding='utf-8') as df:
                    df.write(f"[XRAY_TEST_EXCEPTION] binary={binary_path} config={config_path}\n")
            except Exception:
                pass
            return False

    def _validate_singbox_config(self, binary_path, config_path):
        try:
            result = subprocess.run([binary_path, 'check', '-c', config_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            return result.returncode == 0
        except Exception:
            try:
                debug_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Core', 'singbox_config_test.log'))
                with open(debug_path, 'a', encoding='utf-8') as df:
                    df.write(f"[SINGBOX_TEST_EXCEPTION] binary={binary_path} config={config_path}\n")
            except Exception:
                pass
            return False

    def _measure_proxy(self, local_port, timeout, quick=False):
        proxy_url = f'http://127.0.0.1:{local_port}'
        proxy_handler = ProxyHandler({'http': proxy_url, 'https': proxy_url})
        opener = build_opener(proxy_handler)

        endpoints = [
            'https://www.gstatic.com/generate_204',
            'https://www.google.com/generate_204',
            'https://www.cloudflare.com/cdn-cgi/trace'
        ]
        if quick:
            endpoints = endpoints[:2]

        metrics = {
            'requests': 0,
            'successes': 0,
            'latencies': [],
            'first_response_ms': None,
            'download_kbps': 0.0,
            'error_count': 0
        }

        for endpoint in endpoints:
            req = Request(endpoint, headers={'User-Agent': 'Mozilla/5.0'})
            metrics['requests'] += 1
            start_time = time.time()
            try:
                with opener.open(req, timeout=timeout) as response:
                    status = response.getcode()
                    elapsed = int((time.time() - start_time) * 1000)
                    if status in (200, 204):
                        metrics['successes'] += 1
                        metrics['latencies'].append(elapsed)
                        if metrics['first_response_ms'] is None:
                            metrics['first_response_ms'] = elapsed
                    else:
                        metrics['error_count'] += 1
            except Exception:
                metrics['error_count'] += 1

        download_url = 'https://speed.cloudflare.com/__down?bytes=200000'
        metrics['requests'] += 1
        dl_start = time.time()
        try:
            dl_req = Request(download_url, headers={'User-Agent': 'Mozilla/5.0'})
            with opener.open(dl_req, timeout=max(timeout, 8.0)) as response:
                data = response.read(200000)
            duration = time.time() - dl_start
            if duration > 0 and len(data) > 0:
                metrics['download_kbps'] = len(data) / 1024 / duration
                metrics['successes'] += 1
                if metrics['first_response_ms'] is None:
                    metrics['first_response_ms'] = int(duration * 1000)
            else:
                metrics['error_count'] += 1
        except Exception:
            metrics['error_count'] += 1

        metrics['success_ratio'] = metrics['successes'] / metrics['requests'] if metrics['requests'] else 0.0
        metrics['average_latency'] = int(sum(metrics['latencies']) / len(metrics['latencies'])) if metrics['latencies'] else None
        return metrics

    def _score_metrics(self, metrics):
        if metrics['success_ratio'] < 0.6 or metrics['download_kbps'] < 1.0:
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
            'classification': classification
        }

    def _build_config(self, parsed, local_port, engine):
        if engine == 'xray':
            return configs.make_xray_config(parsed, local_port)
        if engine == 'singbox':
            return configs.make_singbox_config(parsed, local_port)
        return None

    def _validate_config(self, binary_path, config_path, engine):
        if engine == 'xray':
            return self._validate_xray_config(binary_path, config_path)
        return self._validate_singbox_config(binary_path, config_path)

    def _test_core(self, parsed, timeout, binary_path, engine, quick=False):
        if not os.path.exists(binary_path):
            return None

        local_port = get_free_port()
        config_data = self._build_config(parsed, local_port, engine)
        if not config_data:
            return None

        config_path = self._write_config(config_data)
        if not self._validate_config(binary_path, config_path, engine):
            self._cleanup_process(None, config_path)
            return None

        args = [binary_path, '-c', config_path] if engine == 'xray' else [binary_path, 'run', '-c', config_path]
        proc = self._run_core_process(args)
        if not proc:
            self._cleanup_process(proc, config_path)
            return None

        if not self._wait_for_local_port(local_port, timeout=max(timeout, 5.0)):
            self._cleanup_process(proc, config_path)
            return None

        metrics = self._measure_proxy(local_port, timeout, quick=quick)
        self._cleanup_process(proc, config_path)
        if metrics['success_ratio'] < 0.6 or metrics['download_kbps'] < 1.0:
            return None

        return self._build_benchmark_result(parsed.get('link', ''), parsed, engine, metrics)

    def _fast_core_test(self, parsed, timeout):
        if parsed.get('proto') == 'ss':
            if os.path.exists(self.singbox_path):
                result = self._test_core(parsed, timeout, self.singbox_path, 'singbox', quick=True)
                if result or not os.path.exists(self.xray_path):
                    return result
            if os.path.exists(self.xray_path):
                return self._test_core(parsed, timeout, self.xray_path, 'xray', quick=True)
            return None

        if os.path.exists(self.xray_path):
            return self._test_core(parsed, timeout, self.xray_path, 'xray', quick=True)
        if os.path.exists(self.singbox_path):
            return self._test_core(parsed, timeout, self.singbox_path, 'singbox', quick=True)
        return None

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

        if parsed.get('proto') == 'ss' and 'xray' in methods and 'singbox' in methods and os.path.exists(self.xray_path) and os.path.exists(self.singbox_path):
            core_result = self._test_core(parsed, timeout, self.xray_path, 'xray')
            if core_result:
                results.append(core_result)
            else:
                core_result = self._test_core(parsed, timeout, self.singbox_path, 'singbox')
                if core_result:
                    results.append(core_result)
        else:
            if 'xray' in methods and os.path.exists(self.xray_path):
                core_result = self._test_core(parsed, timeout, self.xray_path, 'xray')
                if core_result:
                    results.append(core_result)

            if 'singbox' in methods and os.path.exists(self.singbox_path):
                core_result = self._test_core(parsed, timeout, self.singbox_path, 'singbox')
                if core_result:
                    results.append(core_result)

        return results
