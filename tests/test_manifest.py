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

    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="abc123", version=None, timestamp=111.0)

    stored = json.loads((tmp_path / manifest.MANIFEST_FILE).read_text())
    assert stored == {"setup.exe": {"category": "installers", "downlink": DL, "size": 5, "db_size": DB_SIZE, "checksum": "abc123", "version": None, "fetched_at": 111.0}}


def test_add_file_keys_by_the_relative_path_not_the_absolute_one(tmp_path):
    # Regression: game_dir used to get baked straight into the stored key,
    # which is exactly the portability problem this manifest replaced the
    # fetched_files DB table to avoid in the first place.
    (tmp_path / "installers").mkdir()
    game_file = tmp_path / "installers" / "setup.exe"
    game_file.write_bytes(b"hi")

    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="x", version=None, timestamp=1.0)

    stored = json.loads((tmp_path / manifest.MANIFEST_FILE).read_text())
    assert list(stored.keys()) == ["installers/setup.exe"]


def test_add_file_raises_when_the_actual_file_is_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        manifest.add_file(tmp_path, tmp_path / "nope.exe", category="installers", downlink=DL, db_size=DB_SIZE, checksum="x", version=None, timestamp=1.0)


def test_add_file_keeps_earlier_entries_around(tmp_path):
    file_a = tmp_path / "a.exe"
    file_b = tmp_path / "b.exe"
    file_a.write_bytes(b"aaa")
    file_b.write_bytes(b"bbbb")

    manifest.add_file(tmp_path, file_a, category="installers", downlink=DL, db_size=DB_SIZE, checksum="a-sum", version=None, timestamp=1.0)
    manifest.add_file(tmp_path, file_b, category="installers", downlink=DL, db_size=DB_SIZE, checksum="b-sum", version=None, timestamp=2.0)

    stored = json.loads((tmp_path / manifest.MANIFEST_FILE).read_text())
    assert set(stored.keys()) == {"a.exe", "b.exe"}


def test_add_file_overwrites_an_existing_entry_for_the_same_file(tmp_path):
    game_file = tmp_path / "a.exe"
    game_file.write_bytes(b"aaa")
    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="old-sum", version=None, timestamp=1.0)

    game_file.write_bytes(b"aaaaa")  # re-downloaded, grew by 2 bytes
    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="new-sum", version=None, timestamp=2.0)

    stored = json.loads((tmp_path / manifest.MANIFEST_FILE).read_text())
    assert stored == {"a.exe": {"category": "installers", "downlink": DL, "size": 5, "db_size": DB_SIZE, "checksum": "new-sum", "version": None, "fetched_at": 2.0}}


def test_add_file_does_not_leave_the_temp_file_behind(tmp_path):
    game_file = tmp_path / "a.exe"
    game_file.write_bytes(b"a")

    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="x", version=None, timestamp=1.0)

    assert not (tmp_path / f"{manifest.MANIFEST_FILE}~").exists()


def test_add_file_on_a_full_disk_raises_and_leaves_the_old_manifest_alone(tmp_path):
    # Half a JSON file is worse than no JSON file. The old manifest stays as
    # it was, the half-written temp file goes, and the caller hears about it.
    game_file = tmp_path / "a.exe"
    game_file.write_bytes(b"a")
    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="old", version=None, timestamp=1.0)
    before = (tmp_path / manifest.MANIFEST_FILE).read_text()

    def disk_fills_up_mid_dump(data, fp):
        fp.write('{"a.exe": {"categ')
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    with patch("gogstash.manifest.json.dump", disk_fills_up_mid_dump), pytest.raises(OSError) as raised:
        manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="new", version=None, timestamp=2.0)

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
        manifest.add_file(tmp_path, outside_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="x", version=None, timestamp=1.0)


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

    manifest.add_file(tmp_path, file_a, category="installers", downlink=DL, db_size=DB_SIZE, checksum="a", version=None, timestamp=1.0)
    manifest.add_file(tmp_path, file_b, category="bonus_content", downlink=DL, db_size=DB_SIZE, checksum="", version=None, timestamp=2.0)

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

    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="x", version=None, timestamp=1.0)

    hidden_paths = [path for path, _, _ in fake_windows.calls]
    assert str(tmp_path / f"{manifest.MANIFEST_FILE}~") not in hidden_paths


def test_add_file_keeps_its_hands_off_the_windows_api_everywhere_else(tmp_path, monkeypatch):
    import ctypes
    kernel32 = _FakeKernel32()
    monkeypatch.setattr(manifest.sys, "platform", "linux")
    monkeypatch.setattr(ctypes, "windll", type("windll", (), {"kernel32": kernel32}), raising=False)
    game_file = tmp_path / "setup.exe"
    game_file.write_bytes(b"hello")

    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="x", version=None, timestamp=1.0)

    assert kernel32.calls == []


# --- add_file: ghost cleanup ---

DL_OTHER = "https://api.gog.com/products/111/downlink/installer/de1installer0"


def _record(tmp_path, name, downlink=DL, payload=b"hello"):
    game_file = tmp_path / name
    game_file.parent.mkdir(parents=True, exist_ok=True)
    game_file.write_bytes(payload)
    manifest.add_file(tmp_path, game_file, category="installers", downlink=downlink, db_size=DB_SIZE, checksum="abc", version="gog-2", timestamp=1.0)
    return game_file


def _keys(tmp_path):
    return list(json.loads((tmp_path / manifest.MANIFEST_FILE).read_text()))


def test_add_file_drops_the_ghost_of_a_file_redownloaded_under_a_new_path(tmp_path):
    # English claimed the old _de copy (#25), then someone binned the _de
    # folder because who needs German. The fresh _en download has to evict
    # the ghost, or the lookup by downlink trips over it first, every time.
    _record(tmp_path, "installer_linux_de/bass.sh").unlink()

    _record(tmp_path, "installer_linux_en/bass.sh")

    assert _keys(tmp_path) == ["installer_linux_en/bass.sh"]
    assert manifest.check_exist_by_downlink(tmp_path, DL, DB_SIZE, "gog-2")


def test_add_file_heals_a_manifest_that_already_has_a_ghost_in_front(tmp_path):
    # Already broken before the fix: ghost first, real entry second, and the
    # lookup never got past the ghost. The next skip re-records the real one
    # and that's enough to exorcise it.
    ghost = _record(tmp_path, "installer_linux_de/bass.sh")
    real = _record(tmp_path, "installer_linux_en/bass.sh")
    ghost.unlink()
    assert not manifest.check_exist_by_downlink(tmp_path, DL, DB_SIZE, "gog-2")  # the bug, live

    manifest.add_file(tmp_path, real, category="installers", downlink=DL, db_size=DB_SIZE, checksum="abc", version="gog-2", timestamp=2.0)

    assert _keys(tmp_path) == ["installer_linux_en/bass.sh"]
    assert manifest.check_exist_by_downlink(tmp_path, DL, DB_SIZE, "gog-2")


def test_add_file_without_a_downlink_leaves_other_unclaimed_ghosts_alone(tmp_path):
    # "" equals "", so without the guard one old-style record would wipe out
    # every other entry that never got a downlink. Spring cleaning by flamethrower.
    (tmp_path / manifest.MANIFEST_FILE).write_text(json.dumps({
        "patch.exe": {"category": "patches", "size": 2, "checksum": "p", "fetched_at": 1.0},
        "manual.pdf": {"category": "bonus_content", "downlink": "", "size": 3, "checksum": "", "fetched_at": 1.0},
    }))

    _record(tmp_path, "setup.exe", downlink="")

    assert _keys(tmp_path) == ["patch.exe", "manual.pdf", "setup.exe"]


def test_add_file_with_a_none_downlink_leaves_other_none_ghosts_alone(tmp_path):
    # Same trap in a different hat: None == None, and None != "" sails right
    # past a guard that only checks for the empty string.
    (tmp_path / manifest.MANIFEST_FILE).write_text(json.dumps({
        "patch.exe": {"category": "patches", "downlink": None, "size": 2, "checksum": "p", "fetched_at": 1.0},
    }))

    _record(tmp_path, "setup.exe", downlink=None)

    assert _keys(tmp_path) == ["patch.exe", "setup.exe"]


def test_add_file_keeps_a_same_downlink_entry_whose_file_is_still_there(tmp_path):
    # Not a ghost if it's still haunting the disk in person.
    _record(tmp_path, "installer_linux_de/bass.sh")

    _record(tmp_path, "installer_linux_en/bass.sh")

    assert _keys(tmp_path) == ["installer_linux_de/bass.sh", "installer_linux_en/bass.sh"]


def test_add_file_only_clears_ghosts_of_the_file_it_is_recording(tmp_path):
    # A missing file with some other downlink stays put: if the drive or the
    # folder comes back, its entry still matches and nothing is re-downloaded.
    _record(tmp_path, "installer_linux_de/bass.sh", downlink=DL_OTHER).unlink()

    _record(tmp_path, "installer_linux_en/bass.sh")

    assert _keys(tmp_path) == ["installer_linux_de/bass.sh", "installer_linux_en/bass.sh"]


# --- stat_file ---

def test_stat_file_returns_the_recorded_entry_for_a_known_file(tmp_path):
    game_file = tmp_path / "a.exe"
    game_file.write_bytes(b"aaa")
    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="a-sum", version=None, timestamp=1.0)

    assert manifest.stat_file(tmp_path, game_file) == {
        "category": "installers", "downlink": DL, "size": 3, "db_size": DB_SIZE, "checksum": "a-sum", "version": None, "fetched_at": 1.0
    }


def test_stat_file_returns_empty_dict_for_a_file_never_recorded(tmp_path):
    game_file = tmp_path / "a.exe"
    game_file.write_bytes(b"aaa")
    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="a-sum", version=None, timestamp=1.0)

    assert manifest.stat_file(tmp_path, tmp_path / "never-downloaded.exe") == {}


def test_stat_file_returns_empty_dict_when_no_manifest_exists_yet(tmp_path):
    assert manifest.stat_file(tmp_path, tmp_path / "a.exe") == {}


def test_stat_file_does_not_require_the_file_to_still_be_on_disk(tmp_path):
    # stat_file is a pure manifest lookup that shouldn't care whether the
    # actual file is still there. That's check_exist's job.
    game_file = tmp_path / "a.exe"
    game_file.write_bytes(b"aaa")
    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="a-sum", version=None, timestamp=1.0)
    game_file.unlink()

    assert manifest.stat_file(tmp_path, game_file) == {
        "category": "installers", "downlink": DL, "size": 3, "db_size": DB_SIZE, "checksum": "a-sum", "version": None, "fetched_at": 1.0
    }


# --- check_exist ---

DL_DE = "https://api.gog.com/products/111/downlink/installer/de1installer0"


def _old_style_entry(tmp_path, name, payload=b"hello", checksum="abc"):
    # Written the way GogStash did before downlinks existed: just a name, a
    # size and a checksum, no idea which GOG file it ever belonged to.
    game_file = tmp_path / name
    game_file.parent.mkdir(parents=True, exist_ok=True)
    game_file.write_bytes(payload)
    manifest_file = tmp_path / manifest.MANIFEST_FILE
    stored = json.loads(manifest_file.read_text()) if manifest_file.exists() else {}
    stored[name] = {"category": "installers", "size": len(payload), "checksum": checksum, "fetched_at": 1.0}
    manifest_file.write_text(json.dumps(stored))
    return game_file


def test_check_exist_returns_the_path_and_entry_when_the_file_matches_at_its_expected_path(tmp_path):
    game_file = tmp_path / "installers" / "setup.exe"
    game_file.parent.mkdir()
    game_file.write_bytes(b"hello")
    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="abc", version=None, timestamp=1.0)

    assert manifest.check_exist(tmp_path, DL, game_file, 5) == (game_file, {
        "category": "installers", "downlink": DL, "size": 5, "db_size": DB_SIZE, "checksum": "abc", "version": None, "fetched_at": 1.0
    })


def test_check_exist_finds_nothing_for_a_brand_new_game_with_no_manifest_yet(tmp_path):
    # Regression: this used to crash with TypeError, because the fallback
    # branch's own _get_manifest() call didn't check for the "no manifest
    # file yet" sentinel the way stat_file() does, so iterating
    # {'error': '...'}.items() handed 'metadata' a plain string and
    # metadata['size'] blew up.
    game_file = tmp_path / "setup.exe"  # no record, no file. zilch.

    assert manifest.check_exist(tmp_path, DL, game_file, 5) == (None, {})


def test_check_exist_finds_nothing_when_the_expected_file_is_corrupted_or_truncated(tmp_path):
    # Regression: a size mismatch at the exact expected path means the file
    # is a different build or got fucked mid-write, not renamed. It should
    # be treated as verification failed, not handed off to the rename scan.
    # Also the one exit that used to fall off the end with a bare {}, which
    # the worker then tried to unpack into two names. It did not go well.
    game_file = tmp_path / "setup.exe"
    game_file.write_bytes(b"hello")
    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="abc", version=None, timestamp=1.0)
    game_file.write_bytes(b"h")  # truncated somehow

    assert manifest.check_exist(tmp_path, DL, game_file, 5) == (None, {})


def test_check_exist_follows_a_cdn_rename_to_the_file_still_sitting_under_its_old_name(tmp_path):
    # GOG renamed the file on its CDN, contents untouched. Our copy and its
    # entry both still live under the old name, so that's the one to report,
    # not the shiny new name where nothing exists.
    old_name = tmp_path / "setup_1.0.exe"
    old_name.write_bytes(b"hello")
    manifest.add_file(tmp_path, old_name, category="installers", downlink=DL, db_size=DB_SIZE, checksum="abc", version=None, timestamp=1.0)

    assert manifest.check_exist(tmp_path, DL, tmp_path / "setup_1.0_(20270).exe", 5) == (old_name, {
        "category": "installers", "downlink": DL, "size": 5, "db_size": DB_SIZE, "checksum": "abc", "version": None, "fetched_at": 1.0
    })


def test_check_exist_does_not_trust_a_file_renamed_by_hand_just_because_its_size_matches(tmp_path):
    # Policy, not an oversight: a file moved or renamed behind GogStash's back
    # gets downloaded again. "Something in the folder is 5 bytes long" used to
    # count as proof, and a coincidence is not a backup.
    original = tmp_path / "setup.exe"
    original.write_bytes(b"hello")
    manifest.add_file(tmp_path, original, category="installers", downlink=DL, db_size=DB_SIZE, checksum="abc", version=None, timestamp=1.0)
    original.rename(tmp_path / "setup_old_backup.exe")

    assert manifest.check_exist(tmp_path, DL, tmp_path / "setup.exe", 5) == (None, {})


def test_check_exist_finds_nothing_when_the_file_is_deleted_with_nothing_matching_left_behind(tmp_path):
    game_file = tmp_path / "setup.exe"
    game_file.write_bytes(b"hello")
    manifest.add_file(tmp_path, game_file, category="installers", downlink=DL, db_size=DB_SIZE, checksum="abc", version=None, timestamp=1.0)
    game_file.unlink()  # gone, and nothing else in the folder matches its size

    assert manifest.check_exist(tmp_path, DL, game_file, 5) == (None, {})


def test_check_exist_picks_the_entry_whose_own_file_is_still_there_out_of_several(tmp_path):
    # Three entries, all the right size. The first two point at files that
    # have since vanished, so only the third has anything to show for itself.
    for ghost in ("patch.exe", "manual.pdf"):
        _old_style_entry(tmp_path, ghost).unlink()
    survivor = _old_style_entry(tmp_path, "setup_old_name.exe", checksum="installer-sum")

    found = manifest.check_exist(tmp_path, DL, tmp_path / "setup_new_name.exe", 5)

    assert found.filepath == survivor
    assert found.manifest_entry["checksum"] == "installer-sum"


def test_check_exist_claims_an_old_entry_saved_under_another_language_folder(tmp_path):
    # Regression for #25, starring Beneath a Steel Sky: GOG ships one installer
    # for every language, an older GogStash filed it under _de, and now only
    # English is ticked. The match has to come back with the _de path, or the
    # skip gets recorded against an _en file that doesn't exist (i.e. never).
    de_copy = _old_style_entry(tmp_path, "installer_linux_de/bass.sh")

    found = manifest.check_exist(tmp_path, DL, tmp_path / "installer_linux_en" / "bass.sh", 5)

    assert found.filepath == de_copy
    assert found.manifest_entry["checksum"] == "abc"


def test_check_exist_wont_poach_an_entry_another_language_already_owns(tmp_path):
    # Both languages ticked: the _de file is German's, signed with German's
    # downlink. If English could borrow it too, the two would take turns
    # overwriting the downlink and neither would ever stay fetched.
    de_copy = tmp_path / "installer_linux_de" / "bass.sh"
    de_copy.parent.mkdir()
    de_copy.write_bytes(b"hello")
    manifest.add_file(tmp_path, de_copy, category="installers", downlink=DL_DE, db_size=DB_SIZE, checksum="abc", version=None, timestamp=1.0)

    assert manifest.check_exist(tmp_path, DL, tmp_path / "installer_linux_en" / "bass.sh", 5) == (None, {})


@pytest.mark.parametrize("ghost_first", [True, False], ids=["ghost-first", "owned-first"])
def test_check_exist_needs_one_entry_to_pass_both_checks_not_two_entries_one_each(tmp_path, ghost_first):
    # Regression: the "downlink is ours" and "file is on disk" flags used to
    # survive from one entry to the next. An unowned entry with no file plus a
    # German entry with a file added up to one bogus match. Two half-alibis
    # are not an alibi.
    def ghost():
        _old_style_entry(tmp_path, "installer_linux_xx/bass.sh").unlink()

    def owned_by_german():
        de_copy = tmp_path / "installer_linux_de" / "bass.sh"
        de_copy.parent.mkdir()
        de_copy.write_bytes(b"hello")
        manifest.add_file(tmp_path, de_copy, category="installers", downlink=DL_DE, db_size=DB_SIZE, checksum="abc", version=None, timestamp=1.0)

    for make_entry in ((ghost, owned_by_german) if ghost_first else (owned_by_german, ghost)):
        make_entry()

    assert manifest.check_exist(tmp_path, DL, tmp_path / "installer_linux_en" / "bass.sh", 5) == (None, {})


# --- check_exist_by_downlink ---

def _recorded(tmp_path, name="setup.exe", payload=b"hello", downlink=DL, db_size=DB_SIZE, version=None):
    game_file = tmp_path / name
    game_file.parent.mkdir(parents=True, exist_ok=True)
    game_file.write_bytes(payload)
    manifest.add_file(tmp_path, game_file, category="installers", downlink=downlink, db_size=db_size, checksum="abc", version=version, timestamp=1.0)
    return game_file


def test_check_exist_by_downlink_finds_a_file_by_its_downlink_and_listed_size(tmp_path):
    _recorded(tmp_path, "installer_windows_en/setup.exe")

    assert manifest.check_exist_by_downlink(tmp_path, DL, DB_SIZE, None) == {
        "category": "installers", "downlink": DL, "size": 5, "db_size": DB_SIZE, "checksum": "abc", "version": None, "fetched_at": 1.0
    }


def test_check_exist_by_downlink_ignores_a_file_whose_listed_size_changed(tmp_path):
    # GOG shipped an update: same downlink slot, new listing size. The old
    # copy on disk is yesterday's news and has to be fetched again.
    _recorded(tmp_path)

    assert manifest.check_exist_by_downlink(tmp_path, DL, DB_SIZE + 1, None) == {}


def test_check_exist_by_downlink_ignores_a_different_downlink_with_the_same_size(tmp_path):
    _recorded(tmp_path)

    assert manifest.check_exist_by_downlink(tmp_path, DL.replace("en1", "de1"), DB_SIZE, None) == {}


def test_check_exist_by_downlink_does_not_trust_the_manifest_about_a_deleted_file(tmp_path):
    # The manifest swears it's there. The disk begs to differ. Disk wins,
    # or the user never gets their installer back.
    _recorded(tmp_path).unlink()

    assert manifest.check_exist_by_downlink(tmp_path, DL, DB_SIZE, None) == {}


def test_check_exist_by_downlink_rejects_a_file_that_shrank_on_disk(tmp_path):
    _recorded(tmp_path).write_bytes(b"h")

    assert manifest.check_exist_by_downlink(tmp_path, DL, DB_SIZE, None) == {}


def test_check_exist_by_downlink_returns_empty_dict_when_no_manifest_exists_yet(tmp_path):
    assert manifest.check_exist_by_downlink(tmp_path, DL, DB_SIZE, None) == {}


def test_check_exist_by_downlink_ignores_entries_from_before_downlinks_were_recorded(tmp_path):
    # Pre-upgrade manifests only know filenames. No downlink, no match, so the
    # file goes to the worker, which skips it and backfills the entry.
    game_file = tmp_path / "setup.exe"
    game_file.write_bytes(b"hello")
    (tmp_path / manifest.MANIFEST_FILE).write_text(json.dumps({
        "setup.exe": {"category": "installers", "size": 5, "checksum": "abc", "fetched_at": 1.0}
    }))

    assert manifest.check_exist_by_downlink(tmp_path, DL, DB_SIZE, None) == {}


def test_check_exist_by_downlink_uses_the_manifest_it_was_handed_instead_of_rereading(tmp_path):
    _recorded(tmp_path)
    preloaded = manifest.read_manifest(tmp_path)
    (tmp_path / manifest.MANIFEST_FILE).unlink()  # can't reread what isn't there

    assert manifest.check_exist_by_downlink(tmp_path, DL, DB_SIZE, None, preloaded)["downlink"] == DL


def test_check_exist_by_downlink_takes_an_empty_handed_manifest_at_its_word(tmp_path):
    # {} is a real (if lonely) manifest, not "please go read one yourself".
    _recorded(tmp_path)

    assert manifest.check_exist_by_downlink(tmp_path, DL, DB_SIZE, None, {}) == {}


# --- installer versions (#24) ---

def test_add_file_records_the_installer_version(tmp_path):
    _recorded(tmp_path, version="1.7.7.4")

    assert manifest.read_manifest(tmp_path)["setup.exe"]["version"] == "1.7.7.4"


def test_check_exist_by_downlink_ignores_a_file_whose_version_changed_but_size_did_not(tmp_path):
    # The whole point of #24: GOG rounds listed sizes to the MiB, so a small
    # patch can keep the size and the downlink. Only the version owns up.
    _recorded(tmp_path, version="2020.11.a.1")

    assert manifest.check_exist_by_downlink(tmp_path, DL, DB_SIZE, "2020.11.a.2") == {}


def test_check_exist_by_downlink_finds_a_file_whose_version_still_matches(tmp_path):
    _recorded(tmp_path, version="gog-2")

    assert manifest.check_exist_by_downlink(tmp_path, DL, DB_SIZE, "gog-2")["version"] == "gog-2"


def test_check_exist_by_downlink_treats_an_entry_from_before_versions_as_out_of_date(tmp_path):
    # No version on record means no way to vouch for it. Queuing it once
    # costs a checksum check, not a download, and fills the version in.
    (tmp_path / "setup.exe").write_bytes(b"hello")
    (tmp_path / manifest.MANIFEST_FILE).write_text(json.dumps({"setup.exe": {
        "category": "installers", "downlink": DL, "size": 5, "db_size": DB_SIZE, "checksum": "abc", "fetched_at": 1.0,
    }}))

    assert manifest.check_exist_by_downlink(tmp_path, DL, DB_SIZE, "1.0") == {}


def test_check_exist_by_downlink_picks_the_current_copy_over_last_versions_leftover(tmp_path):
    # An update that renamed the installer leaves two entries with the same
    # downlink and size. The old one sitting first in the manifest must not
    # answer for the new one.
    _recorded(tmp_path, name="setup_1.0.exe", version="1.0")
    _recorded(tmp_path, name="setup_1.1.exe", version="1.1")

    assert manifest.check_exist_by_downlink(tmp_path, DL, DB_SIZE, "1.1")["version"] == "1.1"
