# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for Amue KeyFlow (Windows, onedir)."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).parent
ICON = ROOT / "app" / "resources" / "icons" / "amue_keyflow.ico"
VERSION_FILE = Path(SPECPATH) / "version_info.txt"

# pedalboard ships JUCE as DLLs; sounddevice ships PortAudio as package data.
audio_binaries = collect_dynamic_libs("pedalboard")
audio_datas = collect_data_files("sounddevice") + collect_data_files("pedalboard")

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=audio_binaries,
    datas=[(str(ROOT / "app" / "resources"), "app/resources")] + audio_datas,
    hiddenimports=["PySide6.QtSvg", "numpy", "sounddevice", "pedalboard"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AmueKeyFlow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
    version=str(VERSION_FILE) if VERSION_FILE.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AmueKeyFlow",
)
