# -*- mode: python ; coding: utf-8 -*-

import sys

from PyInstaller.utils.hooks import collect_all

heif_data, heif_binaries, heif_hidden = collect_all("pillow_heif")
raw_data, raw_binaries, raw_hidden = collect_all("rawpy")

a = Analysis(
    ["run_app.py"],
    pathex=["src"],
    binaries=heif_binaries + raw_binaries,
    datas=heif_data + raw_data,
    hiddenimports=heif_hidden + raw_hidden + ["photo_fit_picker.ui"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PhotoFitPicker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="拾影.app",
        bundle_identifier="com.photofitpicker.app",
    )
