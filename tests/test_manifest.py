import json
from pathlib import Path

import pytest

from gogstash import manifest


# --- add_file ---

def test_add_file_creates_a_fresh_manifest_when_none_exists(tmp_path):
    game_file = tmp_path / "setup.exe"
    game_file.write_bytes(b"hello")

    manifest.add_file(tmp_path, game_file, category="installers", checksum="abc123", timestamp=111.0)

    stored = json.loads((tmp_path / manifest.MANIFEST_FILE).read_text())
    assert stored == {"setup.exe": {"category": "installers", "size": 5, "checksum": "abc123", "fetched_at": 111.0}}


def test_add_file_keys_by_the_relative_path_not_the_absolute_one(tmp_path):
    # Regression: game_dir used to get baked straight into the stored key,
    # which is exactly the portability problem this manifest replaced the
    # fetched_files DB table to avoid in the first place.
    (tmp_path / "installers").mkdir()
    game_file = tmp_path / "installers" / "setup.exe"
    game_file.write_bytes(b"hi")

    manifest.add_file(tmp_path, game_file, category="installers", checksum="x", timestamp=1.0)

    stored = json.loads((tmp_path / manifest.MANIFEST_FILE).read_text())
    assert list(stored.keys()) == ["installers/setup.exe"]


def test_add_file_raises_when_the_actual_file_is_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        manifest.add_file(tmp_path, tmp_path / "nope.exe", category="installers", checksum="x", timestamp=1.0)


def test_add_file_keeps_earlier_entries_around(tmp_path):
    file_a = tmp_path / "a.exe"
    file_b = tmp_path / "b.exe"
    file_a.write_bytes(b"aaa")
    file_b.write_bytes(b"bbbb")

    manifest.add_file(tmp_path, file_a, category="installers", checksum="a-sum", timestamp=1.0)
    manifest.add_file(tmp_path, file_b, category="installers", checksum="b-sum", timestamp=2.0)

    stored = json.loads((tmp_path / manifest.MANIFEST_FILE).read_text())
    assert set(stored.keys()) == {"a.exe", "b.exe"}


def test_add_file_overwrites_an_existing_entry_for_the_same_file(tmp_path):
    game_file = tmp_path / "a.exe"
    game_file.write_bytes(b"aaa")
    manifest.add_file(tmp_path, game_file, category="installers", checksum="old-sum", timestamp=1.0)

    game_file.write_bytes(b"aaaaa")  # re-downloaded, grew by 2 bytes
    manifest.add_file(tmp_path, game_file, category="installers", checksum="new-sum", timestamp=2.0)

    stored = json.loads((tmp_path / manifest.MANIFEST_FILE).read_text())
    assert stored == {"a.exe": {"category": "installers", "size": 5, "checksum": "new-sum", "fetched_at": 2.0}}


def test_add_file_does_not_leave_the_temp_file_behind(tmp_path):
    game_file = tmp_path / "a.exe"
    game_file.write_bytes(b"a")

    manifest.add_file(tmp_path, game_file, category="installers", checksum="x", timestamp=1.0)

    assert not (tmp_path / f"{manifest.MANIFEST_FILE}~").exists()


def test_add_file_rejects_a_file_that_is_not_under_game_dir(tmp_path):
    # filepath.relative_to(game_dir) is the whole point of taking an absolute
    # path. If it's not actually under game_dir, there's no sane relative
    # key to store it under.
    outside_dir = tmp_path.parent / "somewhere_else"
    outside_dir.mkdir(exist_ok=True)
    outside_file = outside_dir / "setup.exe"
    outside_file.write_bytes(b"x")

    with pytest.raises(ValueError):
        manifest.add_file(tmp_path, outside_file, category="installers", checksum="x", timestamp=1.0)


# --- stat_file ---

def test_stat_file_returns_the_recorded_entry_for_a_known_file(tmp_path):
    game_file = tmp_path / "a.exe"
    game_file.write_bytes(b"aaa")
    manifest.add_file(tmp_path, game_file, category="installers", checksum="a-sum", timestamp=1.0)

    assert manifest.stat_file(tmp_path, game_file) == {
        "category": "installers", "size": 3, "checksum": "a-sum", "fetched_at": 1.0
    }


def test_stat_file_returns_empty_dict_for_a_file_never_recorded(tmp_path):
    game_file = tmp_path / "a.exe"
    game_file.write_bytes(b"aaa")
    manifest.add_file(tmp_path, game_file, category="installers", checksum="a-sum", timestamp=1.0)

    assert manifest.stat_file(tmp_path, tmp_path / "never-downloaded.exe") == {}


def test_stat_file_returns_empty_dict_when_no_manifest_exists_yet(tmp_path):
    assert manifest.stat_file(tmp_path, tmp_path / "a.exe") == {}


def test_stat_file_does_not_require_the_file_to_still_be_on_disk(tmp_path):
    # stat_file is a pure manifest lookup that shouldn't care whether the
    # actual file is still there. That's check_exist's job.
    game_file = tmp_path / "a.exe"
    game_file.write_bytes(b"aaa")
    manifest.add_file(tmp_path, game_file, category="installers", checksum="a-sum", timestamp=1.0)
    game_file.unlink()

    assert manifest.stat_file(tmp_path, game_file) == {
        "category": "installers", "size": 3, "checksum": "a-sum", "fetched_at": 1.0
    }


# --- check_exist ---

def test_check_exist_returns_the_entry_when_the_file_matches_at_its_expected_path(tmp_path):
    game_file = tmp_path / "installers" / "setup.exe"
    game_file.parent.mkdir()
    game_file.write_bytes(b"hello")
    manifest.add_file(tmp_path, game_file, category="installers", checksum="abc", timestamp=1.0)

    assert manifest.check_exist(tmp_path, game_file, 5) == {
        "category": "installers", "size": 5, "checksum": "abc", "fetched_at": 1.0
    }


def test_check_exist_returns_empty_dict_for_a_brand_new_game_with_no_manifest_yet(tmp_path):
    # Regression: this used to crash with TypeError, because the fallback
    # branch's own _get_manifest() call didn't check for the "no manifest
    # file yet" sentinel the way stat_file() does, so iterating
    # {'error': '...'}.items() handed 'metadata' a plain string and
    # metadata['size'] blew up.
    game_file = tmp_path / "setup.exe"  # no record, no file. zilch.

    assert manifest.check_exist(tmp_path, game_file, 5) == {}


def test_check_exist_returns_empty_dict_when_the_expected_file_is_corrupted_or_truncated(tmp_path):
    # Regression: a size mismatch at the exact expected path means the file
    # is a different build or got fucked mid-write, not renamed. It should
    # be treated as verification failed, not handed off to the rename scan.
    game_file = tmp_path / "setup.exe"
    game_file.write_bytes(b"hello")
    manifest.add_file(tmp_path, game_file, category="installers", checksum="abc", timestamp=1.0)
    game_file.write_bytes(b"h")  # truncated somehow

    assert manifest.check_exist(tmp_path, game_file, 5) == {}


def test_check_exist_finds_a_renamed_file_by_matching_size(tmp_path):
    # The manifest still has an entry under "setup.exe" (its name back when
    # it was downloaded), but the user's since renamed the file on disk.
    # Something in the folder still has the exact same size, so it counts.
    original = tmp_path / "setup.exe"
    original.write_bytes(b"hello")
    manifest.add_file(tmp_path, original, category="installers", checksum="abc", timestamp=1.0)
    original.rename(tmp_path / "setup_old_backup.exe")

    assert manifest.check_exist(tmp_path, tmp_path / "setup.exe", 5) == {
        "category": "installers", "size": 5, "checksum": "abc", "fetched_at": 1.0
    }


def test_check_exist_returns_empty_dict_when_the_file_is_deleted_with_nothing_matching_left_behind(tmp_path):
    game_file = tmp_path / "setup.exe"
    game_file.write_bytes(b"hello")
    manifest.add_file(tmp_path, game_file, category="installers", checksum="abc", timestamp=1.0)
    game_file.unlink()  # gone, and nothing else in the folder matches its size

    assert manifest.check_exist(tmp_path, game_file, 5) == {}


def test_check_exist_picks_the_right_entry_out_of_several_when_scanning_by_size(tmp_path):
    # Two other tracked files are also missing from where they should be.
    # The rename scan has to land on the one whose size actually matches the
    # renamed file that's still sitting in the folder, not just any entry.
    patch_file = tmp_path / "patch.exe"
    patch_file.write_bytes(b"pp")
    manifest.add_file(tmp_path, patch_file, category="patches", checksum="patch-sum", timestamp=1.0)
    patch_file.unlink()

    bonus_file = tmp_path / "manual.pdf"
    bonus_file.write_bytes(b"bbbb")
    manifest.add_file(tmp_path, bonus_file, category="bonus_content", checksum="bonus-sum", timestamp=2.0)
    bonus_file.unlink()

    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"hello")
    manifest.add_file(tmp_path, installer, category="installers", checksum="installer-sum", timestamp=3.0)
    installer.rename(tmp_path / "setup_renamed_by_me.exe")

    assert manifest.check_exist(tmp_path, installer, 5) == {
        "category": "installers", "size": 5, "checksum": "installer-sum", "fetched_at": 3.0
    }
