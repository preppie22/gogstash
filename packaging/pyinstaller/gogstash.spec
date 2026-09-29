# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import copy_metadata
import os
import sys


datas = [(os.path.join(SPECPATH, '..', '..', 'src', 'gogstash', 'icons'), 'gogstash/icons'), (os.path.join(SPECPATH, '..', 'licenses'), 'gogstash/licenses')]
datas += copy_metadata('gogstash')

# Exclude "libstdc++.so.6", "libgcc_s.so.1", "libgbm.so.1" to fix #1
excluded_files_linux = {
    "libstdc++.so.6", "libgcc_s.so.1", "libgbm.so.1"  
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
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if sys.platform.startswith('linux'):
    for entry in a.binaries.copy():
        filename = os.path.basename(entry[0])
        if filename in excluded_files_linux:
            a.binaries.remove(entry)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='gogstash',
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
