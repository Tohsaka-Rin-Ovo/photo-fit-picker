# -*- mode: python ; coding: utf-8 -*-

import sys

from PyInstaller.utils.hooks import collect_all

heif_data, heif_binaries, heif_hidden = collect_all("pillow_heif")
raw_data, raw_binaries, raw_hidden = collect_all("rawpy")
qta_data, qta_binaries, qta_hidden = collect_all("qtawesome")

a = Analysis(
    ["run_app.py"],
    pathex=["src"],
    binaries=heif_binaries + raw_binaries + qta_binaries,
    datas=heif_data + raw_data + qta_data + [("demo-photos", "demo-photos")],
    hiddenimports=heif_hidden + raw_hidden + qta_hidden + ["photo_fit_picker.ui"],
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="PhotoFitPicker",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        icon="assets/app.icns",
    )
    collected = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        name="PhotoFitPicker",
    )
    app = BUNDLE(
        collected,
        name="拾影.app",
        icon="assets/app.icns",
        bundle_identifier="com.photofitpicker.app",
        version="0.4.0",
    )
else:
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
        icon="assets/app.ico",
    )
