import os
import runpy
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


LAUNCHER = Path(__file__).parents[1] / "packaging" / "pyinstaller" / "launch_gogstash.py"

# Everything the launcher touches. Registering each one with monkeypatch,
# set or not, means whatever the launcher does to them gets undone after.
TOUCHED_VARS = (
    "LD_LIBRARY_PATH", "LD_LIBRARY_PATH_ORIG", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH",
    "GI_TYPELIB_PATH", "GIO_MODULE_DIR", "GDK_PIXBUF_MODULE_FILE",
    "GTK_DATA_PREFIX", "GTK_EXE_PREFIX", "GTK_PATH",
    "PANGO_LIBDIR", "PANGO_SYSCONFDIR", "XDG_DATA_DIRS",
)


@pytest.fixture
def clean_env(monkeypatch):
    for var in TOUCHED_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def frozen_linux(monkeypatch, tmp_path, clean_env):
    bundle = tmp_path / "bundle"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    return bundle


def run_launcher(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["gogstash", *args])
    runpy.run_path(str(LAUNCHER), run_name="__main__")


@patch("gogstash.main.main")
@patch("gogstash.login_window.LoginWindow")
def test_login_helper_flag_runs_helper_and_exits_with_its_code(mock_login_cls, mock_main, monkeypatch, clean_env):
    mock_login_cls.return_value.start_helper.return_value = 75

    with pytest.raises(SystemExit) as exited:
        run_launcher(monkeypatch, "--login-helper")

    # The exit code is the helper's only way of talking to the main window.
    assert exited.value.code == 75
    # Regression: an instance, not the class. Calling start_helper on the
    # class itself died wanting a `self`.
    mock_login_cls.assert_called_once_with()
    mock_main.assert_not_called()


@patch("gogstash.main.main")
@patch("gogstash.login_window.LoginWindow")
def test_no_flag_starts_the_app(mock_login_cls, mock_main, monkeypatch, clean_env):
    # Regression: `from gogstash import main` fetched the module, and
    # modules make poor apps. "'module' object is not callable".
    run_launcher(monkeypatch)

    mock_main.assert_called_once_with()
    mock_login_cls.assert_not_called()


@patch("gogstash.main.main")
def test_frozen_linux_scrubs_bundle_paths_before_anything_starts(mock_main, monkeypatch, frozen_linux):
    bundle = frozen_linux
    monkeypatch.setenv("LD_LIBRARY_PATH", str(bundle))
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/lib/the/users/own")
    monkeypatch.setenv("QT_PLUGIN_PATH", str(bundle / "plugins"))
    monkeypatch.setenv("GTK_PATH", str(bundle / "gtk"))
    monkeypatch.setenv("GI_TYPELIB_PATH", str(bundle / "gi_typelibs"))
    monkeypatch.setenv("GIO_MODULE_DIR", str(bundle / "gio_modules"))
    monkeypatch.setenv("XDG_DATA_DIRS", os.pathsep.join([str(bundle / "share"), "/usr/local/share", "/usr/share"]))

    run_launcher(monkeypatch)

    # Every child, from WebKit's own processes to Dolphin, gets the user's
    # environment back instead of a guided tour of our bundle.
    assert os.environ["LD_LIBRARY_PATH"] == "/usr/lib/the/users/own"
    for var in ("QT_PLUGIN_PATH", "GTK_PATH", "GI_TYPELIB_PATH", "GIO_MODULE_DIR"):
        assert var not in os.environ, var
    assert os.environ["XDG_DATA_DIRS"] == os.pathsep.join(["/usr/local/share", "/usr/share"])
    mock_main.assert_called_once_with()


@patch("gogstash.main.main")
def test_frozen_linux_drops_variables_that_only_ever_pointed_at_the_bundle(mock_main, monkeypatch, frozen_linux):
    bundle = frozen_linux
    monkeypatch.setenv("LD_LIBRARY_PATH", str(bundle))
    monkeypatch.setenv("XDG_DATA_DIRS", str(bundle / "share"))

    run_launcher(monkeypatch)

    # Unset, not empty: an empty XDG_DATA_DIRS means "look nowhere", while
    # an unset one means "the usual places".
    assert "LD_LIBRARY_PATH" not in os.environ
    assert "XDG_DATA_DIRS" not in os.environ


@patch("gogstash.main.main")
def test_from_source_leaves_environment_alone(mock_main, monkeypatch, clean_env):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setenv("QT_PLUGIN_PATH", "/the/users/own/plugins")
    monkeypatch.setenv("GTK_PATH", "/the/users/own/gtk")

    run_launcher(monkeypatch)

    assert os.environ["QT_PLUGIN_PATH"] == "/the/users/own/plugins"
    assert os.environ["GTK_PATH"] == "/the/users/own/gtk"
