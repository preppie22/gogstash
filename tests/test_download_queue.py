import hashlib
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QObject, Signal

from gogstash import download_queue, library_db, manifest, paths, settings

FAKE_PRODUCT = {
    "id": 111,
    "title": "Fake Game",
    "slug": "fake-game",
    "isMovie": False,
    "url": "/en/game/fake_game",
    "image": "//images.example.com/fake_game",
    "worksOn": {"Windows": True, "Linux": False, "Mac": True},
}

FAKE_DOWNLOADABLE = {
    "id": 111,
    "downloads": {
        "installers": [
            {
                "id": "installer_windows_en",
                "name": "Fake Game",
                "os": "windows",
                "language": "en",
                "total_size": 2000,
                "files": [
                    {"id": "file1", "size": 1000, "downlink": "https://example.com/file1"},
                ],
            }
        ],
        "bonus_content": [
            {
                "id": "bonus_group",
                "name": "manual (33 pages)",
                "type": "manuals",
                "total_size": 500,
                # "os" intentionally omitted. GOG's real bonus_content entries
                # don't carry a platform, so this comes back as None, not "".
                "files": [
                    {"id": "bonus1", "size": 500, "downlink": "https://example.com/bonus1"},
                ],
            }
        ],
        "patches": [
            {
                "id": "patch_linux_en",
                "name": "Patch",
                "os": "linux",
                "language": "en",
                "total_size": 300,
                "files": [
                    {"id": "patch1", "size": 300, "downlink": "https://example.com/patch1"},
                ],
            }
        ],
        "language_packs": [
            {
                "id": "lang_pack_en",
                "name": "Language Pack",
                "total_size": 100,
                "files": [
                    {"id": "lang1", "size": 100, "downlink": "https://example.com/lang1"},
                ],
            }
        ],
    },
}


@pytest.fixture(autouse=True)
def db():
    library_db._create_db(force=True)
    library_db.update_downloadables([FAKE_DOWNLOADABLE])


def by_file(result, file_id):
    return next((f for f in result if f["file"] == file_id), None)


def test_returns_none_for_empty_product_ids():
    assert download_queue.generate_download_list(()) is None


def test_installers_are_always_included_with_group_id_as_directory():
    result = download_queue.generate_download_list((111,))

    installer = by_file(result, "file1")
    assert installer is not None
    assert installer["directory"] == "installer_windows_en"


def test_bonus_content_excluded_by_default():
    # DEFAULT_SETTINGS has bonus_content: False
    result = download_queue.generate_download_list((111,))

    assert by_file(result, "bonus1") is None


def test_bonus_content_included_when_enabled_even_with_no_os():
    # Regression: bonus_content entries have no "os" key at all (None, not "").
    # Don't let the platform filter mistake that for "wrong platform".
    settings.update_setting("bonus_content", True)

    result = download_queue.generate_download_list((111,))

    bonus = by_file(result, "bonus1")
    assert bonus is not None
    assert bonus["directory"] == "bonus_content"
    assert bonus["os"] is None


def test_patches_included_by_default_when_platform_matches():
    # DEFAULT_SETTINGS has patches: True and platform_filter includes Linux
    result = download_queue.generate_download_list((111,))

    patch = by_file(result, "patch1")
    assert patch is not None
    assert patch["directory"] == "patches"


def test_patches_excluded_when_disabled_in_settings():
    settings.update_setting("patches", False)

    result = download_queue.generate_download_list((111,))

    assert by_file(result, "patch1") is None


def test_platform_filter_excludes_non_matching_os():
    settings.update_setting("platform_filter", ["Windows"])

    result = download_queue.generate_download_list((111,))

    assert by_file(result, "patch1") is None  # patch is linux-only
    assert by_file(result, "file1") is not None  # installer is windows


def test_language_packs_are_never_included():
    settings.update_setting("bonus_content", True)
    settings.update_setting("patches", True)
    settings.update_setting("platform_filter", ["Linux", "Windows", "MacOS"])

    result = download_queue.generate_download_list((111,))

    assert by_file(result, "lang1") is None


def test_platform_helper_maps_settings_labels_to_gog_os_values():
    assert download_queue._platform_helper(["Linux", "Windows", "MacOS"]) == [
        "linux",
        "windows",
        "mac",
    ]
    assert download_queue._platform_helper(["Linux"]) == ["linux"]
    assert download_queue._platform_helper([]) == []


def make_streamed_response(chunks, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.iter_content.return_value = chunks
    return response


def make_checksum_response(md5: str):
    response = MagicMock()
    response.text = f'<file md5="{md5}"/>'
    return response


class Watcher:
    """Records everything a DownloadWorkerThread emits so tests can assert on
    the whole conversation instead of wiring up six lambdas every time."""

    def __init__(self, thread):
        self.succeeded = 0
        self.stopped = 0
        self.failed = []
        self.paused = []
        self.fetched = []
        self.progress = []
        thread.succeeded.connect(lambda: setattr(self, "succeeded", self.succeeded + 1))
        thread.stopped.connect(lambda: setattr(self, "stopped", self.stopped + 1))
        thread.failed.connect(lambda msg: self.failed.append(msg))
        thread.paused.connect(lambda resume_link: self.paused.append(resume_link))
        thread.fetched.connect(lambda entry: self.fetched.append(entry))
        thread.progress.connect(lambda fetched, total: self.progress.append((fetched, total)))


def single_installer_setup(mock_resolve, tmp_path):
    library_db.update_products([FAKE_PRODUCT])
    settings.update_setting("download_path", str(tmp_path))
    settings.update_setting("patches", False)  # isolate to the single installer file
    mock_resolve.return_value = {
        "downlink": "https://cdn.example.com/setup_fake_game.exe",
        "checksum": "https://cdn.example.com/setup_fake_game.exe.xml",
    }
    return tmp_path / "fake-game" / "installer_windows_en"


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_succeeds_and_writes_file(mock_resolve, mock_get, tmp_path):
    single_installer_setup(mock_resolve, tmp_path)
    # file1's declared size in FAKE_DOWNLOADABLE is 1000 bytes, the streamed
    # content must add up to exactly that or the new size-verification check
    # (part_path size vs file['size']) will treat this as a failed download.
    chunk_a = b"a" * 400
    chunk_b = b"b" * 600
    checksum = hashlib.md5(chunk_a + chunk_b).hexdigest()
    mock_get.side_effect = [
        make_checksum_response(checksum),  # the .xml sidekick that verifies it, fetched first
        make_streamed_response([chunk_a, chunk_b]),  # the real download
    ]

    thread = download_queue.DownloadWorkerThread(111)
    events = Watcher(thread)

    thread.run()

    mock_resolve.assert_called_once_with("https://example.com/file1")
    assert events.failed == []
    assert events.succeeded == 1
    [entry] = events.fetched
    written = tmp_path / "fake-game" / "installer_windows_en" / "setup_fake_game.exe"
    assert entry["game_dir"] == tmp_path / "fake-game"
    assert entry["filepath"] == written
    assert entry["size"] == 1000
    assert entry["checksum"] == checksum
    assert "error" not in entry
    assert written.read_bytes() == chunk_a + chunk_b
    # a plain download must not ask the CDN for a byte range
    assert mock_get.call_args_list[1].kwargs["headers"] == {}


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_resumes_a_part_file_with_a_range_request(mock_resolve, mock_get, tmp_path):
    game_dir = single_installer_setup(mock_resolve, tmp_path)
    old_bytes = b"a" * 400
    new_bytes = b"b" * 600  # a real 206 only sends the remaining bytes
    checksum = hashlib.md5(old_bytes + new_bytes).hexdigest()
    game_dir.mkdir(parents=True)
    part_path = game_dir / "setup_fake_game.exe.part"
    part_path.write_bytes(old_bytes)
    mock_get.side_effect = [
        make_checksum_response(checksum),
        make_streamed_response([new_bytes], status_code=206),
    ]

    thread = download_queue.DownloadWorkerThread(
        111, {"partpath": part_path, "downlink": "https://example.com/file1"}
    )
    events = Watcher(thread)

    thread.run()

    assert mock_get.call_args_list[1].kwargs["headers"] == {"Range": "bytes=400-"}
    assert events.failed == []
    assert events.succeeded == 1
    [entry] = events.fetched
    written = game_dir / "setup_fake_game.exe"
    assert entry["checksum"] == checksum
    assert written.read_bytes() == old_bytes + new_bytes  # old half untouched, new half appended
    assert not part_path.exists()


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_starts_over_when_the_cdn_ignores_the_range_request(mock_resolve, mock_get, tmp_path):
    # We politely asked for bytes 400 onwards, the CDN shrugged and sent a 200
    # with the whole file anyway. Appending that to the .part would give us a
    # 1400 byte frankenfile, so the worker has to bin the old half and its hash.
    game_dir = single_installer_setup(mock_resolve, tmp_path)
    old_bytes = b"a" * 400
    full_bytes = b"c" * 1000
    checksum = hashlib.md5(full_bytes).hexdigest()
    game_dir.mkdir(parents=True)
    part_path = game_dir / "setup_fake_game.exe.part"
    part_path.write_bytes(old_bytes)
    mock_get.side_effect = [
        make_checksum_response(checksum),
        make_streamed_response([full_bytes], status_code=200),
    ]

    thread = download_queue.DownloadWorkerThread(
        111, {"partpath": part_path, "downlink": "https://example.com/file1"}
    )
    events = Watcher(thread)

    thread.run()

    assert mock_get.call_args_list[1].kwargs["headers"] == {"Range": "bytes=400-"}
    assert events.failed == []
    assert events.succeeded == 1
    [entry] = events.fetched
    assert entry["checksum"] == checksum
    assert (game_dir / "setup_fake_game.exe").read_bytes() == full_bytes
    # progress must not still be counting the 400 bytes we threw away
    assert thread.fetched_size == 1000
    assert not part_path.exists()


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_skips_a_renamed_bonus_file_instead_of_tripping_over_the_missing_original(mock_resolve, mock_get, tmp_path):
    # Regression: check_exist hands back a manifest entry precisely *because*
    # the file is not at its expected path (the user renamed it). Asking that
    # missing path for its size is how you get a FileNotFoundError for a file
    # we already have, just under a funnier name.
    library_db.update_products([FAKE_PRODUCT])
    settings.update_setting("download_path", str(tmp_path))
    mock_resolve.return_value = {"downlink": "https://cdn.example.com/manual.zip", "checksum": ""}
    bonus_file = {
        "directory": "bonus_content", "category": "bonus_content", "file": "bonus1",
        "os": None, "size": 10, "downlink": "https://example.com/bonus1",
    }
    game_dir = tmp_path / "fake-game"
    bonus_dir = game_dir / "bonus_content"
    bonus_dir.mkdir(parents=True)
    renamed = bonus_dir / "manual (read me first).zip"
    renamed.write_bytes(b"m" * 10)
    manifest.add_file(game_dir, renamed, category="bonus_content", checksum="", timestamp=42.0)
    response = MagicMock()
    response.status_code = 200
    response.headers = {"Content-Length": "10"}
    response.iter_content.side_effect = AssertionError("should never read the byte stream when skipping")
    mock_get.side_effect = [response]

    thread = download_queue.DownloadWorkerThread(111)
    events = Watcher(thread)

    with patch("gogstash.download_queue.generate_download_list", return_value=[bonus_file]):
        thread.run()

    assert events.failed == []
    assert events.succeeded == 1
    [entry] = events.fetched
    assert entry["skipped"] is True
    assert entry["size"] == 10
    assert not (bonus_dir / "manual.zip").exists()


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_resumes_a_bonus_file_and_checks_it_against_the_full_size(mock_resolve, mock_get, tmp_path):
    # Regression: bonus content has no MD5, so it is verified by size. A real
    # 206 reply reports Content-Length for the *remaining* bytes only, so
    # comparing the finished .part file to that number failed every resumed
    # bonus file even though all of its bytes were there, then binned it.
    library_db.update_products([FAKE_PRODUCT])
    settings.update_setting("download_path", str(tmp_path))
    mock_resolve.return_value = {"downlink": "https://cdn.example.com/manual.zip", "checksum": ""}
    bonus_file = {
        "directory": "bonus_content", "category": "bonus_content", "file": "bonus1",
        "os": None, "size": 10, "downlink": "https://example.com/bonus1",
    }
    bonus_dir = tmp_path / "fake-game" / "bonus_content"
    bonus_dir.mkdir(parents=True)
    part_path = bonus_dir / "manual.zip.part"
    part_path.write_bytes(b"a" * 4)
    response = MagicMock()
    response.status_code = 206
    response.iter_content.return_value = [b"b" * 6]
    response.headers = {"Content-Length": "6"}  # just the remaining bytes, like a real 206
    mock_get.side_effect = [response]

    thread = download_queue.DownloadWorkerThread(
        111, {"partpath": part_path, "downlink": "https://example.com/bonus1"}
    )
    events = Watcher(thread)

    with patch("gogstash.download_queue.generate_download_list", return_value=[bonus_file]):
        thread.run()

    assert mock_get.call_args.kwargs["headers"] == {"Range": "bytes=4-"}
    assert events.failed == []
    assert events.succeeded == 1
    assert (bonus_dir / "manual.zip").read_bytes() == b"a" * 4 + b"b" * 6
    assert not part_path.exists()


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_skips_a_file_already_verified_in_the_manifest(mock_resolve, mock_get, tmp_path):
    single_installer_setup(mock_resolve, tmp_path)
    game_dir = tmp_path / "fake-game"
    existing_file = game_dir / "installer_windows_en" / "setup_fake_game.exe"
    existing_file.parent.mkdir(parents=True)
    existing_file.write_bytes(b"already have this one")
    checksum = hashlib.md5(b"already have this one").hexdigest()
    manifest.add_file(game_dir, existing_file, category="installers", checksum=checksum, timestamp=42.0)
    # If the skip check fails to short-circuit, iter_content() gets called and
    # blows up loudly instead of quietly re-downloading something we already have.
    stream_response = MagicMock()
    stream_response.iter_content.side_effect = AssertionError("should never read the byte stream when skipping")
    mock_get.side_effect = [make_checksum_response(checksum), stream_response]

    thread = download_queue.DownloadWorkerThread(111)
    events = Watcher(thread)

    thread.run()

    assert events.failed == []
    assert events.succeeded == 1
    # Skipped files still get reported (so the log can say so), flagged so the
    # scheduler knows not to rewrite their manifest entry.
    [entry] = events.fetched
    assert entry["filepath"] == existing_file
    assert entry["checksum"] == checksum
    assert entry["skipped"] is True
    assert existing_file.read_bytes() == b"already have this one"  # untouched


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_skipping_a_file_never_touches_the_network_stream_or_disk(mock_resolve, mock_get, tmp_path):
    # More paranoid sibling of the "skips a file already verified" test above:
    # that one only proves a *read* of the stream blows up. This one proves
    # nothing ever gets far enough to even try writing bytes, and that the
    # progress signal still reports the skipped file as done instead of
    # leaving the bar stuck at 0% (the gap that was just patched).
    single_installer_setup(mock_resolve, tmp_path)
    game_dir = tmp_path / "fake-game"
    existing_file = game_dir / "installer_windows_en" / "setup_fake_game.exe"
    existing_file.parent.mkdir(parents=True)
    existing_file.write_bytes(b"already have this one")
    checksum = hashlib.md5(b"already have this one").hexdigest()
    manifest.add_file(game_dir, existing_file, category="installers", checksum=checksum, timestamp=42.0)
    stream_response = MagicMock()
    stream_response.iter_content.side_effect = AssertionError("should never read the byte stream when skipping")
    mock_get.side_effect = [make_checksum_response(checksum), stream_response]

    thread = download_queue.DownloadWorkerThread(111)
    events = Watcher(thread)

    real_open = open

    def guard_against_part_file_writes(path, mode="r", *args, **kwargs):
        if "w" in mode or "a" in mode or "x" in mode:
            raise AssertionError(f"should never open {path!r} for writing when skipping")
        return real_open(path, mode, *args, **kwargs)

    with patch("builtins.open", side_effect=guard_against_part_file_writes):
        thread.run()

    part_path = game_dir / "installer_windows_en" / "setup_fake_game.exe.part"
    assert events.failed == []
    assert events.succeeded == 1
    assert stream_response.iter_content.call_count == 0
    assert not part_path.exists()
    # The skip path reports the skipped file's own size as progress made,
    # instead of silently sitting on the fetched_size it walked in with.
    assert events.progress
    assert events.progress[-1][0] == len(b"already have this one")


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_redownloads_when_the_checksum_no_longer_matches(mock_resolve, mock_get, tmp_path):
    # A stale local copy (say, GOG shipped a build update) should not be
    # trusted just because check_exist() found something at the right size.
    single_installer_setup(mock_resolve, tmp_path)
    game_dir = tmp_path / "fake-game"
    existing_file = game_dir / "installer_windows_en" / "setup_fake_game.exe"
    existing_file.parent.mkdir(parents=True)
    existing_file.write_bytes(b"a" * 1000)  # matches file1's declared size, but stale content
    manifest.add_file(game_dir, existing_file, category="installers", checksum="stale-checksum", timestamp=1.0)
    chunk_a = b"a" * 400
    chunk_b = b"b" * 600
    fresh_checksum = hashlib.md5(chunk_a + chunk_b).hexdigest()
    mock_get.side_effect = [
        make_checksum_response(fresh_checksum),
        make_streamed_response([chunk_a, chunk_b]),
    ]

    thread = download_queue.DownloadWorkerThread(111)
    events = Watcher(thread)

    thread.run()

    assert events.failed == []
    assert events.succeeded == 1
    [entry] = events.fetched
    assert entry["checksum"] == fresh_checksum
    assert "skipped" not in entry
    assert existing_file.read_bytes() == chunk_a + chunk_b  # overwritten with the fresh copy


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_only_emits_succeeded_once_when_some_files_are_skipped(mock_resolve, mock_get, tmp_path):
    # Regression: the skip path used to call self.succeeded.emit() right there
    # in the per-file loop, on top of the one the for/else block fires at the
    # very end, so a batch with any skipped file emitted `succeeded` more
    # than once, prematurely freeing the scheduler's concurrency token for a
    # worker thread that was still very much alive.
    library_db.update_products([FAKE_PRODUCT])
    settings.update_setting("download_path", str(tmp_path))
    settings.update_setting("patches", False)
    settings.update_setting("bonus_content", True)  # installer (skip) + bonus (real download)
    mock_resolve.return_value = {
        "downlink": "https://cdn.example.com/file.bin",
        "checksum": "https://cdn.example.com/file.bin.xml",
    }
    game_dir = tmp_path / "fake-game"
    existing_file = game_dir / "installer_windows_en" / "file.bin"
    existing_file.parent.mkdir(parents=True)
    existing_file.write_bytes(b"already have this one")
    checksum = hashlib.md5(b"already have this one").hexdigest()
    manifest.add_file(game_dir, existing_file, category="installers", checksum=checksum, timestamp=1.0)
    bonus_chunk = b"x" * 10
    bonus_response = MagicMock()
    bonus_response.headers = {"Content-Length": str(len(bonus_chunk))}
    bonus_response.iter_content.return_value = [bonus_chunk]
    stream_response = MagicMock()
    stream_response.iter_content.side_effect = AssertionError("should never read the byte stream when skipping")
    # generate_download_list() yields bonus_content before the installer for
    # this fixture. Bonus content has no checksum manifest, so its only request
    # is the download; the installer then asks for its checksum and its stream.
    mock_get.side_effect = [bonus_response, make_checksum_response(checksum), stream_response]

    thread = download_queue.DownloadWorkerThread(111)
    events = Watcher(thread)

    thread.run()

    assert events.failed == []
    assert events.succeeded == 1  # not one emission per skipped file plus one at the end
    assert len(events.fetched) == 2  # both the skipped installer and the freshly downloaded bonus file
    assert [bool(entry.get("skipped")) for entry in events.fetched].count(True) == 1
    assert not any("error" in entry for entry in events.fetched)


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_failure_does_not_also_emit_succeeded(mock_resolve, mock_get, tmp_path):
    single_installer_setup(mock_resolve, tmp_path)
    # The checksum fetch succeeds fine, the actual download is the one that
    # faceplants once we start reading it. Needs a real dict for .headers
    # though, since a bare MagicMock().headers.get(...) is truthy and would
    # trip up int(cl) before we ever get to the good stuff.
    broken_response = MagicMock()
    broken_response.headers = {}
    broken_response.iter_content.side_effect = RuntimeError("connection reset")
    mock_get.side_effect = [make_checksum_response("irrelevant"), broken_response]

    thread = download_queue.DownloadWorkerThread(111)
    events = Watcher(thread)

    thread.run()

    assert events.failed == ["connection reset"]
    assert events.succeeded == 0  # regression: succeeded must not also fire after failed
    [entry] = events.fetched
    assert entry["size"] == -1
    assert "connection reset" in entry["error"]


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_reports_failed_not_succeeded_when_a_file_fails_but_the_worker_carries_on(
    mock_resolve, mock_get, tmp_path
):
    # A checksum mismatch doesn't abort the worker (it just moves on to the
    # next file), so the only thing standing between the scheduler and a
    # green "succeeded" for a game with a corrupt file is the failed flag.
    single_installer_setup(mock_resolve, tmp_path)
    mock_get.side_effect = [
        make_checksum_response("not-the-real-md5"),
        make_streamed_response([b"a" * 400, b"b" * 600]),
    ]

    thread = download_queue.DownloadWorkerThread(111)
    events = Watcher(thread)

    thread.run()

    assert events.succeeded == 0
    assert len(events.failed) == 1
    [entry] = events.fetched
    assert entry["size"] == -1
    assert "Checksum mismatch" in entry["error"]
    game_dir = tmp_path / "fake-game" / "installer_windows_en"
    assert not (game_dir / "setup_fake_game.exe").exists()
    assert not (game_dir / "setup_fake_game.exe.part").exists()


@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_fails_immediately_when_no_valid_token(mock_resolve, tmp_path):
    # Regression: no token, no refresh_token, no soup for you. Auth checking
    # now lives inside gog_api.resolve_downlink(), which raises
    # PermissionError instead of letting `None['access_token']` blow up with
    # something cryptic. Should just report the auth failure and bail.
    library_db.update_products([FAKE_PRODUCT])
    settings.update_setting("download_path", str(tmp_path))
    settings.update_setting("patches", False)
    mock_resolve.side_effect = PermissionError("Authentication failed. Login again.")

    thread = download_queue.DownloadWorkerThread(111)
    events = Watcher(thread)

    thread.run()

    assert events.failed == ["Authentication failed. Login again."]
    assert events.succeeded == 0
    assert events.fetched == []


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_stop_mid_chunk_deletes_part_file_and_emits_stopped(
    mock_resolve, mock_get, tmp_path
):
    game_dir = single_installer_setup(mock_resolve, tmp_path)
    mock_get.side_effect = [
        make_checksum_response("irrelevant"),
        make_streamed_response([b"a" * 400, b"b" * 600]),
    ]

    thread = download_queue.DownloadWorkerThread(111)
    # Rage-click Stop right after chunk one lands. Fuck chunk two.
    thread.update_progress = lambda: thread.stop_worker()
    events = Watcher(thread)

    thread.run()

    assert events.succeeded == 0
    assert events.failed == []
    assert events.stopped == 1
    assert events.fetched == []
    assert not (game_dir / "setup_fake_game.exe.part").exists()
    assert not (game_dir / "setup_fake_game.exe").exists()


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_stop_after_full_download_still_saves_the_file(
    mock_resolve, mock_get, tmp_path
):
    # Stop can land in the sliver of time between the last chunk arriving and
    # the loop noticing the stream ran dry. The file's already fully on disk
    # and checksums clean by then, so binning it would be throwing away
    # used bandwidth
    single_installer_setup(mock_resolve, tmp_path)
    chunk_a = b"a" * 400
    chunk_b = b"b" * 600
    checksum = hashlib.md5(chunk_a + chunk_b).hexdigest()
    thread = download_queue.DownloadWorkerThread(111)

    def chunks_then_stop():
        yield chunk_a
        yield chunk_b
        thread.stop_worker()  # doesn't fire until the loop comes back asking for seconds

    response = MagicMock()
    response.iter_content.return_value = chunks_then_stop()
    mock_get.side_effect = [make_checksum_response(checksum), response]
    events = Watcher(thread)

    thread.run()

    assert events.succeeded == 0
    assert events.failed == []
    assert events.stopped == 1
    [entry] = events.fetched
    written = tmp_path / "fake-game" / "installer_windows_en" / "setup_fake_game.exe"
    assert entry["filepath"] == written
    assert entry["size"] == 1000
    assert entry["checksum"] == checksum
    assert written.read_bytes() == chunk_a + chunk_b


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_pause_mid_chunk_keeps_part_file_and_reports_where_it_is(
    mock_resolve, mock_get, tmp_path
):
    # Pause is Stop's chill sibling: same "drop everything right now", but the
    # half-baked .part file has to survive, since that's the whole point of
    # being able to resume later instead of starting from byte zero.
    game_dir = single_installer_setup(mock_resolve, tmp_path)
    mock_get.side_effect = [
        make_checksum_response("irrelevant"),
        make_streamed_response([b"a" * 400, b"b" * 600]),
    ]

    thread = download_queue.DownloadWorkerThread(111)
    thread.update_progress = lambda: thread.pause_worker()
    events = Watcher(thread)

    thread.run()

    assert events.succeeded == 0
    assert events.failed == []
    assert events.stopped == 0
    assert events.fetched == []
    part_path = game_dir / "setup_fake_game.exe.part"
    assert events.paused == [{"partpath": part_path, "downlink": "https://example.com/file1"}]
    assert part_path.read_bytes() == b"a" * 400
    assert not (game_dir / "setup_fake_game.exe").exists()


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_pause_after_full_download_saves_the_file_and_only_pauses_once(
    mock_resolve, mock_get, tmp_path
):
    # Regression: pausing in the gap after a file finishes verifying used to
    # emit `paused` and then just keep on trucking into the next file (or, on
    # the last file, straight into `succeeded`), so the poor scheduler got
    # told "paused" and "done" for the same job. Now it emits paused once and gets out.
    single_installer_setup(mock_resolve, tmp_path)
    chunk_a = b"a" * 400
    chunk_b = b"b" * 600
    checksum = hashlib.md5(chunk_a + chunk_b).hexdigest()
    thread = download_queue.DownloadWorkerThread(111)

    def chunks_then_pause():
        yield chunk_a
        yield chunk_b
        thread.pause_worker()  # lands after the last chunk, before the loop notices

    response = MagicMock()
    response.iter_content.return_value = chunks_then_pause()
    mock_get.side_effect = [make_checksum_response(checksum), response]
    events = Watcher(thread)

    thread.run()

    assert events.succeeded == 0
    assert events.failed == []
    assert events.paused == [{}]  # nothing half-downloaded to resume from
    written = tmp_path / "fake-game" / "installer_windows_en" / "setup_fake_game.exe"
    assert [entry["filepath"] for entry in events.fetched] == [written]
    assert written.read_bytes() == chunk_a + chunk_b


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_unrelated_failure_with_stop_already_requested_does_not_also_emit_stopped(
    mock_resolve, mock_get, tmp_path
):
    # Regression: `stopped` used to fire from one blanket check put
    # after the whole file loop, regardless of why the loop
    # actually ended. An unrelated failure (here: the destination folder
    # won't create) landing at the same moment as a stop request used to
    # make the worker kill itself twice, once via `failed` and
    # once via `stopped`, and the scheduler tried to bury the same job out
    # of active_queue twice.
    single_installer_setup(mock_resolve, tmp_path)
    mock_get.side_effect = [
        make_checksum_response("irrelevant"),
        make_streamed_response([b"a"]),
    ]

    thread = download_queue.DownloadWorkerThread(111)
    thread.stop_worker()  # stop was already requested before this file even starts
    events = Watcher(thread)

    with patch("pathlib.Path.mkdir", side_effect=OSError("disk full")):
        thread.run()

    assert events.failed == ["disk full"]
    assert events.stopped == 0
    assert events.succeeded == 0


class FakeWorker(QObject):
    """A lazy double for DownloadWorkerThread that never does any actual work.
    Tests drive it by emitting its signals directly, so DownloadScheduler's
    orchestration (dispatch/reap/stop bookkeeping) gets exercised for real,
    minus the real threads, real network calls, and the wait for a QThread
    that will never show up."""

    succeeded = Signal()
    failed = Signal(str)
    progress = Signal(float, float)
    stopped = Signal()
    paused = Signal(dict)
    fetched = Signal(dict)

    def __init__(self, product_id, resume_link=None):
        super().__init__()
        self.product_id = product_id
        self.resume_link = resume_link
        self.stop_worker = MagicMock()
        self.pause_worker = MagicMock()

    def start(self):
        pass

    def wait(self):
        # Never actually ran, so there's jack shit to wait for.
        self.waited = True
        return True


def make_scheduler(concurrency, count):
    product_queue = [{"idx": i, "product_id": i} for i in range(count)]
    return download_queue.DownloadScheduler(product_queue, concurrency)


def _pause_active_worker(job, resume_link=None):
    job["worker"].paused.emit({} if resume_link is None else resume_link)


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_stop_all_stops_active_workers_immediately():
    # Regression: stop_all() used to just set a flag and hope to god
    # that some future dispatch() call, triggered by a completely different
    # worker finishing, would eventually get around to telling active
    # workers to stop. With concurrency 1 there's no other worker around to
    # do that shit, so clicking Stop did jack until the download
    # was going to finish anyway.
    scheduler = make_scheduler(concurrency=1, count=2)
    scheduler.schedule()
    active_worker = scheduler.active_queue[0]["worker"]

    scheduler.stop_all()

    active_worker.stop_worker.assert_called_once()


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_stop_all_reports_pending_and_active_jobs_as_stopped():
    scheduler = make_scheduler(concurrency=1, count=2)
    scheduler.schedule()
    active_worker = scheduler.active_queue[0]["worker"]
    stopped_rows = []
    scheduler.game_stopped.connect(lambda row_idx: stopped_rows.append(row_idx))

    scheduler.stop_all()
    active_worker.stopped.emit()  # the active worker cooperates and taps out

    # Row 0 was mid-download and reports itself. Row 1 never dispatched,
    # but it gets the same "stopped" send-off once the scheduler drains the
    # rest of the queue.
    assert stopped_rows == [0, 1]


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_stop_all_with_nothing_pending_still_emits_stopped_not_finished():
    # Regression: the stopped-vs-finished flag only ever flipped while
    # draining leftover *pending* jobs. Stop the one download that's already
    # running, or the last one left in the queue with nothing pending behind
    # it, and the flag stayed False forever, so the scheduler still
    # announced `finished` right after you'd just told it to fuck off.
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.schedule()
    active_worker = scheduler.active_queue[0]["worker"]
    finished_events, stopped_events = [], []
    scheduler.finished.connect(lambda: finished_events.append(True))
    scheduler.stopped.connect(lambda: stopped_events.append(True))

    scheduler.stop_all()
    active_worker.stopped.emit()

    assert stopped_events == [True]
    assert finished_events == []


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_schedule_emits_finished_not_stopped_when_nothing_was_stopped():
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.schedule()
    active_worker = scheduler.active_queue[0]["worker"]
    finished_events, stopped_events = [], []
    scheduler.finished.connect(lambda: finished_events.append(True))
    scheduler.stopped.connect(lambda: stopped_events.append(True))

    active_worker.succeeded.emit()

    assert finished_events == [True]
    assert stopped_events == []


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_reap_ignores_a_job_that_was_already_removed():
    # Regression: a worker could, in a narrow race, announce its own
    # completion twice (see the double-emit test above). _reap() has to
    # tolerate being called twice for the same job instead of throwing a
    # hissy fit when asked to reap a job that's already gone.
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.schedule()
    job = scheduler.active_queue[0]

    scheduler._reap(job)
    scheduler._reap(job)  # deja vu, but tokens should only tick up once

    assert scheduler.tokens == 1
    assert job["worker"] is None  # the dispatcher builds a fresh one next time


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_scheduler_builds_a_fresh_worker_per_dispatch_not_at_construction():
    scheduler = make_scheduler(concurrency=1, count=2)

    assert all(job["worker"] is None for job in scheduler.idle_queue)

    scheduler.schedule()

    [active] = scheduler.active_queue
    assert isinstance(active["worker"], FakeWorker)
    assert active["worker"].product_id == 0
    assert scheduler.idle_queue[0]["worker"] is None  # still waiting its turn


def _fetched_entry(game_dir, name, checksum="abc", **extra):
    return {
        "game_dir": game_dir, "filepath": game_dir / name, "category": "installers",
        "size": 1, "checksum": checksum, **extra,
    }


def _scheduler_with_game_files(tmp_path, *names):
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.schedule()
    game_dir = tmp_path / "some-game"
    game_dir.mkdir()
    for name in names:
        (game_dir / name).write_bytes(b"x")
    return scheduler, scheduler.active_queue[0]["worker"], game_dir


def _log_lines():
    log_file = paths.config_file_path(paths.ConfigFile.DOWNLOAD_LOG)
    return log_file.read_text().splitlines() if log_file.exists() else []


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_game_succeeded_signal_carries_just_the_row():
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.schedule()
    succeeded = []
    scheduler.game_succeeded.connect(lambda row_idx: succeeded.append(row_idx))

    scheduler.active_queue[0]["worker"].succeeded.emit()

    assert succeeded == [0]


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_game_failed_signal_carries_the_row_and_the_reason():
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.schedule()
    failed = []
    scheduler.game_failed.connect(lambda row_idx, msg: failed.append((row_idx, msg)))

    scheduler.active_queue[0]["worker"].failed.emit("connection reset")

    assert failed == [(0, "connection reset")]
    assert scheduler.active_queue == []  # the job got reaped and its slot freed


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_fetched_file_is_recorded_in_the_manifest_by_the_scheduler(tmp_path):
    scheduler, worker, game_dir = _scheduler_with_game_files(tmp_path, "setup.exe")
    (game_dir / "setup.exe").write_bytes(b"hello")
    before = time.time()

    worker.fetched.emit({
        "game_dir": game_dir, "filepath": game_dir / "setup.exe", "category": "installers",
        "size": 5, "checksum": "abc123",
    })

    recorded = manifest.stat_file(game_dir, game_dir / "setup.exe")
    assert (recorded["category"], recorded["size"], recorded["checksum"]) == ("installers", 5, "abc123")
    assert before <= recorded["fetched_at"] <= time.time()  # stamped when it was recorded


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_fetched_file_is_logged_the_moment_it_arrives_not_when_the_game_ends(tmp_path):
    # The point of the scheduler owning the log: a file that finished before a
    # pause (or before the app got killed) already has its line on disk.
    scheduler, worker, game_dir = _scheduler_with_game_files(tmp_path, "a.exe")

    worker.fetched.emit(_fetched_entry(game_dir, "a.exe", checksum="abc123", size=500))

    [line] = _log_lines()
    assert line.startswith("[")
    assert f"{game_dir / 'a.exe'} : Fetched 500 Bytes | md5: abc123" in line
    assert scheduler.active_queue  # the game itself hasn't finished


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_failed_fetch_entries_never_reach_the_manifest_and_dont_derail_the_good_ones(tmp_path):
    # Regression: a game can report failed entries (size -1, no real file
    # behind them, sometimes just a bare file id for a path) right next to real
    # ones. Calling manifest.add_file on those blindly raises and the good file
    # after it never gets recorded.
    scheduler, worker, game_dir = _scheduler_with_game_files(tmp_path, "good.exe")
    (game_dir / "good.exe").write_bytes(b"hello")

    worker.fetched.emit({
        "game_dir": game_dir, "filepath": tmp_path / "bad_file_id", "category": "installers",
        "size": -1, "checksum": "", "error": "boom",
    })
    worker.fetched.emit({
        "game_dir": game_dir, "filepath": game_dir / "good.exe", "category": "installers",
        "size": 5, "checksum": "abc123",
    })

    recorded = manifest.stat_file(game_dir, game_dir / "good.exe")
    assert (recorded["category"], recorded["size"], recorded["checksum"]) == ("installers", 5, "abc123")
    log = "\n".join(_log_lines())
    assert "bad_file_id : boom" in log  # the failure is still logged, just not recorded
    assert "good.exe : Fetched" in log


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_skipped_fetch_entries_are_logged_but_leave_the_manifest_alone(tmp_path):
    scheduler, worker, game_dir = _scheduler_with_game_files(tmp_path, "setup.exe")
    manifest.add_file(game_dir, game_dir / "setup.exe", category="installers", checksum="abc123", timestamp=1.0)

    worker.fetched.emit(_fetched_entry(game_dir, "setup.exe", checksum="abc123", skipped=True))

    assert manifest.stat_file(game_dir, game_dir / "setup.exe")["fetched_at"] == 1.0
    [line] = _log_lines()
    assert "setup.exe : Skipped | Already up to date" in line


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_every_file_of_a_fully_cached_game_gets_its_own_log_line(tmp_path):
    scheduler, worker, game_dir = _scheduler_with_game_files(tmp_path, "a.exe", "b.exe", "c.exe")

    for name in ("a.exe", "b.exe", "c.exe"):
        worker.fetched.emit(_fetched_entry(game_dir, name, skipped=True))

    lines = _log_lines()
    assert len(lines) == 3
    assert all("Skipped" in line for line in lines)


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_a_file_fetched_before_a_pause_and_skipped_after_the_resume_is_logged_as_both(tmp_path):
    # The log is an event history, not a list of files: the download happened,
    # then the resumed worker re-checked it and skipped it. Both are true.
    scheduler, worker, game_dir = _scheduler_with_game_files(tmp_path, "a.exe")

    worker.fetched.emit(_fetched_entry(game_dir, "a.exe"))
    worker.fetched.emit(_fetched_entry(game_dir, "a.exe", skipped=True))

    first, second = _log_lines()
    assert "Fetched" in first
    assert "Skipped" in second


def test_write_log_file_formats_a_successful_entry():
    download_queue._write_log_file({
        "filepath": Path("setup.exe"), "size": 500, "checksum": "abc123"
    })

    [line] = _log_lines()
    assert line.endswith("| setup.exe : Fetched 500 Bytes | md5: abc123")


def test_write_log_file_formats_an_error_entry():
    download_queue._write_log_file({
        "filepath": Path("setup.exe"), "size": -1, "checksum": "",
        "error": "connection reset",
    })

    [line] = _log_lines()
    assert line.endswith("| setup.exe : connection reset")
    assert "Fetched" not in line


def test_write_log_file_formats_a_skipped_entry():
    download_queue._write_log_file({
        "filepath": Path("setup.exe"), "size": 500, "checksum": "abc123", "skipped": True
    })

    [line] = _log_lines()
    assert line.endswith("| setup.exe : Skipped | Already up to date")


def test_write_log_file_does_nothing_for_an_empty_entry():
    download_queue._write_log_file({})

    assert _log_lines() == []


def test_write_log_msg_puts_every_message_on_its_own_line():
    # Regression: the message logger forgot its newline, so consecutive
    # entries glued themselves together into one very long, very useless line.
    download_queue._write_log_msg("Downloads paused")
    download_queue._write_log_msg("Downloads resumed")
    download_queue._write_log_file({"filepath": Path("a.exe"), "size": 1, "checksum": "x"})

    lines = _log_lines()
    assert len(lines) == 3
    assert lines[0].endswith(": Downloads paused")
    assert lines[1].endswith(": Downloads resumed")


def test_write_log_msg_ignores_an_empty_message():
    download_queue._write_log_msg("")

    assert _log_lines() == []


def test_write_log_msg_survives_a_log_file_it_cannot_write(capsys):
    with patch("builtins.open", side_effect=OSError("disk full")):
        download_queue._write_log_msg("Downloads paused")  # must not raise

    assert "disk full" in capsys.readouterr().out


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_pause_resume_and_stop_each_leave_a_line_in_the_log():
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.schedule()

    scheduler.pause_all()
    scheduler.pause_all()  # a second click shouldn't log a second pause
    scheduler.resume_all()
    scheduler.resume_all()  # nothing was paused any more
    scheduler.stop_all()

    lines = _log_lines()
    assert [line.split(" : ", 1)[1] for line in lines] == [
        "Downloads paused", "Downloads resumed", "Downloads stopped",
    ]


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_pause_all_pauses_active_workers_and_leaves_pending_ones_alone():
    scheduler = make_scheduler(concurrency=1, count=2)
    scheduler.schedule()
    active_worker = scheduler.active_queue[0]["worker"]

    scheduler.pause_all()

    active_worker.pause_worker.assert_called_once()
    active_worker.stop_worker.assert_not_called()
    assert [job["row_idx"] for job in scheduler.idle_queue] == [1]
    assert scheduler.idle_queue[0]["stopped"] is False


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_pause_all_twice_only_pauses_workers_once():
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.schedule()
    active_worker = scheduler.active_queue[0]["worker"]

    scheduler.pause_all()
    scheduler.pause_all()  # panicked double-click, should be a no-op

    active_worker.pause_worker.assert_called_once()


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_paused_worker_moves_to_paused_queue_and_frees_its_token(tmp_path):
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.schedule()
    job = scheduler.active_queue[0]
    resume_link = {"partpath": tmp_path / "game.exe.part", "downlink": "https://example.com/f"}
    game_paused_events = []
    scheduler.game_paused.connect(lambda row_idx: game_paused_events.append(row_idx))

    scheduler.pause_all()
    _pause_active_worker(job, resume_link)

    assert game_paused_events == [0]
    assert scheduler.active_queue == []
    assert scheduler.tokens == 1
    [paused_job] = scheduler.paused_queue
    assert paused_job["row_idx"] == 0
    assert paused_job["resume_link"] == resume_link


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_scheduler_paused_signal_waits_for_the_last_active_worker():
    scheduler = make_scheduler(concurrency=2, count=2)
    scheduler.schedule()
    first, second = list(scheduler.active_queue)
    paused_events = []
    scheduler.paused.connect(lambda: paused_events.append(True))

    scheduler.pause_all()
    _pause_active_worker(first)
    assert paused_events == []  # one worker is still mid-chunk, so nope

    _pause_active_worker(second)
    assert paused_events == [True]


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_pausing_does_not_dispatch_pending_jobs_or_announce_finished():
    scheduler = make_scheduler(concurrency=1, count=2)
    scheduler.schedule()
    job = scheduler.active_queue[0]
    finished_events = []
    scheduler.finished.connect(lambda: finished_events.append(True))

    scheduler.pause_all()
    _pause_active_worker(job)

    # The freed token is right there begging to be used, but the scheduler
    # is supposed to be sitting on its hands.
    assert scheduler.active_queue == []
    assert [j["row_idx"] for j in scheduler.idle_queue] == [1]
    assert finished_events == []


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_resume_all_redispatches_paused_jobs_with_a_fresh_worker_and_their_resume_link(tmp_path):
    scheduler = make_scheduler(concurrency=1, count=2)
    scheduler.schedule()
    job = scheduler.active_queue[0]
    old_worker = job["worker"]
    resume_link = {"partpath": tmp_path / "game.exe.part", "downlink": "https://example.com/f"}
    scheduler.pause_all()
    _pause_active_worker(job, resume_link)
    assert scheduler.active_queue == []

    scheduler.resume_all()

    [resumed] = scheduler.active_queue
    assert resumed["row_idx"] == 0
    assert resumed["worker"] is not old_worker  # a finished QThread with its pause flag still set is no use to anyone
    assert resumed["worker"].resume_link == resume_link
    assert [j["row_idx"] for j in scheduler.idle_queue] == [1]
    assert scheduler.paused_queue == []


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_resume_all_lets_the_rest_of_the_queue_flow_again():
    scheduler = make_scheduler(concurrency=1, count=2)
    scheduler.schedule()
    scheduler.pause_all()
    _pause_active_worker(scheduler.active_queue[0])
    scheduler.resume_all()
    finished_events = []
    scheduler.finished.connect(lambda: finished_events.append(True))

    scheduler.active_queue[0]["worker"].succeeded.emit()  # row 0 done, row 1 should start
    assert [j["row_idx"] for j in scheduler.active_queue] == [1]
    scheduler.active_queue[0]["worker"].succeeded.emit()

    assert finished_events == [True]


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_resume_all_is_a_noop_when_nothing_is_paused():
    scheduler = make_scheduler(concurrency=1, count=2)
    scheduler.schedule()
    worker = scheduler.active_queue[0]["worker"]

    scheduler.resume_all()

    assert [j["row_idx"] for j in scheduler.active_queue] == [0]
    assert scheduler.active_queue[0]["worker"] is worker  # not rebuilt out from under the running download


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_stop_all_while_paused_reports_everything_stopped_and_deletes_part_files(tmp_path):
    scheduler = make_scheduler(concurrency=1, count=2)
    scheduler.schedule()
    job = scheduler.active_queue[0]
    part_path = tmp_path / "game.exe.part"
    part_path.write_bytes(b"half a game")
    stopped_rows, stopped_events, finished_events = [], [], []
    scheduler.game_stopped.connect(lambda row_idx: stopped_rows.append(row_idx))
    scheduler.stopped.connect(lambda: stopped_events.append(True))
    scheduler.finished.connect(lambda: finished_events.append(True))
    scheduler.pause_all()
    _pause_active_worker(job, {"partpath": part_path, "downlink": "https://example.com/f"})

    scheduler.stop_all()

    # Row 0 was paused mid-file, row 1 never even started. Both get sent off,
    # the partial file gets binned, and the UI gets its `stopped` instead of
    # sitting there forever waiting on a paused scheduler that will never talk again.
    assert sorted(stopped_rows) == [0, 1]
    assert not part_path.exists()
    assert scheduler.paused_queue == []
    assert stopped_events == [True]
    assert finished_events == []


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_stop_all_while_paused_survives_a_job_paused_between_files():
    # A pause that lands between two files has no .part file to point at, so
    # the resume link comes back empty. Stop shouldn't trip over the missing key.
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.schedule()
    job = scheduler.active_queue[0]
    stopped_events = []
    scheduler.stopped.connect(lambda: stopped_events.append(True))
    scheduler.pause_all()
    _pause_active_worker(job)

    scheduler.stop_all()

    assert stopped_events == [True]


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_stop_all_while_paused_tolerates_a_part_file_that_already_vanished(tmp_path):
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.schedule()
    job = scheduler.active_queue[0]
    stopped_events = []
    scheduler.stopped.connect(lambda: stopped_events.append(True))
    scheduler.pause_all()
    _pause_active_worker(job, {"partpath": tmp_path / "ghost.part", "downlink": "x"})

    scheduler.stop_all()

    assert stopped_events == [True]


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_stop_while_paused_deletes_the_part_file_a_real_worker_left_behind(mock_resolve, mock_get, tmp_path):
    # Regression: the worker's paused payload and the scheduler's stop_all()
    # each spelled the part-file key their own way (partfile, parthpath,
    # partpath...), so Stop quietly deleted nothing and left the half-file on
    # disk. Every other stop-while-paused test hand-writes the payload, which
    # can't catch that. This one takes the payload from a real paused worker
    # and feeds it to a real scheduler, so the two have to agree.
    game_dir = single_installer_setup(mock_resolve, tmp_path)
    mock_get.side_effect = [
        make_checksum_response("irrelevant"),
        make_streamed_response([b"a" * 400, b"b" * 600]),
    ]
    thread = download_queue.DownloadWorkerThread(111)
    thread.update_progress = lambda: thread.pause_worker()
    events = Watcher(thread)
    thread.run()
    [payload] = events.paused
    part_path = game_dir / "setup_fake_game.exe.part"
    assert part_path.exists()

    with patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker):
        scheduler = make_scheduler(concurrency=1, count=1)
        scheduler.schedule()
        scheduler.pause_all()
        _pause_active_worker(scheduler.active_queue[0], payload)

        scheduler.stop_all()

    assert not part_path.exists()


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_enqueue_ignores_a_row_that_is_already_waiting():
    # Double-clicking a game twice shouldn't mean downloading that shit
    # twice.
    scheduler = download_queue.DownloadScheduler()
    scheduler.enqueue({"idx": 0, "product_id": 7})
    scheduler.enqueue({"idx": 0, "product_id": 7})

    assert [(j["row_idx"], j["product_id"]) for j in scheduler.idle_queue] == [(0, 7)]


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_enqueue_on_an_idle_scheduler_just_waits_for_start():
    # Adding a game is not clicking Start. And an idle scheduler yelling
    # "finished!" every time you add a row would be some unhinged shit.
    scheduler = download_queue.DownloadScheduler()
    finished_events = []
    scheduler.finished.connect(lambda: finished_events.append(True))

    scheduler.enqueue({"idx": 0, "product_id": 0})

    assert scheduler.active_queue == []
    assert [j["row_idx"] for j in scheduler.idle_queue] == [0]
    assert finished_events == []


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_enqueue_mid_run_grabs_a_free_slot_right_away():
    scheduler = make_scheduler(concurrency=2, count=1)
    scheduler.schedule()

    scheduler.enqueue({"idx": 1, "product_id": 1})

    assert [j["row_idx"] for j in scheduler.active_queue] == [0, 1]
    assert scheduler.idle_queue == []


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_enqueue_mid_run_waits_its_turn_when_every_slot_is_busy():
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.schedule()

    scheduler.enqueue({"idx": 1, "product_id": 1})
    assert [j["row_idx"] for j in scheduler.active_queue] == [0]

    scheduler.active_queue[0]["worker"].succeeded.emit()

    assert [j["row_idx"] for j in scheduler.active_queue] == [1]


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_enqueue_while_pausing_does_not_sneak_a_new_download_in():
    # Pause was clicked and the active worker is still packing its shit up.
    # A game added right then doesn't get to cut the line, it waits for
    # Resume like everyone else.
    scheduler = make_scheduler(concurrency=2, count=1)
    scheduler.schedule()
    scheduler.pause_all()

    scheduler.enqueue({"idx": 1, "product_id": 1})

    assert [j["row_idx"] for j in scheduler.active_queue] == [0]
    assert [j["row_idx"] for j in scheduler.idle_queue] == [1]


def test_set_concurrency_refuses_zero():
    scheduler = download_queue.DownloadScheduler()

    with pytest.raises(ValueError):
        scheduler.set_concurrency(0)

    assert scheduler.max_tokens == 1
    assert scheduler.tokens == 1


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_set_concurrency_raised_mid_run_fills_the_new_slots_on_the_next_schedule():
    scheduler = make_scheduler(concurrency=1, count=3)
    scheduler.schedule()

    scheduler.set_concurrency(3)
    assert scheduler.tokens == 2

    scheduler.active_queue[0]["worker"].succeeded.emit()

    assert [j["row_idx"] for j in scheduler.active_queue] == [1, 2]
    assert scheduler.tokens == 1


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_set_concurrency_lowered_mid_run_lets_the_extra_workers_drain_first():
    # Nobody gets jacked for being over the new limit, but nobody new gets
    # to start either until we're actually back under the damn thing.
    scheduler = make_scheduler(concurrency=3, count=4)
    scheduler.schedule()

    scheduler.set_concurrency(1)
    assert scheduler.tokens == -2

    scheduler.active_queue[0]["worker"].succeeded.emit()
    scheduler.active_queue[0]["worker"].succeeded.emit()
    assert [j["row_idx"] for j in scheduler.active_queue] == [2]
    assert [j["row_idx"] for j in scheduler.idle_queue] == [3]

    scheduler.active_queue[0]["worker"].succeeded.emit()

    assert [j["row_idx"] for j in scheduler.active_queue] == [3]
    assert scheduler.tokens == 0


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_a_stop_does_not_haunt_the_next_run_on_the_same_scheduler():
    # Regression: _stopped_flag never got cleared, so one Cancel turned every
    # later run's "finished" into "stopped". One click and the scheduler held
    # a grudge for the rest of its fucking life.
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.schedule()
    scheduler.stop_all()
    scheduler.active_queue[0]["worker"].stopped.emit()
    finished_events, stopped_events = [], []
    scheduler.finished.connect(lambda: finished_events.append(True))
    scheduler.stopped.connect(lambda: stopped_events.append(True))

    scheduler.enqueue({"idx": 1, "product_id": 1})
    scheduler.schedule()
    scheduler.active_queue[0]["worker"].succeeded.emit()

    assert finished_events == [True]
    assert stopped_events == []


@patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)
def test_reap_waits_for_the_thread_to_actually_die_before_dropping_it():
    # Regression: _reap binned the only reference to a worker that had sent
    # its last signal but hadn't finished unwinding run() yet. Qt saw a
    # running QThread get destroyed and took the whole fucking app down
    # with it, reliably on Cancel.
    for signal in ("succeeded", "stopped", "failed", "paused"):
        scheduler = make_scheduler(concurrency=1, count=1)
        scheduler.schedule()
        worker = scheduler.active_queue[0]["worker"]

        emit = getattr(worker, signal).emit
        if signal == "failed":
            emit("boom")
        elif signal == "paused":
            emit({})
        else:
            emit()

        assert getattr(worker, "waited", False), f"{signal} dropped the worker without waiting"
