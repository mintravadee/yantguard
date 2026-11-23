# PyInstaller recipe. Build with scripts\build_desktop.bat (output: dist\YantGuard\YantGuard.exe).
from PyInstaller.utils.hooks import collect_submodules

root = SPECPATH.replace("\\desktop", "").replace("/desktop", "")

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("app")
    + collect_submodules("scripts")
    + ["webview.platforms.edgechromium", "webview.platforms.winforms", "clr_loader", "pythonnet"]
)

a = Analysis(
    [root + "/desktop/yantguard_desktop.py"],
    pathex=[root],
    datas=[(root + "/app/dashboard/static", "app/dashboard/static"),
           (root + "/.env.example", ".")],
    hiddenimports=hidden,
    excludes=["tkinter", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="YantGuard", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="YantGuard")
