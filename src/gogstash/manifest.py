"""Per-game manifest of downloaded files.

Each game directory holds a hidden JSON file (``.gogstash.manifest``)
keyed by file path relative to the game directory. Every entry records
the file's category, downlink, size on disk, size listed by GOG, md5
checksum and fetch time. Entries written by older versions have no
downlink or listed size.
"""

import sys
import json
from pathlib import Path

MANIFEST_FILE = ".gogstash.manifest"
FILE_ATTRIBUTE_HIDDEN = 0x2

def read_manifest(game_dir: Path) -> dict:
    """Read the manifest of a game directory.

    Args:
        game_dir (Path): The game's download directory.

    Returns:
        dict: The manifest entries, or a dict with a single ``'error'`` key
        if the manifest file does not exist.
    """
    manifest_file = Path(game_dir) / MANIFEST_FILE
    manifest = None
    try:
        with open(manifest_file, 'r') as rp:
            manifest = json.load(rp)
    except FileNotFoundError:
        return {'error': f'Missing: {str(manifest_file)}'}
    return manifest

def add_file(
        game_dir: Path,
        filepath: Path,
        category: str,
        downlink: str,
        db_size: float,
        checksum: str,
        timestamp: float
    ) -> None:
    """Record a downloaded file in the game's manifest.

    Creates the manifest if it does not exist. The manifest is written to
    a temporary file first and then swapped in, so an interrupted write
    does not corrupt it.

    Args:
        game_dir (Path): The game's download directory.
        filepath (Path): Path to the downloaded file inside ``game_dir``.
        category (str): Download category, such as ``'installers'``.
        downlink (str): GOG downlink of the file. Stays the same across
            game updates, so it identifies the file before its CDN name is
            known.
        db_size (float): File size listed by GOG when it was downloaded.
        checksum (str): md5 hex digest. Empty for bonus content.
        timestamp (float): Fetch time as a Unix timestamp.

    Raises:
        FileNotFoundError: If ``filepath`` does not exist.
    """
    manifest = read_manifest(game_dir)
    if 'error' in manifest:
        manifest = {}
    if not filepath.exists():
        raise FileNotFoundError(f"No such file {filepath}")
    manifest[str(filepath.relative_to(game_dir))] = {
        'category': category,
        'downlink': downlink,
        'size': filepath.stat().st_size,
        'db_size': db_size,
        'checksum': checksum,
        'fetched_at': timestamp
    }
    temp_file = Path(game_dir) / f"{MANIFEST_FILE}~"
    manifest_file = Path(game_dir) / Path(MANIFEST_FILE)
    with open(temp_file, 'w') as wp:
        json.dump(manifest, wp)
    temp_file.replace(manifest_file)
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(manifest_file), FILE_ATTRIBUTE_HIDDEN)

def stat_file(game_dir: Path, filepath: Path) -> dict:
    """Look up a file's manifest entry.

    Args:
        game_dir (Path): The game's download directory.
        filepath (Path): Path to the file inside ``game_dir``.

    Returns:
        dict: The file's entry, or an empty dict if the manifest or the
        entry is missing.
    """
    manifest = read_manifest(game_dir)
    if 'error' in manifest:
        return {}
    return manifest.get(str(filepath.relative_to(game_dir)), {})

def check_exist(game_dir: Path, filepath: Path, filesize: int) -> dict:
    """Find a manifest entry for a file that is already downloaded.

    If ``filepath`` exists, its entry is returned only when the size on
    disk matches the recorded size. If it does not exist (for example when
    the file name changed on the CDN), any entry with a recorded size equal
    to ``filesize`` is returned, as long as a file of that size exists in
    ``game_dir``.

    Args:
        game_dir (Path): The game's download directory.
        filepath (Path): The path the file would be saved to.
        filesize (int): File size reported by the server.

    Returns:
        dict: The matching manifest entry, or an empty dict.
    """
    stats = stat_file(game_dir, filepath)
    if filepath.exists():
        if stats:
            file_size = filepath.stat().st_size
            if file_size == stats['size']:
                return stats
        else:
            return {}
    else:
        manifest = read_manifest(game_dir)
        if 'error' in manifest:
            return {}
        file_sizes = [f.stat().st_size for f in game_dir.rglob('*')]
        for name, meta in manifest.items():
            if meta['size'] == filesize:
                if filesize in file_sizes:
                    return manifest[name]
    return {}

def check_exist_by_downlink(game_dir: Path, downlink: str, filesize: int, manifest_data: dict | None = None) -> dict:
    """Find a manifest entry for a file that is already downloaded, by its downlink.

    Unlike ``check_exist``, this works before the file's CDN name is known.
    An entry matches when its downlink and listed size are the same and
    the file is still on disk at its recorded size. A changed listed size
    means GOG updated the file, so it does not match.

    Args:
        game_dir (Path): The game's download directory.
        downlink (str): GOG downlink of the file.
        filesize (int): File size listed by GOG.
        manifest_data (dict | None): The game's manifest, if already read.
            Read from ``game_dir`` when None.

    Returns:
        dict: The matching manifest entry, or an empty dict.
    """
    if manifest_data is not None:
        manifest = manifest_data
    else:
        manifest = read_manifest(game_dir)
    if 'error' in manifest:
        return {}
    found = False
    for name, meta in manifest.items():
        if meta.get('downlink', "") == downlink and meta.get('db_size', -1) == filesize:
            found = True
            break
    if not found:
        return {}
    filepath = Path(game_dir) / name
    if filepath.exists():
        file_size = filepath.stat().st_size
        if file_size == meta.get('size'):
            return meta
        else:
            return {}
    return {}

