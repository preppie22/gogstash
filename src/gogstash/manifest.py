import json
from pathlib import Path

MANIFEST_FILE = ".gogstash.manifest"

def read_manifest(game_dir: Path) -> dict:
    manifest_file = Path(game_dir) / MANIFEST_FILE
    manifest = None
    try:
        with open(manifest_file, 'r') as rp:
            manifest = json.load(rp)
    except FileNotFoundError:
        return {'error': f'Missing: {str(manifest_file)}'}
    return manifest

def add_file(game_dir: Path, filepath: Path, category: str, checksum: str, timestamp: float) -> None:
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
    manifest = read_manifest(game_dir)
    if 'error' in manifest:
        return {}
    return manifest.get(str(filepath.relative_to(game_dir)), {})

def check_exist(game_dir: Path, filepath: Path, filesize: int) -> dict:
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