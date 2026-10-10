# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: one-file ResumeCheck (launcher + FastAPI + bundled UI)."""
import os
from pathlib import Path

HERE = Path(SPECPATH)  # noqa: F821
SOURCE = HERE.parent / "source"
ICON = HERE / "assets" / "icon.ico"
ICON_ICNS = HERE / "assets" / "icon.icns"

datas = [
    (str(SOURCE / "frontend"), "frontend"),
]

binaries = []
hiddenimports = [
    "backend.app.main",
    "backend.app.paths",
    "backend.app.routes_runs",
    "backend.app.runner",
    "backend.app.uploads",
    "backend.app.extraction",
    "backend.app.qualification",
    "backend.app.output_writer",
    "backend.app.report",
    "backend.app.locale",
    "backend.app.models",
    "backend.app.text_normalization",
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan.on",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "pypdf",
    "docx",
    "openpyxl",
    "jdatetime",
    "multipart",
]

a = Analysis(
    [str(HERE / "launcher.py")],
    pathex=[str(SOURCE)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter.test", "unittest", "pytest", "reportlab"],
    noarchive=False,
)
pyz = PYZ(a.pure)

import sys as _sys

is_win = os.name == "nt"
is_mac = _sys.platform == "darwin"
icon = str(ICON) if ICON.is_file() else None

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ResumeCheck",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon if is_win else None,
)
if is_mac:
    app = BUNDLE(
        exe,
        name="ResumeCheck.app",
        icon=str(ICON_ICNS) if ICON_ICNS.is_file() else None,
        bundle_identifier="com.resumecheck.app",
        info_plist={
            "NSPrincipalClass": "NSApplication",
            "NSAppleScriptEnabled": False,
            "CFBundleShortVersionString": "1.0.0",
            "LSMinimumSystemVersion": "11.0",
        },
    )
