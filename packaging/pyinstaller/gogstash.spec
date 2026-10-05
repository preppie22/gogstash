# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import copy_metadata
import os
import sys


datas = [(os.path.join(SPECPATH, '..', '..', 'src', 'gogstash', 'icons'), 'gogstash/icons'), (os.path.join(SPECPATH, '..', 'licenses'), 'gogstash/licenses')]
datas += copy_metadata('gogstash')

# Exclude "libstdc++.so.6", "libgcc_s.so.1", "libgbm.so.1" to fix #1
excluded_files_linux = {
    "libstdc++.so.6", "libgcc_s.so.1", "libgbm.so.1",
}

# GogStash has no QML. QtWebEngine pulls these modules in, and their hooks
# copy Qt's whole QML folder plus every library it needs (3D, Charts,
# Multimedia...). The libraries WebEngine links against are still bundled.
excluded_modules = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets"
]

# Qt plugins GogStash never loads on Linux: printing, geolocation,
# touchscreens and embedded displays, image formats other than SVG (every
# icon is an SVG), platforms other than X11 and Wayland, the virtual
# keyboard, and Wayland shells nobody's desktop uses.
unused_plugin_dirs_linux = {
    "printsupport", "position", "generic", "egldeviceintegrations"
}
unused_plugins_linux = {
    "libqjpeg.so", "libqwebp.so", "libqtiff.so", "libqicns.so", "libqpdf.so",
    "libqgif.so", "libqico.so", "libqwbmp.so", "libqtga.so",
    "libqlinuxfb.so", "libqvnc.so", "libqminimal.so", "libqminimalegl.so",
    "libqeglfs.so", "libqvkkhrdisplay.so", "libqoffscreen.so",
    "libqtvirtualkeyboardplugin.so",
    "libivi-shell.so", "libqt-shell.so", "libfullscreen-shell-v1.so",
    "libwl-shell-plugin.so", "libdmabuf-server.so", "libshm-emulation-server.so",
    "libvulkan-server.so", "libdrm-egl-server.so"
}
# Libraries that only those plugins need. PyInstaller collects them along
# with the plugins and doesn't drop them when the plugins go.
plugin_only_libs_linux = {
    "libQt6Pdf.so.6", "libQt6VirtualKeyboard.so.6", "libQt6VirtualKeyboardQml.so.6",
    "libQt6EglFSDeviceIntegration.so.6", "libQt6EglFsKmsSupport.so.6",
    "libQt6WlShellIntegration.so.6", "libQt6SerialPort.so.6", "libcups.so.2"
}

# The same idea on Windows, where the files have their own names. The app
# runs on the qwindows platform with the Fusion style, so the other
# platforms and the Windows style go too. PySide6 also ships its own
# OpenSSL for Qt's networking, which GogStash doesn't use: downloads go
# through Python's OpenSSL (libssl-3.dll, kept) and WebEngine has its own.
# Names are lowercase because Windows file names aren't case sensitive.
unused_plugin_dirs_windows = {
    "position", "generic", "styles"
}
unused_plugins_windows = {
    "qgif.dll", "qicns.dll", "qico.dll", "qjpeg.dll", "qpdf.dll",
    "qtga.dll", "qtiff.dll", "qwbmp.dll", "qwebp.dll",
    "qdirect2d.dll", "qminimal.dll", "qoffscreen.dll",
    "qtvirtualkeyboardplugin.dll", "qopensslbackend.dll"
}
plugin_only_libs_windows = {
    "qt6pdf.dll", "qt6serialport.dll", "qt6virtualkeyboard.dll",
    "libssl-3-x64.dll", "libcrypto-3-x64.dll"
}

a = Analysis(
    ['launch_gogstash.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if sys.platform.startswith('linux'):
    for entry in a.binaries.copy():
        filename = os.path.basename(entry[0])
        plugin_dir = os.path.basename(os.path.dirname(entry[0]))
        is_plugin = 'plugins' in entry[0].replace('\\', '/').split('/')
        if (
            filename in excluded_files_linux or
            filename in plugin_only_libs_linux or
            (is_plugin and (plugin_dir in unused_plugin_dirs_linux or filename in unused_plugins_linux))
        ):
            a.binaries.remove(entry)
    # Each Qt library also gets a symlink next to the executable, listed
    # with the data files. Left behind, they'd point at nothing.
    for entry in a.datas.copy():
        if entry[2] == 'SYMLINK' and os.path.basename(entry[0]) in plugin_only_libs_linux:
            a.datas.remove(entry)

if sys.platform == 'win32':
    for entry in a.binaries.copy():
        filename = os.path.basename(entry[0]).lower()
        plugin_dir = os.path.basename(os.path.dirname(entry[0])).lower()
        is_plugin = 'plugins' in entry[0].replace('\\', '/').split('/')
        if (
            filename in plugin_only_libs_windows or
            (is_plugin and (plugin_dir in unused_plugin_dirs_windows or filename in unused_plugins_windows))
        ):
            a.binaries.remove(entry)

# Qt's own translations only load through a QTranslator, and GogStash never
# installs one. WebEngine's locales are a different folder and stay.
for entry in a.datas.copy():
    parts = entry[0].replace('\\', '/').split('/')
    if 'translations' in parts and entry[0].endswith('.qm'):
        a.datas.remove(entry)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='gogstash',
    contents_directory='lib',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(SPECPATH, '..', 'icons', 'logo.ico')],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='gogstash',
)
