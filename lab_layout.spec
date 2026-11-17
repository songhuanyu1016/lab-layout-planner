# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Lab Layout Planner (one-folder build, Windows + macOS).
# Build with:  build_exe.bat (Windows)  /  ./build_mac.sh (macOS)
#
# Windows output: dist\LabLayoutPlanner\LabLayoutPlanner.exe (+ _internal\)
# macOS output:   dist/LabLayoutPlanner.app
# The build scripts then place a Library folder next to the exe / .app.

import sys
from PyInstaller.utils.hooks import collect_all

IS_MAC = sys.platform == "darwin"
ICON = "assets/icon.icns" if IS_MAC else "assets/icon.ico"

datas = [("assets/icon.ico", "assets"), ("assets/icon.png", "assets")]
binaries = []
hiddenimports = []

# cadquery / OpenCascade (OCP) / casadi ship many native libraries and data files
for pkg in ("cadquery", "OCP", "casadi"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["lab_layout.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["matplotlib.backends.backend_agg"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "IPython", "jupyter", "notebook", "trame",
              "trame_vtk", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LabLayoutPlanner",
    icon=ICON,
    console=False,
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="LabLayoutPlanner",
    upx=False,
)

if IS_MAC:
    app = BUNDLE(
        coll,
        name="LabLayoutPlanner.app",
        icon=ICON,
        bundle_identifier="io.github.lablayoutplanner",
        info_plist={
            "CFBundleDisplayName": "Lab Layout Planner",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
        },
    )
