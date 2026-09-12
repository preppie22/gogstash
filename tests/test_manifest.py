import json
from pathlib import Path

import pytest

from gogstash import manifest


def test_add_file_creates_a_fresh_manifest_when_none_exists(tmp_path):
    (tmp_path / "setup.exe").write_bytes(b"hello")

    manifest.add_file(tmp_path, Path("setup.exe"), checksum="abc123", timestamp=111.0)

    stored = json.loads((tmp_path / manifest.MANIFEST_FILE).read_text())
    assert stored == {"setup.exe": {"size": 5, "checksum": "abc123", "fetched_at": 111.0}}


def test_add_file_keys_by_the_relative_path_not_the_absolute_one(tmp_path):
    # Regression: game_dir used to get baked straight into the stored key,
    # which is exactly the portability problem this manifest replaced the
    # fetched_files DB table to avoid in the first place.
    (tmp_path / "installers").mkdir()
    (tmp_path / "installers" / "setup.exe").write_bytes(b"hi")

    manifest.add_file(tmp_path, Path("installers/setup.exe"), checksum="x", timestamp=1.0)

    stored = json.loads((tmp_path / manifest.MANIFEST_FILE).read_text())
    assert list(stored.keys()) == ["installers/setup.exe"]


def test_add_file_raises_when_the_actual_file_is_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        manifest.add_file(tmp_path, Path("nope.exe"), checksum="x", timestamp=1.0)


def test_add_file_keeps_earlier_entries_around(tmp_path):
    (tmp_path / "a.exe").write_bytes(b"aaa")
    (tmp_path / "b.exe").write_bytes(b"bbbb")

    manifest.add_file(tmp_path, Path("a.exe"), checksum="a-sum", timestamp=1.0)
    manifest.add_file(tmp_path, Path("b.exe"), checksum="b-sum", timestamp=2.0)

    stored = json.loads((tmp_path / manifest.MANIFEST_FILE).read_text())
    assert set(stored.keys()) == {"a.exe", "b.exe"}


def test_add_file_overwrites_an_existing_entry_for_the_same_file(tmp_path):
    game_file = tmp_path / "a.exe"
    game_file.write_bytes(b"aaa")
    manifest.add_file(tmp_path, Path("a.exe"), checksum="old-sum", timestamp=1.0)

    game_file.write_bytes(b"aaaaa")  # re-downloaded, grew by 2 bytes
    manifest.add_file(tmp_path, Path("a.exe"), checksum="new-sum", timestamp=2.0)

    stored = json.loads((tmp_path / manifest.MANIFEST_FILE).read_text())
    assert stored == {"a.exe": {"size": 5, "checksum": "new-sum", "fetched_at": 2.0}}


def test_add_file_does_not_leave_the_temp_file_behind(tmp_path):
    (tmp_path / "a.exe").write_bytes(b"a")

    manifest.add_file(tmp_path, Path("a.exe"), checksum="x", timestamp=1.0)

    assert not (tmp_path / f"{manifest.MANIFEST_FILE}~").exists()


def test_stat_file_returns_the_recorded_entry_for_a_known_file(tmp_path):
    (tmp_path / "a.exe").write_bytes(b"aaa")
    manifest.add_file(tmp_path, Path("a.exe"), checksum="a-sum", timestamp=1.0)

    assert manifest.stat_file(tmp_path, Path("a.exe")) == {
        "size": 3, "checksum": "a-sum", "fetched_at": 1.0
    }


def test_stat_file_returns_empty_dict_for_a_file_never_recorded(tmp_path):
    (tmp_path / "a.exe").write_bytes(b"aaa")
    manifest.add_file(tmp_path, Path("a.exe"), checksum="a-sum", timestamp=1.0)

    assert manifest.stat_file(tmp_path, Path("never-downloaded.exe")) == {}


def test_stat_file_returns_empty_dict_when_no_manifest_exists_yet(tmp_path):
    assert manifest.stat_file(tmp_path, Path("a.exe")) == {}
