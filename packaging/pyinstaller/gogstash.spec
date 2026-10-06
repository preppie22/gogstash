# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import copy_metadata
import os
import re
import sys


datas = [(os.path.join(SPECPATH, '..', '..', 'src', 'gogstash', 'icons'), 'gogstash/icons'), (os.path.join(SPECPATH, '..', 'licenses'), 'gogstash/licenses')]
datas += copy_metadata('gogstash')

# Exclude "libstdc++.so.6", "libgcc_s.so.1", "libgbm.so.1" to fix #1
excluded_files_linux = {
    "libstdc++.so.6", "libgcc_s.so.1", "libgbm.so.1",
}

# The login helper's pywebview runs on the system's own GTK and WebKitGTK, so
# only gi's Python bindings ship. gi's hooks would happily pack the whole GTK
# family plus everything it drags along (the gvfs and libproxy GIO modules
# bring a TLS, HTTP and LDAP stack to the party). Matched by name stem since
# the version suffix changes between distros.
gtk_stack_linux = re.compile(r"^lib(" + "|".join([
    r"glib-2\.0", r"gobject-2\.0", r"gio-2\.0", r"gmodule-2\.0", r"gthread-2\.0",
    r"gtk-3", r"gdk-3", r"gdk_pixbuf-2\.0",
    r"cairo", r"cairo-gobject", r"pango-1\.0", r"pangocairo-1\.0", r"pangoft2-1\.0",
    r"harfbuzz", r"harfbuzz-gobject", r"atk-1\.0", r"atk-bridge-2\.0", r"atspi",
    r"epoxy", r"pixman-1", r"fribidi", r"thai", r"datrie", r"cloudproviders",
    r"rsvg-2", r"glycin-2", r"heif", r"dav1d", r"webp", r"webpdemux", r"webpmux",
    r"sharpyuv", r"xml2", r"ffi", r"pcre2-8", r"mount", r"blkid", r"selinux",
    r"gvfscommon", r"proxy", r"pxbackend-1\.0", r"curl-gnutls", r"gnutls",
    r"nettle", r"hogweed", r"gmp", r"tasn1", r"p11-kit", r"idn2", r"unistring",
    r"psl", r"nghttp2", r"nghttp3", r"ngtcp2", r"ngtcp2_crypto_gnutls",
    r"ssh2", r"ldap", r"lber", r"sasl2", r"brotlienc", r"duktape",
    # Not GTK, but a 22.04 fontconfig loaded by Qt starves Tumbleweed's pango
    # of FcConfigSetDefaultSubstitute, so these come from the system too.
    r"fontconfig", r"freetype",
]) + r")\.so")
# libgirepository-1.0 stays on purpose. Newer distros (Ubuntu 26.04) only
# ship girepository-2.0, and the 1.0 library runs fine on any newer GLib.

# The GTK stack's data: typelibs, GIO modules, pixbuf loaders, and the icon
# themes and translations hooksconfig already keeps out.
gtk_data_dirs_linux = ("share/", "gi_typelibs/", "gio_modules/", "lib/gdk-pixbuf/")

# What the GTK stack leaves behind once it's gone: libraries only GTK linked
# against. Exact 22.04 names, since that's what the build container has. The
# ICU here is Ubuntu's 70, not the 73 Qt keeps in PySide6/Qt/lib.
gtk_leftovers_linux = {
    "libicuuc.so.70", "libicudata.so.70", "libtiff.so.5", "libjpeg.so.8",
    "libjbig.so.0", "libdeflate.so.0", "libpng16.so.16", "libgraphite2.so.3",
    "libpcre.so.3", "libXau.so.6", "libXdmcp.so.6", "libbsd.so.0", "libmd.so.0",
    "libXcomposite.so.1", "libXcursor.so.1", "libXfixes.so.3", "libXdamage.so.1",
    "libXinerama.so.1", "libXi.so.6", "libXrandr.so.2", "libXrender.so.1",
    "libXext.so.6",
}

# Every desktop distro has these, and the AppImage project's excludelist
# says to take them from the system. A 22.04 libX11 loaded into a newer
# distro's GTK even warns that Xlib isn't thread-safe. The dbus chain goes
# too (libdbus-1 plus the libsystemd, libgcrypt, liblz4 and libcap only it
# needs): no desktop runs without dbus, and distros without systemd build
# their libdbus without libsystemd anyway.
system_libs_linux = {
    "libX11.so.6", "libX11-xcb.so.1", "libz.so.1", "libexpat.so.1",
    "libuuid.so.1", "libcom_err.so.2", "libgpg-error.so.0",
    "libdbus-1.so.3", "libsystemd.so.0", "libgcrypt.so.20", "liblz4.so.1",
    "libcap.so.2",
}

# QtNetwork is excluded below, yet PyInstaller's Qt hook still collects its
# library, plus the Kerberos and brotli libraries that library links.
qt_network_libs_linux = {
    "libQt6Network.so.6", "libgssapi_krb5.so.2", "libkrb5.so.3",
    "libk5crypto.so.3", "libkrb5support.so.0", "libkeyutils.so.1",
    "libbrotlidec.so.1", "libbrotlicommon.so.1",
}

# Qt plugins GogStash never loads on Linux: printing, touchscreens and
# embedded displays, image formats other than SVG (every icon is an SVG),
# platforms other than X11 and Wayland, the virtual keyboard, and Wayland
# shells nobody's desktop uses.
unused_plugin_dirs_linux = {
    "printsupport", "generic", "egldeviceintegrations"
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
    "libQt6EglFSDeviceIntegration.so.6", "libQt6EglFsKmsSupport.so.6",
    "libQt6WlShellIntegration.so.6", "libcups.so.2"
}

# The same idea on Windows, where the files have their own names. The app
# runs on the qwindows platform with the Fusion style, so the other
# platforms and the Windows style go too.
# Names are lowercase because Windows file names aren't case sensitive.
unused_plugin_dirs_windows = {
    "generic", "styles"
}
unused_plugins_windows = {
    "qgif.dll", "qicns.dll", "qico.dll", "qjpeg.dll", "qpdf.dll",
    "qtga.dll", "qtiff.dll", "qwbmp.dll", "qwebp.dll",
    "qdirect2d.dll", "qminimal.dll", "qoffscreen.dll",
    "qtvirtualkeyboardplugin.dll"
}
# Qt libraries nothing links to once QtNetwork is out. opengl32sw.dll is
# Qt's software OpenGL (20 MB of it), only loaded when something asks for
# OpenGL, and plain widgets never do.
unused_libs_windows = {
    "opengl32sw.dll", "qt6opengl.dll", "qt6network.dll"
}

# GogStash downloads through requests, so QtNetwork only gets in because
# PySide6's package lists it. readline is for the interactive prompt, which
# a windowed app doesn't have.
excluded_modules = ["PySide6.QtNetwork", "readline"]

a = Analysis(
    ['launch_gogstash.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={"gi": {"icons": [], "themes": [], "languages": []}},
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
        in_gtk_data_dir = entry[0].replace('\\', '/').startswith(gtk_data_dirs_linux)
        if (
            filename in excluded_files_linux or
            filename in plugin_only_libs_linux or
            filename in qt_network_libs_linux or
            filename in gtk_leftovers_linux or filename in system_libs_linux or
            gtk_stack_linux.match(filename) or in_gtk_data_dir or
            (is_plugin and (plugin_dir in unused_plugin_dirs_linux or filename in unused_plugins_linux))
        ):
            a.binaries.remove(entry)
    # Each Qt library also gets a symlink next to the executable, listed
    # with the data files. Left behind, they'd point at nothing.
    for entry in a.datas.copy():
        filename = os.path.basename(entry[0])
        if entry[2] == 'SYMLINK' and (filename in plugin_only_libs_linux or filename in qt_network_libs_linux):
            a.datas.remove(entry)
        elif entry[0].replace('\\', '/').startswith(gtk_data_dirs_linux):
            a.datas.remove(entry)

if sys.platform == 'win32':
    for entry in a.binaries.copy():
        filename = os.path.basename(entry[0]).lower()
        plugin_dir = os.path.basename(os.path.dirname(entry[0])).lower()
        is_plugin = 'plugins' in entry[0].replace('\\', '/').split('/')
        if (
            filename in unused_libs_windows or
            (is_plugin and (plugin_dir in unused_plugin_dirs_windows or filename in unused_plugins_windows))
        ):
            a.binaries.remove(entry)

# Qt's own translations only load through a QTranslator, and GogStash never
# installs one.
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
    # Sheds the debug symbols a few libraries still carry (mostly Qt's ICU).
    # Windows DLLs don't go through strip.
    strip=sys.platform.startswith('linux'),
    upx=False,
    upx_exclude=[],
    name='gogstash',
)
