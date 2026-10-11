"""Log file setup for the main window, the login helper and the download history.

Kept free of Qt, so the login helper can import it without loading the
main window's libraries.
"""

import logging
import logging.handlers
from pathlib import Path

# Name of the logger that writes the download history. Anything logged to
# it goes to downloads.log only, once setup_download_log has run.
DOWNLOAD_LOGGER = "gogstash.downloads"

def _rotating_handler(log_file: Path, max_bytes: int = 2*1024*1024, backup_count: int = 3) -> logging.handlers.RotatingFileHandler:
    """Build a UTF-8 handler that rolls a log file over once it gets too big.

    The file's folder is created first if it doesn't exist yet.

    Args:
        log_file (Path): The log file to write to.
        max_bytes (int): Size at which the file is renamed to ``.1`` and a
            new one started. 2 MB by default.
        backup_count (int): How many of the old files to keep. Must be at
            least 1, since with 0 the file never rolls over at all.

    Returns:
        logging.handlers.RotatingFileHandler: The handler, not yet attached
        to any logger.
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)
    return logging.handlers.RotatingFileHandler(
        str(log_file),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )

def setup_logging(log_file: Path):
    """Send every log record of this process to a log file.

    Sets up the root logger with ``logging.basicConfig``, so the logger of
    every module writes to the file. The file rolls over at 2 MB and keeps
    three old files. ``urllib3`` is held at WARNING, since its DEBUG lines
    hold each request's full URL, with tokens and signed links in the
    query. ``basicConfig`` only works once per process, so this is called
    once, at startup. Each process gets its own file, the main
    window ``APP_LOG`` and the login helper ``AUTH_LOG``, since two
    processes can't safely share one that rotates.

    Args:
        log_file (Path): The log file to write to, from
            ``paths.log_file_path``.
    """
    logging.basicConfig(
        handlers=[_rotating_handler(log_file)],
        format='[%(asctime)s | %(module)s] - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)

def setup_download_log(log_file: Path):
    """Send the ``DOWNLOAD_LOGGER`` logger to the download history file.

    The history is for the user to read, not for debugging, so it keeps
    more than the app log: it rolls over at 5 MB and keeps five old files.
    Each line is the time and the message, with nothing in between. The
    logger doesn't pass its records on to the root logger, so they stay
    out of ``gogstash.log``. Call it once per process, since each call
    adds another handler and every line would be written once more.

    Args:
        log_file (Path): The history file to write to, from
            ``paths.log_file_path``.
    """
    logger = logging.getLogger(DOWNLOAD_LOGGER)
    handler = _rotating_handler(log_file, 5*1024*1024, 5)
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False