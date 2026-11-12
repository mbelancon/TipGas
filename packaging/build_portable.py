"""
Build the TipGas portable app with PyInstaller (one folder, no console) and zip it.

    python packaging/build_portable.py [--firmware path/to/TipGas_F411.hex]

Output: dist/TipGas-<version>-<platform>-portable.zip containing
    TipGas-<version>/TipGas(.exe), _internal/ (libraries), firmware/, LEIA-ME_README.txt, LICENSE.txt
Run it on the target OS (Windows build on Windows).
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IFACE = os.path.join(ROOT, "interface")
sys.path.insert(0, IFACE)
from tipgas_core import APP_VERSION  # noqa: E402

# Qt modules the app does not use (saves ~100 MB)
EXCLUDES = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel", "PySide6.QtMultimedia",
    "PySide6.QtNetwork", "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
    "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSensors", "PySide6.QtSerialPort",
    "tkinter", "matplotlib", "scipy", "pandas", "IPython", "pytest", "PyQt5", "PyQt6",
    "pyqtgraph.opengl", "OpenGL", "yaml",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--firmware", nargs="*", default=[], help="firmware files to include (.hex/.bin)")
    args = ap.parse_args()

    work = os.path.join(ROOT, "build_portable")
    dist = os.path.join(ROOT, "dist")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(dist, exist_ok=True)

    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
           "--name", "TipGas", "--distpath", os.path.join(work, "app"), "--workpath", os.path.join(work, "tmp"),
           "--specpath", work, "--paths", IFACE]
    for m in EXCLUDES:
        cmd += ["--exclude-module", m]
    cmd.append(os.path.join(IFACE, "TipGas.py"))
    print(" ".join(cmd))
    subprocess.check_call(cmd)

    # flatten: TipGas.exe and _internal/ at the top of the package
    pkg = os.path.join(work, "pkg")
    shutil.move(os.path.join(work, "app", "TipGas"), pkg)
    # drop the bulky Qt translations and unused plugins
    for root, dirs, files in os.walk(pkg):
        for d in list(dirs):
            if d in ("translations", "qml") or (os.path.basename(root) == "plugins" and d in (
                    "multimedia", "sqldrivers", "networkinformation", "tls", "qmltooling")):
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                dirs.remove(d)

    if args.firmware:
        fw = os.path.join(pkg, "firmware")
        os.makedirs(fw, exist_ok=True)
        for f in args.firmware:
            shutil.copy2(f, fw)
        shutil.copy2(os.path.join(ROOT, "docs", "flashing.md"), fw)
    shutil.copy2(os.path.join(ROOT, "packaging", "LEIA-ME_README.txt"), pkg)
    shutil.copy2(os.path.join(ROOT, "LICENSE"), os.path.join(pkg, "LICENSE.txt"))

    plat = {"Windows": "windows", "Darwin": "macos"}.get(platform.system(), "linux")
    base = os.path.join(dist, f"TipGas-{APP_VERSION}-{plat}-portable")
    # zip with a top-level folder TipGas-<version>/
    top = f"TipGas-{APP_VERSION}"
    os.rename(pkg, os.path.join(work, top))
    out = shutil.make_archive(base, "zip", work, top)
    print("created", out, f"{os.path.getsize(out) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
