import errno
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from gogstash import manifest

DL = "https://api.gog.com/products/111/downlink/installer/en1installer0"
DB_SIZE = 1234


# --- add_file ---

def test_add_file_creates_a_fresh_manifest_when_none_exists(tmp_path):
    game_file = tmp_path / "setup.exe"
    game_file.write_bytes(b"hello")

    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="abc123", timestamp=111.0)

    stored = json.loads((tmp_path / manifest.MANIFEST_FILE).read_text())
    assert stored == {"setup.exe": {"category": "installers", "downlink": DL, "size": 5, "db_size": DB_SIZE, "checksum": "abc123", "fetched_at": 111.0}}


def test_add_file_keys_by_the_relative_path_not_the_absolute_one(tmp_path):
    # Regression: game_dir used to get baked straight into the stored key,
    # which is exactly the portability problem this manifest replaced the
    # fetched_files DB table to avoid in the first place.
    (tmp_path / "installers").mkdir()
    game_file = tmp_path / "installers" / "setup.exe"
    game_file.write_bytes(b"hi")

    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="x", timestamp=1.0)

    stored = json.loads((tmp_path / manifest.MANIFEST_FILE).read_text())
    assert list(stored.keys()) == ["installers/setup.exe"]


def test_add_file_raises_when_the_actual_file_is_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        manifest.add_file(tmp_path, tmp_path / "nope.exe", category="installers", downlink=DL, db_size=DB_SIZE, checksum="x", timestamp=1.0)


def test_add_file_keeps_earlier_entries_around(tmp_path):
    file_a = tmp_path / "a.exe"
    file_b = tmp_path / "b.exe"
    file_a.write_bytes(b"aaa")
    file_b.write_bytes(b"bbbb")

    manifest.add_file(tmp_path, file_a, category="installers", downlink=DL, db_size=DB_SIZE, checksum="a-sum", timestamp=1.0)
    manifest.add_file(tmp_path, file_b, category="installers", downlink=DL, db_size=DB_SIZE, checksum="b-sum", timestamp=2.0)

    stored = json.loads((tmp_path / manifest.MANIFEST_FILE).read_text())
    assert set(stored.keys()) == {"a.exe", "b.exe"}


def test_add_file_overwrites_an_existing_entry_for_the_same_file(tmp_path):
    game_file = tmp_path / "a.exe"
    game_file.write_bytes(b"aaa")
    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="old-sum", timestamp=1.0)

    game_file.write_bytes(b"aaaaa")  # re-downloaded, grew by 2 bytes
    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="new-sum", timestamp=2.0)

    stored = json.loads((tmp_path / manifest.MANIFEST_FILE).read_text())
    assert stored == {"a.exe": {"category": "installers", "downlink": DL, "size": 5, "db_size": DB_SIZE, "checksum": "new-sum", "fetched_at": 2.0}}


def test_add_file_does_not_leave_the_temp_file_behind(tmp_path):
    game_file = tmp_path / "a.exe"
    game_file.write_bytes(b"a")

    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="x", timestamp=1.0)

    assert not (tmp_path / f"{manifest.MANIFEST_FILE}~").exists()


def test_add_file_on_a_full_disk_raises_and_leaves_the_old_manifest_alone(tmp_path):
    # Half a JSON file is worse than no JSON file. The old manifest stays as
    # it was, the half-written temp file goes, and the caller hears about it.
    game_file = tmp_path / "a.exe"
    game_file.write_bytes(b"a")
    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="old", timestamp=1.0)
    before = (tmp_path / manifest.MANIFEST_FILE).read_text()

    def disk_fills_up_mid_dump(data, fp):
        fp.write('{"a.exe": {"categ')
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    with patch("gogstash.manifest.json.dump", disk_fills_up_mid_dump), pytest.raises(OSError) as raised:
        manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="new", timestamp=2.0)

    assert raised.value.errno == errno.ENOSPC
    assert (tmp_path / manifest.MANIFEST_FILE).read_text() == before
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
        manifest.add_file(tmp_path, outside_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="x", timestamp=1.0)


class _FakeKernel32:
    """Stand-in for ctypes.windll.kernel32 that writes down every hiding attempt,
    plus whether the manifest was actually on disk yet when it happened."""

    def __init__(self):
        self.calls = []

    def SetFileAttributesW(self, path, attributes):
        self.calls.append((path, attributes, Path(path).exists()))
        return 1


@pytest.fixture
def fake_windows(monkeypatch):
    # Cosplaying as Windows without having to actually suffer it.
    import ctypes
    kernel32 = _FakeKernel32()
    monkeypatch.setattr(manifest.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", type("windll", (), {"kernel32": kernel32}), raising=False)
    return kernel32


def test_add_file_hides_the_manifest_on_windows_after_every_single_write(tmp_path, fake_windows):
    # Regression: Windows couldn't care less about the leading dot. And since
    # replace() swaps in the temp file's attributes, hiding it once isn't
    # enough; every write has to re-hide it or it pops right back into view.
    file_a = tmp_path / "a.exe"
    file_b = tmp_path / "b.exe"
    file_a.write_bytes(b"aaa")
    file_b.write_bytes(b"bbbb")

    manifest.add_file(tmp_path, file_a, category="installers", downlink=DL, db_size=DB_SIZE, checksum="a", timestamp=1.0)
    manifest.add_file(tmp_path, file_b, category="bonus_content", downlink=DL, db_size=DB_SIZE, checksum="", timestamp=2.0)

    manifest_path = str(tmp_path / manifest.MANIFEST_FILE)
    assert fake_windows.calls == [
        (manifest_path, manifest.FILE_ATTRIBUTE_HIDDEN, True),
        (manifest_path, manifest.FILE_ATTRIBUTE_HIDDEN, True),
    ]


def test_add_file_leaves_the_temp_file_visible_so_a_leftover_cant_jam_future_writes(tmp_path, fake_windows):
    # open(path, 'w') on a hidden file is a PermissionError on Windows. A
    # hidden temp file left behind by a crash would brick every later write.
    game_file = tmp_path / "setup.exe"
    game_file.write_bytes(b"hello")

    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="x", timestamp=1.0)

    hidden_paths = [path for path, _, _ in fake_windows.calls]
    assert str(tmp_path / f"{manifest.MANIFEST_FILE}~") not in hidden_paths


def test_add_file_keeps_its_hands_off_the_windows_api_everywhere_else(tmp_path, monkeypatch):
    import ctypes
    kernel32 = _FakeKernel32()
    monkeypatch.setattr(manifest.sys, "platform", "linux")
    monkeypatch.setattr(ctypes, "windll", type("windll", (), {"kernel32": kernel32}), raising=False)
    game_file = tmp_path / "setup.exe"
    game_file.write_bytes(b"hello")

    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="x", timestamp=1.0)

    assert kernel32.calls == []


# --- stat_file ---

def test_stat_file_returns_the_recorded_entry_for_a_known_file(tmp_path):
    game_file = tmp_path / "a.exe"
    game_file.write_bytes(b"aaa")
    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="a-sum", timestamp=1.0)

    assert manifest.stat_file(tmp_path, game_file) == {
        "category": "installers", "downlink": DL, "size": 3, "db_size": DB_SIZE, "checksum": "a-sum", "fetched_at": 1.0
    }


def test_stat_file_returns_empty_dict_for_a_file_never_recorded(tmp_path):
    game_file = tmp_path / "a.exe"
    game_file.write_bytes(b"aaa")
    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="a-sum", timestamp=1.0)

    assert manifest.stat_file(tmp_path, tmp_path / "never-downloaded.exe") == {}


def test_stat_file_returns_empty_dict_when_no_manifest_exists_yet(tmp_path):
    assert manifest.stat_file(tmp_path, tmp_path / "a.exe") == {}


def test_stat_file_does_not_require_the_file_to_still_be_on_disk(tmp_path):
    # stat_file is a pure manifest lookup that shouldn't care whether the
    # actual file is still there. That's check_exist's job.
    game_file = tmp_path / "a.exe"
    game_file.write_bytes(b"aaa")
    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="a-sum", timestamp=1.0)
    game_file.unlink()

    assert manifest.stat_file(tmp_path, game_file) == {
        "category": "installers", "downlink": DL, "size": 3, "db_size": DB_SIZE, "checksum": "a-sum", "fetched_at": 1.0
    }


# --- check_exist ---

def test_check_exist_returns_the_entry_when_the_file_matches_at_its_expected_path(tmp_path):
    game_file = tmp_path / "installers" / "setup.exe"
    game_file.parent.mkdir()
    game_file.write_bytes(b"hello")
    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="abc", timestamp=1.0)

    assert manifest.check_exist(tmp_path, game_file, 5) == {
        "category": "installers", "downlink": DL, "size": 5, "db_size": DB_SIZE, "checksum": "abc", "fetched_at": 1.0
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
    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="abc", timestamp=1.0)
    game_file.write_bytes(b"h")  # truncated somehow

    assert manifest.check_exist(tmp_path, game_file, 5) == {}


def test_check_exist_finds_a_renamed_file_by_matching_size(tmp_path):
    # The manifest still has an entry under "setup.exe" (its name back when
    # it was downloaded), but the user's since renamed the file on disk.
    # Something in the folder still has the exact same size, so it counts.
    original = tmp_path / "setup.exe"
    original.write_bytes(b"hello")
    manifest.add_file(tmp_path, original, category="installers", downlink=DL, db_size=DB_SIZE, checksum="abc", timestamp=1.0)
    original.rename(tmp_path / "setup_old_backup.exe")

    assert manifest.check_exist(tmp_path, tmp_path / "setup.exe", 5) == {
        "category": "installers", "downlink": DL, "size": 5, "db_size": DB_SIZE, "checksum": "abc", "fetched_at": 1.0
    }


def test_check_exist_returns_empty_dict_when_the_file_is_deleted_with_nothing_matching_left_behind(tmp_path):
    game_file = tmp_path / "setup.exe"
    game_file.write_bytes(b"hello")
    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="abc", timestamp=1.0)
    game_file.unlink()  # gone, and nothing else in the folder matches its size

    assert manifest.check_exist(tmp_path, game_file, 5) == {}


def test_check_exist_picks_the_right_entry_out_of_several_when_scanning_by_size(tmp_path):
    # Two other tracked files are also missing from where they should be.
    # The rename scan has to land on the one whose size actually matches the
    # renamed file that's still sitting in the folder, not just any entry.
    patch_file = tmp_path / "patch.exe"
    patch_file.write_bytes(b"pp")
    manifest.add_file(tmp_path, patch_file, category="patches", downlink=DL, db_size=DB_SIZE, checksum="patch-sum", timestamp=1.0)
    patch_file.unlink()

    bonus_file = tmp_path / "manual.pdf"
    bonus_file.write_bytes(b"bbbb")
    manifest.add_file(tmp_path, bonus_file, category="bonus_content", downlink=DL, db_size=DB_SIZE, checksum="bonus-sum", timestamp=2.0)
    bonus_file.unlink()

    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"hello")
    manifest.add_file(tmp_path, installer, category="installers", downlink=DL, db_size=DB_SIZE, checksum="installer-sum", timestamp=3.0)
    installer.rename(tmp_path / "setup_renamed_by_me.exe")

    assert manifest.check_exist(tmp_path, installer, 5) == {
        "category": "installers", "downlink": DL, "size": 5, "db_size": DB_SIZE, "checksum": "installer-sum", "fetched_at": 3.0
    }


# --- check_exist_by_downlink ---

def _recorded(tmp_path, name="setup.exe", payload=b"hello", downlink=DL, db_size=DB_SIZE):
    game_file = tmp_path / name
    game_file.parent.mkdir(parents=True, exist_ok=True)
    game_file.write_bytes(payload)
    manifest.add_file(tmp_path, game_file, category="installers", downlink=downlink, db_size=db_size, checksum="abc", timestamp=1.0)
    return game_file


def test_check_exist_by_downlink_finds_a_file_by_its_downlink_and_listed_size(tmp_path):
    _recorded(tmp_path, "installer_windows_en/setup.exe")

    assert manifest.check_exist_by_downlink(tmp_path, DL, DB_SIZE) == {
        "category": "installers", "downlink": DL, "size": 5, "db_size": DB_SIZE, "checksum": "abc", "fetched_at": 1.0
    }


def test_check_exist_by_downlink_ignores_a_file_whose_listed_size_changed(tmp_path):
    # GOG shipped an update: same downlink slot, new listing size. The old
    # copy on disk is yesterday's news and has to be fetched again.
    _recorded(tmp_path)

    assert manifest.check_exist_by_downlink(tmp_path, DL, DB_SIZE + 1) == {}


def test_check_exist_by_downlink_ignores_a_different_downlink_with_the_same_size(tmp_path):
    _recorded(tmp_path)

    assert manifest.check_exist_by_downlink(tmp_path, DL.replace("en1", "de1"), DB_SIZE) == {}


def test_check_exist_by_downlink_does_not_trust_the_manifest_about_a_deleted_file(tmp_path):
    # The manifest swears it's there. The disk begs to differ. Disk wins,
    # or the user never gets their installer back.
    _recorded(tmp_path).unlink()

    assert manifest.check_exist_by_downlink(tmp_path, DL, DB_SIZE) == {}


def test_check_exist_by_downlink_rejects_a_file_that_shrank_on_disk(tmp_path):
    _recorded(tmp_path).write_bytes(b"h")

    assert manifest.check_exist_by_downlink(tmp_path, DL, DB_SIZE) == {}


def test_check_exist_by_downlink_returns_empty_dict_when_no_manifest_exists_yet(tmp_path):
    assert manifest.check_exist_by_downlink(tmp_path, DL, DB_SIZE) == {}


def test_check_exist_by_downlink_ignores_entries_from_before_downlinks_were_recorded(tmp_path):
    # Pre-upgrade manifests only know filenames. No downlink, no match, so the
    # file goes to the worker, which skips it and backfills the entry.
    game_file = tmp_path / "setup.exe"
    game_file.write_bytes(b"hello")
    (tmp_path / manifest.MANIFEST_FILE).write_text(json.dumps({
        "setup.exe": {"category": "installers", "size": 5, "checksum": "abc", "fetched_at": 1.0}
    }))

    assert manifest.check_exist_by_downlink(tmp_path, DL, DB_SIZE) == {}


def test_check_exist_by_downlink_uses_the_manifest_it_was_handed_instead_of_rereading(tmp_path):
    _recorded(tmp_path)
    preloaded = manifest.read_manifest(tmp_path)
    (tmp_path / manifest.MANIFEST_FILE).unlink()  # can't reread what isn't there

    assert manifest.check_exist_by_downlink(tmp_path, DL, DB_SIZE, preloaded)["downlink"] == DL


def test_check_exist_by_downlink_takes_an_empty_handed_manifest_at_its_word(tmp_path):
    # {} is a real (if lonely) manifest, not "please go read one yourself".
    _recorded(tmp_path)

    assert manifest.check_exist_by_downlink(tmp_path, DL, DB_SIZE, {}) == {}
