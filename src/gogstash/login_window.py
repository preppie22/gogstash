"""GOG login helper that runs in its own process.

Shows GOG's login page in pywebview, using the system's own web view
(Edge WebView2 on Windows, WebKitGTK on Linux). Qt and the web view both
want the main thread, so the main window starts this as a separate
process and only reads its exit code. The helper exchanges the code for a
token and saves it itself.
"""

import sys
import threading
from pathlib import Path
import time
import os
import requests
import logging
from enum import IntEnum

from gogstash import gog_auth
from gogstash.paths import ConfigFile, config_file_path

class ExitCode(IntEnum):
    """How the login helper ended, reported through its exit code.

    The values stay clear of 1, which GTK exits with on its own when it
    can't open a display.
    """
    EXIT_OK = 0
    EXIT_CANCELLED = 75
    EXIT_NO_WEBVIEW = 2
    EXIT_TOKEN_ERROR = 4

# Get lib64 typelib if on Tumbleweed/Arch/Fedora
TYPELIB_DIRS = (
    "/usr/lib/x86_64-linux-gnu/girepository-1.0",
    "/usr/lib64/girepository-1.0",
    "/usr/lib/girepository-1.0",
    "/usr/local/lib/girepository-1.0",
)

BASE_PAGE = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  :root { color-scheme: light dark; }
  html, body { height: 100%; margin: 0; }
  body {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 16px;
    font-family: system-ui, sans-serif;
    background: Canvas;
    color: CanvasText;
  }
  .spinner {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: 4px solid rgba(128, 128, 128, 0.25);
    border-top-color: #8a4fd8;
    animation: spin 0.9s linear infinite;
  }
  p { margin: 0; font-size: 15px; opacity: 0.8; }
  @keyframes spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) {
    .spinner { animation-duration: 3s; }
  }
</style>
</head>
<body>
  <div class="spinner"></div>
  <p>Loading GOG login…</p>
</body>
</html>
"""

class LoginWindow():
    """The login window and everything the helper process does around it."""
    def __init__(self):
        """Set up logging to the app log file.

        The helper is its own process, so it doesn't share the main
        window's logging setup.
        """
        self.__code = None
        self.__load_failed = False
        log_file = config_file_path(ConfigFile.APP_LOG)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
        filename=str(log_file),
        format='[%(asctime)s | %(module)s] - %(levelname)s - %(message)s',
        level=logging.INFO
        )
        self.log = logging.getLogger(__name__)

    @property
    def code(self):
        """str | None: The authorization code caught from GOG's redirect, if any."""
        return self.__code

    def start_helper(self) -> int:
        """Show the login window until the user logs in or closes it.

        The window opens on a local loading page, then loads GOG's login
        page once that is up. A background thread checks the address four
        times a second and closes the window as soon as it lands on the
        login success page. The thread is a daemon, so closing the window
        early doesn't leave the process waiting on it.

        In the frozen Linux build, ``GI_TYPELIB_PATH`` lists every typelib
        folder the distro has, since the bundled libgirepository only
        looks in Debian's.

        Returns:
            int: An ``ExitCode``. ``EXIT_OK`` once the token is saved,
            ``EXIT_TOKEN_ERROR`` if the login worked but the token exchange
            didn't, ``EXIT_CANCELLED`` if the window was closed without
            logging in, and ``EXIT_NO_WEBVIEW`` if there is no working web
            view or GOG's page couldn't be loaded.
        """
        gui = "edgechromium" if sys.platform == "win32" else "gtk"
        if getattr(sys, "frozen", False) and sys.platform.startswith("linux"):
            found = [d for d in TYPELIB_DIRS if Path(d).is_dir()]
            os.environ["GI_TYPELIB_PATH"] = os.pathsep.join(found)
            self.log.info(f"typelib dirs: {found}")
        try:
            import webview
        except Exception as e:
            self.log.warning(f"pywebview import failed: {e!r}")
            return ExitCode.EXIT_NO_WEBVIEW

        done = threading.Event()
        window = webview.create_window("GOG Login", html=BASE_PAGE, width=600, height=700)

        def poll_url():
            window.events.loaded.wait()
            try:
                window.load_url(gog_auth.build_auth_uri())
            except Exception as e:
                if not done.is_set():
                    self.log.warning(f"unable to load login page: {e!r}")
                    self.__load_failed = True
                    done.set()
                    window.destroy()
                else:
                    return
            while not done.is_set():
                if window.events.loaded.is_set():
                    try:
                        self.__code = gog_auth.extract_code(window.get_current_url())
                    except Exception:
                        self.__code = None
                    if self.__code:
                        done.set()
                        window.destroy()
                time.sleep(0.25)

        window.events.closed += done.set

        threading.Thread(target=poll_url, daemon=True).start()
        try:
            webview.start(gui=gui, private_mode=True)
        except Exception as e:
            self.log.warning(f"webview.start failed with gui={gui}: {e!r}")
            return ExitCode.EXIT_NO_WEBVIEW
        if self.__load_failed:
            return ExitCode.EXIT_NO_WEBVIEW
        if self.__code:
            self.log.info("code fetched successfully")
            if self._create_token():
                return ExitCode.EXIT_OK
            return ExitCode.EXIT_TOKEN_ERROR

        self.log.info("window closed without a code")
        return ExitCode.EXIT_CANCELLED

    def _create_token(self) -> bool:
        """Exchange the caught code for a token and save it.

        Returns:
            bool: True if the token was saved. False if GOG couldn't be
            reached or rejected the code as expired or invalid.
        """
        try:
            token = gog_auth.fetch_token(self.code)
            gog_auth.save_token(token)
        except requests.RequestException as e:
            self.log.warning(f"connection to gog api failed: {e!r}")            
            return False
        except KeyError as e:
            self.log.warning(f"expired or invalid address: {e!r}")
            return False
        return True

if __name__ == "__main__":
    login_window = LoginWindow()
    sys.exit(login_window.start_helper())

    