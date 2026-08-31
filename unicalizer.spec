# -*- mode: python ; coding: utf-8 -*-
"""Сборка приложения через PyInstaller. Работает и на macOS, и на Windows.

    pyinstaller --noconfirm unicalizer.spec
"""

import sys
from pathlib import Path

MAC = sys.platform == "darwin"
ICON = "assets/icon.icns" if MAC else "assets/icon.ico"

# ffmpeg вкладываем в сборку, если он положен в bin рядом с исходниками.
# Тогда программа работает на любом компьютере, где ничего не установлено.
extra = []
if Path("bin").is_dir():
    extra.append(("bin", "bin"))

analysis = Analysis(
    ["app.py"],
    pathex=["."],
    binaries=[],
    # Иконки и пресеты кладём внутрь приложения, чтобы оно работало
    # само по себе, без папки с исходниками рядом.
    datas=[("assets", "assets"), ("presets", "presets")] + extra,
    hiddenimports=[],
    hookspath=[],
    excludes=["tkinter", "matplotlib", "numpy", "PySide6.QtWebEngineCore"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Video Unicalizer",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=ICON,
)

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="Video Unicalizer",
)

if MAC:
    app = BUNDLE(
        collection,
        name="Video Unicalizer.app",
        icon=ICON,
        bundle_identifier="me.ytcartell.unicalizer",
        info_plist={
            "CFBundleName": "Video Unicalizer",
            "CFBundleDisplayName": "Video Unicalizer",
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": "t.me/YT_cartell",
        },
    )
