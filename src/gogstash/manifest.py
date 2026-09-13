import json
from pathlib import Path

MANIFEST_FILE = ".gogstash.manifest"

def _get_manifest(game_dir: Path) -> dict:
    manifest_file = Path(game_dir) / MANIFEST_FILE
    manifest = None
    try:
        with open(manifest_file, 'r') as rp:
            manifest = json.load(rp)
    except FileNotFoundError:
        return {'error': f'Missing: {str(manifest_file)}'}
    return manifest

def add_file(game_dir: Path, filepath: Path, checksum: str, timestamp: float) -> None:
    manifest = _get_manifest(game_dir)
    if 'error' in manifest:
        manifest = {}
    filepath_abs = Path(game_dir) / Path(filepath)
    if not filepath_abs.exists():
        raise FileNotFoundError(f"No such file {filepath_abs}")
    manifest[str(filepath)] = {
        'size': filepath_abs.stat().st_size,
        'checksum': checksum,
        'fetched_at': timestamp
    }
    temp_file = Path(game_dir) / f"{MANIFEST_FILE}~"
    with open(temp_file, 'w') as wp:
        json.dump(manifest, wp)
    temp_file.replace(Path(game_dir) / Path(MANIFEST_FILE))

def stat_file(game_dir: Path, filepath: Path) -> dict:
    manifest = _get_manifest(game_dir)
    if 'error' in manifest:
        return {}
    return manifest.get(str(filepath), {})

def check_exist(game_dir: Path, filepath: Path) -> bool:
    stats = stat_file(game_dir, filepath)
    actual = Path(game_dir) / Path(filepath)
    if stats and actual.exists():
        if actual.stat().st_size == stats['size']:
            return True
        else:
            return False
    file_sizes = [f.stat().st_size for f in game_dir.rglob('*')]
    manifest = _get_manifest(game_dir)
    for file in manifest.values():        
        if file['size'] in file_sizes:
            return True         
    return False
