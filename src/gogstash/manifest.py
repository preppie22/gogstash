"""Per-game manifest of downloaded files.

Each game directory holds a hidden JSON file (``.gogstash.manifest``)
keyed by file path relative to the game directory. Every entry records
the file's category, downlink, size on disk, size listed by GOG, md5
checksum, installer version and fetch time. Entries written by older
versions have no downlink or listed size, and no version.
"""

import sys
import json
from typing import NamedTuple
from pathlib import Path

MANIFEST_FILE = ".gogstash.manifest"
FILE_ATTRIBUTE_HIDDEN = 0x2

class FileExists(NamedTuple):
    """Result of ``check_exist``.

    Attributes:
        filepath (Path | None): Where the matching file is on disk. This
            can differ from the path asked about, for example when GOG
            renamed the file. None when nothing matched.
        manifest_entry (dict): The matching manifest entry, or an empty
            dict when nothing matched.
    """
    filepath: Path | None
    manifest_entry: dict

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
        version: str | None,
        timestamp: float
    ) -> None:
    """Record a downloaded file in the game's manifest.

    Creates the manifest if it does not exist. The manifest is written to
    a temporary file first and then swapped in, so an interrupted write
    does not corrupt it. If writing the temporary file fails, it is
    deleted and the old manifest stays as it was.

    Other entries with the same downlink whose file is gone are removed in
    the same write. They are left behind when a file comes back under
    another path, and would otherwise hide the new entry from
    ``check_exist_by_downlink``. Entries with no downlink, or another one,
    are kept even when their file is gone.

    Args:
        game_dir (Path): The game's download directory.
        filepath (Path): Path to the downloaded file inside ``game_dir``.
        category (str): Download category, such as ``'installers'``.
        downlink (str): GOG downlink of the file. Stays the same across
            game updates, so it identifies the file before its CDN name is
            known.
        db_size (float): File size listed by GOG when it was downloaded.
        checksum (str): md5 hex digest. Empty for bonus content.
        version (str | None): Version GOG listed for the file's download
            group when it was downloaded. None when GOG lists none, as
            for bonus content.
        timestamp (float): Fetch time as a Unix timestamp.

    Raises:
        FileNotFoundError: If ``filepath`` does not exist.
        OSError: If the manifest cannot be written, for example because
            the disk is full.
    """
    manifest = read_manifest(game_dir)
    if 'error' in manifest:
        manifest = {}
    if not filepath.exists():
        raise FileNotFoundError(f"No such file {filepath}")
    valid_keys = []
    for name, meta in manifest.items():
        recorded_downlink = meta.get('downlink')
        file_on_disk: Path = game_dir / name
        if recorded_downlink and recorded_downlink == downlink and not file_on_disk.exists():
            continue
        else:
            valid_keys.append(name)
    manifest = {key: manifest[key] for key in valid_keys}
        
    manifest[str(filepath.relative_to(game_dir))] = {
        'category': category,
        'downlink': downlink,
        'size': filepath.stat().st_size,
        'db_size': db_size,
        'checksum': checksum,
        'version': version,
        'fetched_at': timestamp
    }
    temp_file = Path(game_dir) / f"{MANIFEST_FILE}~"
    manifest_file = Path(game_dir) / Path(MANIFEST_FILE)
    try:
        with open(temp_file, 'w') as wp:
            json.dump(manifest, wp)
    except Exception:
        temp_file.unlink(missing_ok=True)
        raise
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

def check_exist(game_dir: Path, downlink: str, filepath: Path, filesize: int) -> FileExists:
    """Find a manifest entry for a file that is already downloaded.

    If ``filepath`` exists, its entry matches only when the size on disk
    matches the recorded size. If it does not exist, another entry can
    match instead, for example when GOG renamed the file on its CDN or an
    older GogStash saved a shared installer under another language's
    folder. Such an entry matches when its recorded size equals
    ``filesize``, its own file is still on disk at that size, and it has
    no downlink yet or has ``downlink``. An entry with another downlink
    belongs to another file, such as the same installer in another
    language, and is left alone.

    Files renamed or moved by hand are not tracked down. Their entry points
    to a file that is gone, so nothing matches and the file is downloaded
    again.

    Args:
        game_dir (Path): The game's download directory.
        downlink (str): GOG downlink of the file.
        filepath (Path): The path the file would be saved to.
        filesize (int): File size reported by the server.

    Returns:
        FileExists: Where the matching file is and its manifest entry, or
        ``(None, {})`` if nothing matches.
    """
    stats = stat_file(game_dir, filepath)
    if filepath.exists():
        if stats:
            file_size = filepath.stat().st_size
            if file_size == stats['size']:
                return FileExists(filepath, stats)
        else:
            return FileExists(None, {})
    else:
        manifest = read_manifest(game_dir)
        if 'error' in manifest:
            return FileExists(None, {})
        for name, meta in manifest.items():
            downlink_matched = False
            size_matched = False
            if meta['size'] == filesize:
                if meta.get('downlink', "") == downlink or not meta.get('downlink'):
                    downlink_matched = True
                file_on_disk = game_dir / name
                if file_on_disk.exists() and file_on_disk.stat().st_size == filesize:
                    size_matched = True
            if downlink_matched and size_matched:
                return FileExists(file_on_disk, meta)
    return FileExists(None, {})

def check_exist_by_downlink(
        game_dir: Path,
        downlink: str,
        filesize: int, 
        version: str | None,
        manifest_data: dict | None = None
    ) -> dict:
    """Find a manifest entry for a file that is already downloaded, by its downlink.

    Unlike ``check_exist``, this works before the file's CDN name is known.
    An entry matches when its downlink, listed size and version are the
    same and the file is still on disk at its recorded size. A changed
    listed size or version means GOG updated the file, so it does not
    match. Versions are only compared for equality, since GOG uses formats
    such as ``gog-2`` and ``1.7.7.4``. An entry with no recorded version,
    written by an older GogStash, does not match a listed version.

    Args:
        game_dir (Path): The game's download directory.
        downlink (str): GOG downlink of the file.
        filesize (int): File size listed by GOG.
        version (str | None): Version GOG lists for the file's download
            group. None when GOG lists none, as for bonus content.
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
        if meta.get('version', "") == version and meta.get('downlink', "") == downlink and meta.get('db_size', -1) == filesize:
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

