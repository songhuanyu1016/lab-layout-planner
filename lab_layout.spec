# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Lab Layout Planner (one-folder build).
# Build with:  build_exe.bat   (or: pyinstaller --noconfirm lab_layout.spec)
#
# Output: dist\LabLayoutPlanner\LabLayoutPlanner.exe
#         dist\LabLayoutPlanner\Library\      <- copied by build_exe.bat
#         dist\LabLayoutPlanner\_internal\    <- bundled Python + libraries

from PyInstaller.utils.hooks import collect_all

datas = [("assets/icon.ico", "assets")]
binaries = []
hiddenimports = []

# cadquery / OpenCascade (OCP) / casadi ship many native DLLs and data files
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
    icon="assets/icon.ico",
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
