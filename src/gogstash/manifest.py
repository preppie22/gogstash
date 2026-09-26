"""Per-game manifest of downloaded files.

Each game directory holds a hidden JSON file (``.gogstash.manifest``)
keyed by file path relative to the game directory. Every entry records
the file's category, size, md5 checksum and fetch time.
"""

import json
from pathlib import Path

MANIFEST_FILE = ".gogstash.manifest"

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

def add_file(game_dir: Path, filepath: Path, category: str, checksum: str, timestamp: float) -> None:
    """Record a downloaded file in the game's manifest.

    Creates the manifest if it does not exist. The manifest is written to
    a temporary file first and then swapped in, so an interrupted write
    does not corrupt it.

    Args:
        game_dir (Path): The game's download directory.
        filepath (Path): Path to the downloaded file inside ``game_dir``.
        category (str): Download category, such as ``'installers'``.
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
        "category": category,
        'size': filepath.stat().st_size,
        'checksum': checksum,
        'fetched_at': timestamp
    }
    temp_file = Path(game_dir) / f"{MANIFEST_FILE}~"
    with open(temp_file, 'w') as wp:
        json.dump(manifest, wp)
    temp_file.replace(Path(game_dir) / Path(MANIFEST_FILE))

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