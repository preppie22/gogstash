import sys
import os

GI_HOOK_VARS = (
    "GI_TYPELIB_PATH", "GIO_MODULE_DIR", "GDK_PIXBUF_MODULE_FILE",
    "GTK_DATA_PREFIX", "GTK_EXE_PREFIX", "GTK_PATH",
    "PANGO_LIBDIR", "PANGO_SYSCONFDIR",
)

if __name__ == "__main__":
    frozen = getattr(sys, 'frozen', False)
    on_linux = sys.platform.startswith('linux')
    if frozen and on_linux:
        original = os.environ.get('LD_LIBRARY_PATH_ORIG')
        if original:
            os.environ['LD_LIBRARY_PATH'] = original
        else:
            os.environ.pop('LD_LIBRARY_PATH', None)
        os.environ.pop('QT_PLUGIN_PATH', None)
        os.environ.pop('QML2_IMPORT_PATH', None)
        for var in GI_HOOK_VARS:
            os.environ.pop(var, None)
        bundled_share = os.path.join(sys._MEIPASS, "share")
        xdg = [d for d in os.environ.get("XDG_DATA_DIRS", "").split(os.pathsep)
            if d and d != bundled_share]
        if xdg:
            os.environ["XDG_DATA_DIRS"] = os.pathsep.join(xdg)
        else:
            os.environ.pop("XDG_DATA_DIRS", None)

    if "--login-helper" in sys.argv:
        from gogstash.login_window import LoginWindow
        sys.exit(LoginWindow().start_helper())
    else:
        from gogstash.main import main
        main()
