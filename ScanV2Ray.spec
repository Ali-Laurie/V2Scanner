# -*- mode: python ; coding: utf-8 -*-
# ScanV2Ray — PySide6 (Qt) UI, one-file build.
# Entry: Scan_qt.py -> scanv2ray.main_qt -> scanv2ray.ui_qt (PySide6).
# PyInstaller's bundled PySide6 hook auto-collects the Qt libraries/plugins.

a = Analysis(
    ['Scan_qt.py'],
    pathex=[],
    binaries=[],
    datas=[('About.md', '.'), ('scanv2ray', 'scanv2ray'), ('Core', 'Core')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Legacy tkinter UI is no longer built; other Qt bindings would clash.
    excludes=['tkinter', 'customtkinter', 'PyQt5', 'PyQt6', 'PySide2'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ScanV2Ray',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX can corrupt Qt6 DLLs and yield an exe that won't launch -> keep it off.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
