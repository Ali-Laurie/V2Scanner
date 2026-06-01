# ScanV2Ray

ScanV2Ray is a Windows desktop tool for importing proxy configs, validating them against Xray, and exporting the working results.

## What it does

- Imports links directly, from pasted text, subscription URLs, base64 text, JSON blobs, and local text files.
- Normalizes supported proxy formats: `vmess`, `vless`, `trojan`, `ss`, `hysteria`, and `hysteria2`.
- Builds Xray-compatible JSON configs.
- Validates configs with `xray.exe -test -c`.
- Runs a real Xray process through a local HTTP proxy and measures reachability, latency, and download speed.
- Exports results as JSON, CSV, and TXT.

## Current workflow

The app now uses a simpler Xray-first pipeline:

1. Quick precheck: detects obvious unreachable endpoints early.
2. Xray JSON validation: checks whether the generated config is accepted by the Xray core.
3. Real Xray test: launches `xray.exe`, routes traffic through `127.0.0.1`, and measures real connectivity.
4. Result scoring: classifies configs as `fast`, `medium`, `slow`, or `dead`.

This keeps the scan faster and reduces false positives.

## UI overview

The interface is intentionally compact:

- `Sources`: paste links, subscription URLs, base64 text, JSON, or local file paths.
- `Scan mode`: choose `Quick` or `Full`.
- `Advanced settings`: optional concurrency and timeout controls.
- `Results`: copy/export actions and live classification counters.

## Requirements

- Windows
- Python 3.12+
- `customtkinter`
- `Core/xray/xray.exe`

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python Scan.py
```

## Recommended settings

- `Quick` mode: best for large batches and fast triage.
- `Full` mode: best when you want more reliable final verification.
- `Concurrency`: start with `12` to `16` for normal systems.
- `Timeout`: `3000` to `6000` ms is usually enough.

If you push concurrency too high, the app may become noisier because each test can launch its own Xray process and make real network requests.

## Output files

When you choose an output folder, the app writes results into `Scan_Results/`:

- `scan_results.json`
- `scan_results.csv`
- `fast_verified.txt`
- `medium_verified.txt`
- `slow_verified.txt`
- `dead.txt`
- `active_connected_configs.txt`
- `scan_log.txt`

## Project structure

```text
Scanv2ray/
|-- Scan.py
|-- scanv2ray/
|   |-- __init__.py
|   |-- ui.py
|   |-- scanner.py
|   |-- parser.py
|   `-- configs.py
|-- Core/
|   |-- xray/
|   |   `-- xray.exe
|   `-- sing_box/
|       `-- sing-box.exe
|-- requirements.txt
`-- README.md
```

## Notes

- The app is now designed around Xray as the primary validation and execution core.
- Sing-box binaries may still be present in the repository, but the runtime pipeline is Xray-first.
- Temporary config files are created under `Core/` and ignored by git.

## License

Personal use only.

