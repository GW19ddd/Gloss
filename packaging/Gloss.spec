# PyInstaller recipe for the portable, single-file Windows application.
from pathlib import Path


project_root = Path(SPECPATH).parent

a = Analysis(
    [str(project_root / "packaging" / "windows_launcher.py")],
    pathex=[str(project_root / "backend")],
    binaries=[],
    datas=[
        (str(project_root / "frontend" / "dist"), "frontend/dist"),
        (str(project_root / "packaging" / "gloss.ico"), "packaging"),
    ],
    hiddenimports=[
        "webview",
        "webview.platforms.edgechromium",
        "webview.platforms.winforms",
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Gloss does not use packaging/build APIs at runtime. Excluding these also
    # avoids PyInstaller's pkg_resources hook pulling setuptools' optional
    # ``backports`` namespace into the portable executable.
    excludes=[
        "pkg_resources",
        "setuptools",
        "_distutils_hack",
        # Gloss deliberately uses Edge WebView2. Do not let Qt packages from
        # the Python installation influence the frozen desktop application.
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "webview.platforms.qt",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Gloss",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / "packaging" / "gloss.ico"),
)
