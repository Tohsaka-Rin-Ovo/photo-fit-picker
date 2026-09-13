# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

heif_data, heif_binaries, heif_hidden = collect_all("pillow_heif")
raw_data, raw_binaries, raw_hidden = collect_all("rawpy")
exif_data, exif_binaries, exif_hidden = collect_all("exifread")
opencv_data, opencv_binaries, opencv_hidden = collect_all("cv2")

a = Analysis(
    ["run_engine.py"],
    pathex=["src"],
    binaries=heif_binaries + raw_binaries + exif_binaries + opencv_binaries,
    datas=heif_data + raw_data + exif_data + opencv_data,
    hiddenimports=heif_hidden + raw_hidden + exif_hidden + opencv_hidden,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="photo-engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
