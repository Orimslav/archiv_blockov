# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — single-file, no console, QtCharts + bcrypt collected."""

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# bcrypt 5.x ships a Rust extension — collect its binaries + data explicitly.
bcrypt_datas, bcrypt_binaries, bcrypt_hidden = collect_all("bcrypt")

hiddenimports = (
    collect_submodules("PySide6.QtCharts")
    + bcrypt_hidden
    + ["qrcode", "PIL", "openpyxl", "reportlab", "requests"]
)

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=bcrypt_binaries,
    datas=[
        ("assets/logo.png", "assets"),
        ("assets/logo.ico", "assets"),
        ("assets/kofi_icon.png", "assets"),
    ] + bcrypt_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ArchivBlockov",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=".",
    console=False,
    icon="assets/logo.ico",
)
