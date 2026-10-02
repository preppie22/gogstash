import errno
import hashlib
import os
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


def fake_product(product_id, slug):
    return {**FAKE_PRODUCT, "id": product_id, "title": slug, "slug": slug}


@pytest.fixture(autouse=True)
def db():
    library_db._create_db(force=True)
    library_db.update_downloadables([FAKE_DOWNLOADABLE])
    library_db.update_products([FAKE_PRODUCT, fake_product(333, "polyglot-game"), fake_product(444, "monoglot-game")])


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


# Shaped like Iratus: Lord of the Dead, where Linux speaks German but
# Windows only ever learned English.
FAKE_MULTILINGUAL = {
    "id": 333,
    "downloads": {
        "installers": [
            {
                "id": f"installer_{os}_{lang}",
                "name": "Polyglot Game",
                "os": os,
                "language": lang,
                "total_size": 1000,
                "files": [
                    {"id": f"{os}_{lang}", "size": 1000, "downlink": f"https://example.com/{os}_{lang}"},
                ],
            }
            for os, lang in [("linux", "en"), ("linux", "de"), ("windows", "en")]
        ],
        "patches": [
            {
                "id": f"patch_{os}_{lang}",
                "name": "Patch",
                "os": os,
                "language": lang,
                "total_size": 100,
                "files": [
                    {"id": f"patch_{os}_{lang}", "size": 100, "downlink": f"https://example.com/patch_{os}_{lang}"},
                ],
            }
            for os, lang in [("linux", "en"), ("linux", "de"), ("windows", "en")]
        ],
        "bonus_content": [
            {
                "id": "polyglot_bonus",
                "name": "soundtrack",
                "type": "audio",
                "total_size": 50,
                # No "language" key, same as GOG's real bonus content.
                "files": [
                    {"id": "polyglot_bonus", "size": 50, "downlink": "https://example.com/polyglot_bonus"},
                ],
            }
        ],
    },
}


def polyglot_files(languages):
    library_db.update_downloadables([FAKE_MULTILINGUAL])
    settings.update_setting("languages", languages)
    settings.update_setting("bonus_content", True)
    return {f["file"] for f in download_queue.generate_download_list((333,))}


def test_default_languages_download_english_only():
    # DEFAULT_SETTINGS has languages: ['en']
    library_db.update_downloadables([FAKE_MULTILINGUAL])

    files = {f["file"] for f in download_queue.generate_download_list((333,))}

    assert {"linux_en", "windows_en", "patch_linux_en", "patch_windows_en"} <= files
    assert "linux_de" not in files
    assert "patch_linux_de" not in files


def test_chosen_language_replaces_english_when_available():
    # English is the fallback, not a chaperone. Letting it tag along with
    # every chosen language is how a 12 GB game grows toward 118 GB (#10).
    files = polyglot_files(["de"])

    assert "linux_de" in files
    assert "linux_en" not in files


def test_os_without_the_chosen_language_falls_back_to_english():
    # German on Linux doesn't mean Windows sprechen Deutsch. If the fallback
    # is decided per game instead of per OS, Windows downloads nothing.
    files = polyglot_files(["de"])

    assert "windows_en" in files


def test_game_without_any_chosen_language_falls_back_to_english():
    files = polyglot_files(["pl"])

    assert {"linux_en", "windows_en"} <= files
    assert "linux_de" not in files


def test_multiple_chosen_languages_are_all_downloaded():
    files = polyglot_files(["de", "en"])

    assert {"linux_de", "linux_en", "windows_en"} <= files


def test_empty_language_setting_falls_back_to_english():
    files = polyglot_files([])

    assert {"linux_en", "windows_en"} <= files
    assert "linux_de" not in files


def test_patches_follow_the_installer_language_of_their_os():
    files = polyglot_files(["de"])

    assert "patch_linux_de" in files
    assert "patch_linux_en" not in files
    assert "patch_windows_en" in files  # rides along with the Windows fallback


def test_bonus_content_ignores_the_language_filter():
    # Bonus content has no language. A soundtrack is a soundtrack in any tongue.
    files = polyglot_files(["de"])

    assert "polyglot_bonus" in files


def test_language_fallback_is_decided_per_game_in_a_batch():
    # Two games, one call, the way the game list asks. If the chosen
    # languages were pooled across the batch, the polyglot's German Linux
    # build would convince everyone Linux speaks German, and the
    # monoglot's only Linux installer would quietly vanish.
    monoglot = {
        "id": 444,
        "downloads": {
            "installers": [
                {
                    "id": "installer_linux_en_mono",
                    "name": "Monoglot Game",
                    "os": "linux",
                    "language": "en",
                    "total_size": 1000,
                    "files": [
                        {"id": "mono_linux_en", "size": 1000, "downlink": "https://example.com/mono_linux_en"},
                    ],
                }
            ],
        },
    }
    library_db.update_downloadables([FAKE_MULTILINGUAL, monoglot])
    settings.update_setting("languages", ["de"])

    files = {f["file"] for f in download_queue.generate_download_list((333, 444))}

    assert "linux_de" in files
    assert "linux_en" not in files
    assert "mono_linux_en" in files


def fake_response():
    # The worker holds its download in a `with` block now, and a MagicMock's
    # __enter__ hands back a brand new stranger instead of itself. Every
    # carefully staged header and chunk would go straight in the bin.
    response = MagicMock()
    response.__enter__.return_value = response
    return response


def make_streamed_response(chunks, status_code=200, headers=None):
    # A real dict for headers, since a bare MagicMock's Content-Length int()s
    # to 1 and every fake file would swear it's a single byte long.
    response = fake_response()
    response.status_code = status_code
    response.iter_content.return_value = chunks
    response.headers = headers if headers is not None else {"Content-Length": str(sum(len(c) for c in chunks))}
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
        self.disk_full = []
        thread.disk_full.connect(lambda resume_link: self.disk_full.append(resume_link))
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


def make_worker(resume_link=None, file_queue=None):
    # Workers are handed their file list by the scheduler now. Build it the
    # same way the scheduler does, off whatever the test's settings say.
    if file_queue is None:
        file_queue = download_queue.generate_download_list((111,))
    return download_queue.DownloadWorkerThread(111, file_queue, resume_link)


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

    thread = make_worker()
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

    thread = make_worker({"partpath": part_path, "downlink": "https://example.com/file1"})
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

    thread = make_worker({"partpath": part_path, "downlink": "https://example.com/file1"})
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
    manifest.add_file(game_dir, renamed, category="bonus_content", downlink="", db_size=-1, checksum="", timestamp=42.0)
    response = fake_response()
    response.status_code = 200
    response.headers = {"Content-Length": "10"}
    response.iter_content.side_effect = AssertionError("should never read the byte stream when skipping")
    mock_get.side_effect = [response]

    thread = make_worker(file_queue=[bonus_file])
    events = Watcher(thread)

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
    response = fake_response()
    response.status_code = 206
    response.iter_content.return_value = [b"b" * 6]
    response.headers = {"Content-Length": "6"}  # just the remaining bytes, like a real 206
    mock_get.side_effect = [response]

    thread = make_worker({"partpath": part_path, "downlink": "https://example.com/bonus1"}, file_queue=[bonus_file])
    events = Watcher(thread)

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
    manifest.add_file(game_dir, existing_file, category="installers", downlink="", db_size=-1, checksum=checksum, timestamp=42.0)
    # If the skip check fails to short-circuit, iter_content() gets called and
    # blows up loudly instead of quietly re-downloading something we already have.
    stream_response = fake_response()
    stream_response.iter_content.side_effect = AssertionError("should never read the byte stream when skipping")
    mock_get.side_effect = [make_checksum_response(checksum), stream_response]

    thread = make_worker()
    events = Watcher(thread)

    thread.run()

    assert events.failed == []
    assert events.succeeded == 1
    # Skipped files still get reported (so the log can say so), flagged so the
    # scheduler knows it's a backfill of an old entry, not a fresh download.
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
    manifest.add_file(game_dir, existing_file, category="installers", downlink="", db_size=-1, checksum=checksum, timestamp=42.0)
    stream_response = fake_response()
    stream_response.iter_content.side_effect = AssertionError("should never read the byte stream when skipping")
    mock_get.side_effect = [make_checksum_response(checksum), stream_response]

    thread = make_worker()
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
    manifest.add_file(game_dir, existing_file, category="installers", downlink="", db_size=-1, checksum="stale-checksum", timestamp=1.0)
    chunk_a = b"a" * 400
    chunk_b = b"b" * 600
    fresh_checksum = hashlib.md5(chunk_a + chunk_b).hexdigest()
    mock_get.side_effect = [
        make_checksum_response(fresh_checksum),
        make_streamed_response([chunk_a, chunk_b]),
    ]

    thread = make_worker()
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
    manifest.add_file(game_dir, existing_file, category="installers", downlink="", db_size=-1, checksum=checksum, timestamp=1.0)
    bonus_chunk = b"x" * 10
    bonus_response = fake_response()
    bonus_response.headers = {"Content-Length": str(len(bonus_chunk))}
    bonus_response.iter_content.return_value = [bonus_chunk]
    stream_response = fake_response()
    stream_response.iter_content.side_effect = AssertionError("should never read the byte stream when skipping")
    # generate_download_list() yields bonus_content before the installer for
    # this fixture. Bonus content has no checksum manifest, so its only request
    # is the download; the installer then asks for its checksum and its stream.
    mock_get.side_effect = [bonus_response, make_checksum_response(checksum), stream_response]

    thread = make_worker()
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
    broken_response = fake_response()
    broken_response.headers = {}
    broken_response.iter_content.side_effect = RuntimeError("connection reset")
    mock_get.side_effect = [make_checksum_response("irrelevant"), broken_response]

    thread = make_worker()
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

    thread = make_worker()
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

    thread = make_worker()
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

    thread = make_worker()
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


def _stop_after_first_chunk(mock_get):
    mock_get.side_effect = [
        make_checksum_response("irrelevant"),
        make_streamed_response([b"a" * 400, b"b" * 600]),
    ]
    thread = make_worker()
    thread.update_progress = lambda: thread.stop_worker()
    return thread


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_stopping_a_brand_new_game_leaves_no_empty_folders_behind(mock_resolve, mock_get, tmp_path):
    # Regression: cancelling a game's very first download left
    # fake-game/installer_windows_en/ sitting there, empty, forever, like a
    # tombstone for a game you changed your mind about.
    single_installer_setup(mock_resolve, tmp_path)
    thread = _stop_after_first_chunk(mock_get)
    events = Watcher(thread)

    thread.run()

    assert events.stopped == 1
    assert not (tmp_path / "fake-game").exists()
    assert tmp_path.exists()  # tidy the game's folder, not the whole download folder


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_stopping_a_game_with_earlier_downloads_only_tidies_what_is_empty(mock_resolve, mock_get, tmp_path):
    # Regression: an unconditional rmdir() on a game folder that already held
    # a manifest blew up with "Directory not empty", and the stop came back
    # as a red "Failed" row instead of a quiet "Queued" one.
    game_dir = single_installer_setup(mock_resolve, tmp_path).parent
    (game_dir / "extras").mkdir(parents=True)
    (game_dir / ".gogstash.manifest").write_text("{}")
    (game_dir / "patches").mkdir()
    (game_dir / "patches" / "patch_1.exe").write_bytes(b"finished, keep me")
    (game_dir / "patches" / "patch_2.exe.part").write_bytes(b"left over from a failed run")
    thread = _stop_after_first_chunk(mock_get)
    events = Watcher(thread)

    thread.run()

    assert events.stopped == 1
    assert events.failed == []
    assert (game_dir / ".gogstash.manifest").exists()
    assert (game_dir / "patches" / "patch_1.exe").read_bytes() == b"finished, keep me"
    assert not (game_dir / "patches" / "patch_2.exe.part").exists()
    assert not (game_dir / "installer_windows_en").exists()
    assert not (game_dir / "extras").exists()


# --- disk fills up mid-download ---

class _FillingFile:
    """Wraps a real .part file and runs out of disk after a set number of
    writes, or on close. Python buffers writes, so a real full disk can
    surface either way: from a write() or from the flush on close."""

    def __init__(self, fp, writes_that_fit, error_errno, on_close):
        self._fp = fp
        self._writes_left = writes_that_fit
        self._errno = error_errno
        self._on_close = on_close

    def write(self, data):
        if self._writes_left == 0:
            raise OSError(self._errno, os.strerror(self._errno))
        self._writes_left -= 1
        return self._fp.write(data)

    def __getattr__(self, name):
        return getattr(self._fp, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._fp.close()
        if self._on_close and exc[0] is None:
            raise OSError(self._errno, os.strerror(self._errno))
        return False


def _disk_fills_up(writes_that_fit=1, error_errno=errno.ENOSPC, on_close=False):
    real_open = open

    def fake_open(path, mode="r", *args, **kwargs):
        fp = real_open(path, mode, *args, **kwargs)
        if str(path).endswith(".part") and "r" not in mode:
            return _FillingFile(fp, writes_that_fit, error_errno, on_close)
        return fp

    return patch("gogstash.download_queue.open", fake_open, create=True)


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_a_full_disk_mid_file_reports_disk_full_and_keeps_the_part_file(mock_resolve, mock_get, tmp_path):
    # Regression: errno 28 fell into the catch-all and came out as a plain
    # "failed", the next game got sent straight into the same full disk, and
    # the user never found out the fix was "delete some memes and resume".
    game_dir = single_installer_setup(mock_resolve, tmp_path)
    mock_get.side_effect = [
        make_checksum_response("irrelevant"),
        make_streamed_response([b"a" * 400, b"b" * 600]),
    ]
    thread = make_worker()
    events = Watcher(thread)

    with _disk_fills_up(writes_that_fit=1):
        thread.run()

    part_path = game_dir / "setup_fake_game.exe.part"
    assert events.disk_full == [{"partpath": part_path, "downlink": "https://example.com/file1"}]
    assert events.failed == []
    assert events.paused == []
    assert events.succeeded == 0
    assert events.fetched == []  # nothing to log yet, it isn't over
    assert part_path.read_bytes() == b"a" * 400


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_a_full_disk_that_only_shows_up_when_the_file_closes_is_still_disk_full(mock_resolve, mock_get, tmp_path):
    # Every write() "worked" because it only went into Python's buffer. The
    # bill arrives at close(), and it still shouldn't be paid as a failure.
    game_dir = single_installer_setup(mock_resolve, tmp_path)
    mock_get.side_effect = [
        make_checksum_response("irrelevant"),
        make_streamed_response([b"a" * 400, b"b" * 600]),
    ]
    thread = make_worker()
    events = Watcher(thread)

    with _disk_fills_up(writes_that_fit=2, on_close=True):
        thread.run()

    assert len(events.disk_full) == 1
    assert events.failed == []
    assert (game_dir / "setup_fake_game.exe.part").exists()
    assert not (game_dir / "setup_fake_game.exe").exists()  # never renamed into place


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_other_write_errors_still_fail_the_game(mock_resolve, mock_get, tmp_path):
    # A dying USB stick is not a full one. EIO keeps its old, sadder path.
    single_installer_setup(mock_resolve, tmp_path)
    mock_get.side_effect = [
        make_checksum_response("irrelevant"),
        make_streamed_response([b"a" * 400, b"b" * 600]),
    ]
    thread = make_worker()
    events = Watcher(thread)

    with _disk_fills_up(writes_that_fit=1, error_errno=errno.EIO):
        thread.run()

    assert events.disk_full == []
    assert len(events.failed) == 1


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_a_download_cut_short_by_a_full_disk_resumes_into_a_correct_file(mock_resolve, mock_get, tmp_path):
    # The promise behind keeping the .part: hand its payload to a fresh
    # worker once there's room again, and the finished file checksums clean.
    game_dir = single_installer_setup(mock_resolve, tmp_path)
    full = b"a" * 400 + b"b" * 600
    checksum = hashlib.md5(full).hexdigest()
    mock_get.side_effect = [
        make_checksum_response(checksum),
        make_streamed_response([full[:400], full[400:]]),
    ]
    first = make_worker()
    first_events = Watcher(first)
    with _disk_fills_up(writes_that_fit=1):
        first.run()
    [payload] = first_events.disk_full

    mock_get.side_effect = [
        make_checksum_response(checksum),
        make_streamed_response([full[400:]], status_code=206),
    ]
    second = make_worker(payload)
    second_events = Watcher(second)
    second.run()

    assert mock_get.call_args_list[-1].kwargs["headers"] == {"Range": "bytes=400-"}
    assert second_events.failed == []
    assert second_events.succeeded == 1
    assert (game_dir / "setup_fake_game.exe").read_bytes() == full


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
    thread = make_worker()

    def chunks_then_stop():
        yield chunk_a
        yield chunk_b
        thread.stop_worker()  # doesn't fire until the loop comes back asking for seconds

    response = fake_response()
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

    thread = make_worker()
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
    thread = make_worker()

    def chunks_then_pause():
        yield chunk_a
        yield chunk_b
        thread.pause_worker()  # lands after the last chunk, before the loop notices

    response = fake_response()
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
def test_download_worker_pause_landing_on_the_last_chunk_finishes_the_file_instead_of_pausing_on_it(
    mock_resolve, mock_get, tmp_path
):
    # Regression, caught in a live run: the pause landed right as the last
    # chunk hit the disk, so the worker paused holding a .part that was
    # already whole. Resume then asked the CDN for "bytes=<size>-", got a
    # 416 Range Not Satisfiable for its trouble, marked a perfectly good
    # download as failed and left the .part lying around like a sock
    # under the bed.
    game_dir = single_installer_setup(mock_resolve, tmp_path)
    chunk_a = b"a" * 400
    chunk_b = b"b" * 600
    checksum = hashlib.md5(chunk_a + chunk_b).hexdigest()
    mock_get.side_effect = [make_checksum_response(checksum), make_streamed_response([chunk_a, chunk_b])]
    thread = make_worker()
    thread.update_progress = lambda: thread.pause_worker() if thread.fetched_size == 1000 else None
    events = Watcher(thread)

    thread.run()

    assert events.failed == []
    assert events.succeeded == 0
    assert events.paused == [{}]  # paused between files, nothing to resume mid-way
    written = game_dir / "setup_fake_game.exe"
    assert written.read_bytes() == chunk_a + chunk_b
    assert not (game_dir / "setup_fake_game.exe.part").exists()


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_stop_landing_on_the_last_chunk_keeps_the_finished_file(
    mock_resolve, mock_get, tmp_path
):
    # Same timing, Stop edition: the whole file was on disk and would have
    # passed its checksum, and the worker binned it anyway. Bandwidth isn't
    # free, keep the thing.
    game_dir = single_installer_setup(mock_resolve, tmp_path)
    chunk_a = b"a" * 400
    chunk_b = b"b" * 600
    checksum = hashlib.md5(chunk_a + chunk_b).hexdigest()
    mock_get.side_effect = [make_checksum_response(checksum), make_streamed_response([chunk_a, chunk_b])]
    thread = make_worker()
    thread.update_progress = lambda: thread.stop_worker() if thread.fetched_size == 1000 else None
    events = Watcher(thread)

    thread.run()

    assert events.failed == []
    assert events.succeeded == 0
    assert events.stopped == 1
    written = game_dir / "setup_fake_game.exe"
    assert [entry["filepath"] for entry in events.fetched] == [written]
    assert written.read_bytes() == chunk_a + chunk_b
    assert not (game_dir / "setup_fake_game.exe.part").exists()


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_can_still_pause_mid_file_when_the_server_wont_say_how_big_it_is(
    mock_resolve, mock_get, tmp_path
):
    # No Content-Length means content_length is 0, and "0 bytes left"
    # must not read as "done, ignore the pause button" for the whole file.
    game_dir = single_installer_setup(mock_resolve, tmp_path)
    mock_get.side_effect = [
        make_checksum_response("irrelevant"),
        make_streamed_response([b"a" * 400, b"b" * 600], headers={}),
    ]
    thread = make_worker()
    thread.update_progress = lambda: thread.pause_worker()
    events = Watcher(thread)

    thread.run()

    part_path = game_dir / "setup_fake_game.exe.part"
    assert events.paused == [{"partpath": part_path, "downlink": "https://example.com/file1"}]
    assert part_path.read_bytes() == b"a" * 400


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_can_still_stop_mid_file_when_the_server_wont_say_how_big_it_is(
    mock_resolve, mock_get, tmp_path
):
    game_dir = single_installer_setup(mock_resolve, tmp_path)
    mock_get.side_effect = [
        make_checksum_response("irrelevant"),
        make_streamed_response([b"a" * 400, b"b" * 600], headers={}),
    ]
    thread = make_worker()
    thread.update_progress = lambda: thread.stop_worker()
    events = Watcher(thread)

    thread.run()

    assert events.stopped == 1
    assert not (game_dir / "setup_fake_game.exe.part").exists()
    assert not (game_dir / "setup_fake_game.exe").exists()


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

    thread = make_worker()
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
    disk_full = Signal(dict)

    def __init__(self, product_id, file_queue=None, resume_link=None):
        super().__init__()
        self.product_id = product_id
        self.file_queue = file_queue
        self.resume_link = resume_link
        # The free-space check peeks at these on every active job.
        self.total_size = sum(f["size"] for f in file_queue or [])
        self.fetched_size = 0
        self.stop_worker = MagicMock()
        self.pause_worker = MagicMock()

    def start(self):
        pass

    def wait(self):
        # Never actually ran, so there's jack shit to wait for.
        self.waited = True
        return True


def canned_download_list(product_ids):
    # One tiny file per game, so scheduler tests never go rummaging through
    # the DB or a manifest for games that only exist as row numbers.
    return [{
        "directory": "installer_windows_en", "category": "installers", "file": f"file_{pid}",
        "os": "windows", "size": 1, "downlink": f"https://example.com/{pid}",
    } for pid in product_ids]


def with_fake_workers(test):
    test = patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker)(test)
    return patch("gogstash.download_queue.generate_download_list", canned_download_list)(test)


def make_scheduler(concurrency, count):
    # enqueue() is the only way in now. Idle schedulers just queue, so this
    # still leaves every job waiting for the test to call schedule().
    scheduler = download_queue.DownloadScheduler(concurrency)
    for i in range(count):
        scheduler.enqueue({"idx": i, "product_id": i})
    return scheduler


def _pause_active_worker(job, resume_link=None):
    job["worker"].paused.emit({} if resume_link is None else resume_link)


@with_fake_workers
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


@with_fake_workers
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


@with_fake_workers
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


@with_fake_workers
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


@with_fake_workers
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


@with_fake_workers
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
        "downlink": f"https://example.com/{name}", "size": 1, "db_size": 1, "checksum": checksum, **extra,
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


@with_fake_workers
def test_game_succeeded_signal_carries_just_the_row():
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.schedule()
    succeeded = []
    scheduler.game_succeeded.connect(lambda row_idx: succeeded.append(row_idx))

    scheduler.active_queue[0]["worker"].succeeded.emit()

    assert succeeded == [0]


@with_fake_workers
def test_game_failed_signal_carries_the_row_and_the_reason():
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.schedule()
    failed = []
    scheduler.game_failed.connect(lambda row_idx, msg: failed.append((row_idx, msg)))

    scheduler.active_queue[0]["worker"].failed.emit("connection reset")

    assert failed == [(0, "connection reset")]
    assert scheduler.active_queue == []  # the job got reaped and its slot freed


@with_fake_workers
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


@with_fake_workers
def test_fetched_file_is_logged_the_moment_it_arrives_not_when_the_game_ends(tmp_path):
    # The point of the scheduler owning the log: a file that finished before a
    # pause (or before the app got killed) already has its line on disk.
    scheduler, worker, game_dir = _scheduler_with_game_files(tmp_path, "a.exe")

    worker.fetched.emit(_fetched_entry(game_dir, "a.exe", checksum="abc123", size=500))

    [line] = _log_lines()
    assert line.startswith("[")
    assert f"{game_dir / 'a.exe'} : Fetched 500 Bytes | md5: abc123" in line
    assert scheduler.active_queue  # the game itself hasn't finished


@with_fake_workers
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


@with_fake_workers
def test_skipped_fetch_backfills_an_old_manifest_entry_with_its_downlink(tmp_path):
    # A pre-upgrade entry only knows its filename. The worker's skip is the one
    # moment both the filename and the downlink are in the same room, so
    # that's when the entry gets its new fields, no network trip required.
    scheduler, worker, game_dir = _scheduler_with_game_files(tmp_path, "setup.exe")
    (game_dir / manifest.MANIFEST_FILE).write_text(
        '{"setup.exe": {"category": "installers", "size": 1, "checksum": "abc123", "fetched_at": 1.0}}'
    )

    worker.fetched.emit(_fetched_entry(game_dir, "setup.exe", checksum="abc123", db_size=900, skipped=True))

    recorded = manifest.stat_file(game_dir, game_dir / "setup.exe")
    assert recorded["downlink"] == "https://example.com/setup.exe"
    assert recorded["db_size"] == 900
    assert recorded["checksum"] == "abc123"
    [line] = _log_lines()
    assert "setup.exe : Skipped | Already up to date" in line


@with_fake_workers
def test_skip_of_a_renamed_file_is_logged_without_inventing_an_entry_for_the_missing_path(tmp_path):
    # Regression: check_exist can match a file the user renamed, so the
    # skipped path doesn't exist. Writing an entry for it made add_file raise
    # FileNotFoundError right inside the slot, and the log line died with it.
    scheduler, worker, game_dir = _scheduler_with_game_files(tmp_path, "setup (my copy).exe")

    worker.fetched.emit(_fetched_entry(game_dir, "setup.exe", skipped=True))

    assert manifest.stat_file(game_dir, game_dir / "setup.exe") == {}
    [line] = _log_lines()
    assert "setup.exe : Skipped" in line


@with_fake_workers
def test_a_fresh_download_replaces_an_entry_that_already_had_a_downlink(tmp_path):
    # Regression: GOG updates an installer and keeps the filename. The new copy
    # has to overwrite the old entry, or its stale db_size never matches again
    # and the file gets downloaded fresh on every single run, forever.
    scheduler, worker, game_dir = _scheduler_with_game_files(tmp_path, "setup.exe")
    manifest.add_file(game_dir, game_dir / "setup.exe", category="installers",
                      downlink="https://example.com/setup.exe", db_size=100, checksum="old-sum", timestamp=1.0)

    worker.fetched.emit(_fetched_entry(game_dir, "setup.exe", checksum="new-sum", db_size=200))

    recorded = manifest.stat_file(game_dir, game_dir / "setup.exe")
    assert (recorded["db_size"], recorded["checksum"]) == (200, "new-sum")


@with_fake_workers
def test_every_file_of_a_fully_cached_game_gets_its_own_log_line(tmp_path):
    scheduler, worker, game_dir = _scheduler_with_game_files(tmp_path, "a.exe", "b.exe", "c.exe")

    for name in ("a.exe", "b.exe", "c.exe"):
        worker.fetched.emit(_fetched_entry(game_dir, name, skipped=True))

    lines = _log_lines()
    assert len(lines) == 3
    assert all("Skipped" in line for line in lines)


@with_fake_workers
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


@with_fake_workers
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


@with_fake_workers
def test_pause_all_pauses_active_workers_and_leaves_pending_ones_alone():
    scheduler = make_scheduler(concurrency=1, count=2)
    scheduler.schedule()
    active_worker = scheduler.active_queue[0]["worker"]

    scheduler.pause_all()

    active_worker.pause_worker.assert_called_once()
    active_worker.stop_worker.assert_not_called()
    assert [job["row_idx"] for job in scheduler.idle_queue] == [1]
    assert scheduler.idle_queue[0]["stopped"] is False


@with_fake_workers
def test_pause_all_twice_only_pauses_workers_once():
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.schedule()
    active_worker = scheduler.active_queue[0]["worker"]

    scheduler.pause_all()
    scheduler.pause_all()  # panicked double-click, should be a no-op

    active_worker.pause_worker.assert_called_once()


@with_fake_workers
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


@with_fake_workers
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


@with_fake_workers
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


@with_fake_workers
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


@with_fake_workers
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


@with_fake_workers
def test_resume_all_is_a_noop_when_nothing_is_paused():
    scheduler = make_scheduler(concurrency=1, count=2)
    scheduler.schedule()
    worker = scheduler.active_queue[0]["worker"]

    scheduler.resume_all()

    assert [j["row_idx"] for j in scheduler.active_queue] == [0]
    assert scheduler.active_queue[0]["worker"] is worker  # not rebuilt out from under the running download


@with_fake_workers
def test_stop_all_while_paused_reports_everything_stopped_and_deletes_part_files(tmp_path):
    scheduler = make_scheduler(concurrency=1, count=2)
    scheduler.schedule()
    job = scheduler.active_queue[0]
    part_path = tmp_path / "game" / "installer" / "game.exe.part"
    part_path.parent.mkdir(parents=True)
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
    assert not (tmp_path / "game").exists()  # and the folders it was sitting in
    assert scheduler.paused_queue == []
    assert stopped_events == [True]
    assert finished_events == []


@with_fake_workers
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


@with_fake_workers
def test_stop_all_while_paused_tolerates_a_part_file_that_already_vanished(tmp_path):
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.schedule()
    job = scheduler.active_queue[0]
    stopped_events = []
    scheduler.stopped.connect(lambda: stopped_events.append(True))
    scheduler.pause_all()
    _pause_active_worker(job, {"partpath": tmp_path / "game" / "installer" / "ghost.part", "downlink": "x"})

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
    thread = make_worker()
    thread.update_progress = lambda: thread.pause_worker()
    events = Watcher(thread)
    thread.run()
    [payload] = events.paused
    part_path = game_dir / "setup_fake_game.exe.part"
    assert part_path.exists()

    with patch("gogstash.download_queue.DownloadWorkerThread", FakeWorker), \
            patch("gogstash.download_queue.generate_download_list", canned_download_list):
        scheduler = make_scheduler(concurrency=1, count=1)
        scheduler.schedule()
        scheduler.pause_all()
        _pause_active_worker(scheduler.active_queue[0], payload)

        scheduler.stop_all()

    assert not part_path.exists()
    assert not (tmp_path / "fake-game").exists()  # nor the folders it was sitting in


@with_fake_workers
def test_enqueue_ignores_a_row_that_is_already_waiting():
    # Double-clicking a game twice shouldn't mean downloading that shit
    # twice.
    scheduler = download_queue.DownloadScheduler()
    scheduler.enqueue({"idx": 0, "product_id": 7})
    scheduler.enqueue({"idx": 0, "product_id": 7})

    assert [(j["row_idx"], j["product_id"]) for j in scheduler.idle_queue] == [(0, 7)]


@with_fake_workers
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


@with_fake_workers
def test_enqueue_mid_run_grabs_a_free_slot_right_away():
    scheduler = make_scheduler(concurrency=2, count=1)
    scheduler.schedule()

    scheduler.enqueue({"idx": 1, "product_id": 1})

    assert [j["row_idx"] for j in scheduler.active_queue] == [0, 1]
    assert scheduler.idle_queue == []


@with_fake_workers
def test_enqueue_mid_run_waits_its_turn_when_every_slot_is_busy():
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.schedule()

    scheduler.enqueue({"idx": 1, "product_id": 1})
    assert [j["row_idx"] for j in scheduler.active_queue] == [0]

    scheduler.active_queue[0]["worker"].succeeded.emit()

    assert [j["row_idx"] for j in scheduler.active_queue] == [1]


@with_fake_workers
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


@with_fake_workers
def test_set_concurrency_raised_mid_run_fills_the_new_slots_on_the_next_schedule():
    scheduler = make_scheduler(concurrency=1, count=3)
    scheduler.schedule()

    scheduler.set_concurrency(3)
    assert scheduler.tokens == 2

    scheduler.active_queue[0]["worker"].succeeded.emit()

    assert [j["row_idx"] for j in scheduler.active_queue] == [1, 2]
    assert scheduler.tokens == 1


@with_fake_workers
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


@with_fake_workers
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


@with_fake_workers
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


@with_fake_workers
def test_game_started_announces_the_row_not_the_product_id():
    # Regression: it emitted the product id, so the window went looking for
    # row 1207658924 and found a None instead of a dot to paint blue.
    # make_scheduler uses idx == product_id, which would hide exactly this.
    scheduler = download_queue.DownloadScheduler(2)
    scheduler.enqueue({"idx": 0, "product_id": 1207658924})
    scheduler.enqueue({"idx": 1, "product_id": 1207664663})
    started = []
    scheduler.game_started.connect(started.append)

    scheduler.schedule()

    assert started == [0, 1]


# --- skipping what's already on disk ---

def _record_file1(tmp_path, db_size=1000, downlink="https://example.com/file1"):
    settings.update_setting("download_path", str(tmp_path))
    game_dir = tmp_path / "fake-game"
    installer = game_dir / "installer_windows_en" / "setup_fake_game.exe"
    installer.parent.mkdir(parents=True)
    installer.write_bytes(b"x" * 10)
    manifest.add_file(game_dir, installer, category="installers", downlink=downlink, db_size=db_size,
                      checksum="abc", timestamp=1.0)
    return installer


def test_download_list_leaves_out_a_file_already_on_disk(tmp_path):
    _record_file1(tmp_path)

    result = download_queue.generate_download_list((111,))

    assert by_file(result, "file1") is None
    assert by_file(result, "patch1") is not None  # never downloaded, still wanted


def test_download_list_keeps_a_file_whose_listing_size_changed(tmp_path):
    # Same downlink slot, new size on GOG's side: that's an update, go get it.
    _record_file1(tmp_path, db_size=999)

    assert by_file(download_queue.generate_download_list((111,)), "file1") is not None


def test_download_list_keeps_a_file_the_user_deleted(tmp_path):
    _record_file1(tmp_path).unlink()

    assert by_file(download_queue.generate_download_list((111,)), "file1") is not None


def test_download_list_keeps_a_file_from_a_manifest_that_predates_downlinks(tmp_path):
    # The worker will recognise it and skip it, and backfill the entry on the way.
    _record_file1(tmp_path, downlink="", db_size=-1)

    assert by_file(download_queue.generate_download_list((111,)), "file1") is not None


def test_download_list_reads_each_games_manifest_once_not_once_per_file(tmp_path):
    settings.update_setting("download_path", str(tmp_path))

    with patch("gogstash.manifest.read_manifest", wraps=manifest.read_manifest) as spy:
        result = download_queue.generate_download_list((111,))

    assert len(result) == 2  # installer + patch, so a per-file read would show up as 2
    assert spy.call_count == 1


def test_worker_knows_its_total_before_it_ever_runs():
    # Regression: the total used to be set inside run(), so a job dispatched a
    # moment ago counted as 0 bytes to the free-space check until its thread
    # got around to it. A whole game's worth of blind spot.
    files = canned_download_list((111,)) * 3

    assert make_worker(file_queue=files).total_size == 3


def test_worker_built_without_a_file_list_is_just_empty():
    assert download_queue.DownloadWorkerThread(111).total_size == 0


# --- up-to-date games and enqueue sizes ---

@with_fake_workers
def test_enqueue_reports_how_much_the_game_will_download():
    scheduler = download_queue.DownloadScheduler()

    with patch("gogstash.download_queue.generate_download_list", lambda ids: canned_download_list(ids) * 3):
        assert scheduler.enqueue({"idx": 0, "product_id": 7}) == 3


@with_fake_workers
def test_enqueue_reports_nothing_for_a_row_that_is_already_waiting():
    scheduler = download_queue.DownloadScheduler()
    scheduler.enqueue({"idx": 0, "product_id": 7})

    assert scheduler.enqueue({"idx": 0, "product_id": 7}) == 0


@with_fake_workers
def test_game_with_nothing_left_to_download_succeeds_without_a_worker():
    # Regression: an up-to-date game got a worker anyway, which took one look
    # at its empty list and reported "No files to download" as a failure.
    scheduler = download_queue.DownloadScheduler()
    with patch("gogstash.download_queue.generate_download_list", lambda ids: []):
        scheduler.enqueue({"idx": 0, "product_id": 7})
    succeeded, finished_events = [], []
    scheduler.game_succeeded.connect(succeeded.append)
    scheduler.finished.connect(lambda: finished_events.append(True))

    scheduler.schedule()

    assert succeeded == [0]
    assert scheduler.active_queue == []
    assert scheduler.tokens == 1  # never took a slot, never has to give one back
    assert finished_events == [True]


# --- free space ---

def _disk_with(free):
    return patch("gogstash.download_queue.shutil.disk_usage", return_value=MagicMock(free=free))


def _low_space_events(scheduler):
    events = []
    scheduler.low_disk_space.connect(lambda required, free: events.append((required, free)))
    return events


@with_fake_workers
def test_schedule_holds_everything_back_when_the_queue_wont_fit():
    scheduler = make_scheduler(concurrency=2, count=2)
    events = _low_space_events(scheduler)

    with _disk_with(free=1):
        scheduler.schedule()

    assert events == [(2, 1)]  # two 1-byte games, one byte of disk
    assert scheduler.active_queue == []
    assert [j["row_idx"] for j in scheduler.idle_queue] == [0, 1]


@with_fake_workers
def test_schedule_keeps_a_little_headroom_instead_of_filling_the_disk_to_the_brim():
    scheduler = make_scheduler(concurrency=1, count=1)
    events = _low_space_events(scheduler)

    with _disk_with(free=1):  # 1 byte needed, 1 byte free, 0.98 bytes usable
        scheduler.schedule()

    assert events == [(1, 1)]  # the real free space is reported, not the haircut


@with_fake_workers
def test_schedule_starts_the_queue_when_it_fits():
    scheduler = make_scheduler(concurrency=2, count=2)
    events = _low_space_events(scheduler)

    with _disk_with(free=10**9):
        scheduler.schedule()

    assert events == []
    assert [j["row_idx"] for j in scheduler.active_queue] == [0, 1]


@with_fake_workers
def test_free_space_check_counts_what_active_downloads_still_need():
    scheduler = make_scheduler(concurrency=1, count=1)
    with _disk_with(free=10**9):
        scheduler.schedule()
    worker = scheduler.active_queue[0]["worker"]
    worker.total_size, worker.fetched_size = 100, 40
    events = _low_space_events(scheduler)

    with _disk_with(free=50), patch("gogstash.download_queue.generate_download_list", lambda ids: []):
        scheduler.enqueue({"idx": 1, "product_id": 1})

    assert events == [(60, 50)]


@with_fake_workers
def test_free_space_check_ignores_jobs_that_were_already_stopped():
    scheduler = make_scheduler(concurrency=1, count=3)
    scheduler.idle_queue[1]["stopped"] = True
    scheduler.idle_queue[2]["stopped"] = True

    with _disk_with(free=2):
        assert scheduler._free_check().required == 1


@with_fake_workers
def test_stop_all_on_a_full_disk_still_winds_everything_down():
    # Regression: the free-space check ran before stopped jobs were reported,
    # so on a full disk Stop failed the check and returned early, and the
    # window sat on "stopping" forever.
    scheduler = make_scheduler(concurrency=1, count=2)
    with _disk_with(free=10**9):
        scheduler.schedule()
    active_worker = scheduler.active_queue[0]["worker"]
    stopped_rows, stopped_events = [], []
    scheduler.game_stopped.connect(stopped_rows.append)
    scheduler.stopped.connect(lambda: stopped_events.append(True))
    events = _low_space_events(scheduler)

    with _disk_with(free=0):
        scheduler.stop_all()
        active_worker.stopped.emit()

    assert stopped_rows == [0, 1]
    assert stopped_events == [True]
    assert events == []


@with_fake_workers
def test_pause_on_a_full_disk_still_announces_paused():
    scheduler = make_scheduler(concurrency=1, count=2)
    with _disk_with(free=10**9):
        scheduler.schedule()
    job = scheduler.active_queue[0]
    paused_events = []
    scheduler.paused.connect(lambda: paused_events.append(True))

    with _disk_with(free=0):
        scheduler.pause_all()
        _pause_active_worker(job)

    assert paused_events == [True]


@with_fake_workers
def test_pause_all_with_nothing_running_announces_paused_right_away():
    # Regression: "paused" only ever came from the last active worker
    # checking in. No active workers, no check-ins, no "paused", and the
    # window kept waiting by the phone.
    scheduler = make_scheduler(concurrency=1, count=1)
    paused_events = []
    scheduler.paused.connect(lambda: paused_events.append(True))

    scheduler.pause_all()

    assert paused_events == [True]
    assert scheduler.active_queue == []
    assert [j["row_idx"] for j in scheduler.idle_queue] == [0]  # still waiting its turn


@with_fake_workers
def test_turning_the_free_space_check_off_lets_the_queue_run_anyway():
    # The "download anyway" escape hatch for when the user knows better.
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.free_space_check = False
    events = _low_space_events(scheduler)

    with _disk_with(free=0):
        scheduler.schedule()

    assert events == []
    assert [j["row_idx"] for j in scheduler.active_queue] == [0]


@with_fake_workers
def test_free_space_check_fails_safe_when_the_download_folder_cant_be_made(tmp_path):
    settings.update_setting("download_path", str(tmp_path / "locked"))  # settings file exists before mkdir is sabotaged
    scheduler = make_scheduler(concurrency=1, count=1)
    events = _low_space_events(scheduler)

    with patch("pathlib.Path.mkdir", side_effect=PermissionError("nope")):
        scheduler.schedule()

    assert events == [(1, 0)]
    assert scheduler.active_queue == []


def _up_to_date_scheduler(count):
    with patch("gogstash.download_queue.generate_download_list", lambda ids: []):
        return make_scheduler(concurrency=1, count=count)


@with_fake_workers
def test_a_queue_with_nothing_to_download_fits_on_even_the_fullest_disk():
    # Regression: 0 bytes needed, 0 bytes free, and 0 < 0 * 0.98 said no,
    # so the user got warned that nothing wouldn't fit.
    scheduler = _up_to_date_scheduler(count=2)
    events = _low_space_events(scheduler)
    succeeded = []
    scheduler.game_succeeded.connect(succeeded.append)

    with _disk_with(free=0):
        scheduler.schedule()

    assert events == []
    assert succeeded == [0, 1]


@with_fake_workers
def test_a_queue_with_nothing_to_download_doesnt_care_about_the_download_folder(tmp_path):
    settings.update_setting("download_path", str(tmp_path / "locked"))  # settings file exists before mkdir is sabotaged
    scheduler = _up_to_date_scheduler(count=1)
    events = _low_space_events(scheduler)

    with patch("pathlib.Path.mkdir", side_effect=PermissionError("nope")) as mock_mkdir:
        scheduler.schedule()

    assert events == []
    mock_mkdir.assert_not_called()  # nothing to save, nowhere needed


@with_fake_workers
def test_free_space_check_creates_a_download_folder_that_isnt_there_yet(tmp_path):
    # Regression: a fresh install's ~/Downloads/GogStash doesn't exist until
    # something downloads into it, and disk_usage() on a missing folder is a
    # FileNotFoundError, not a number.
    download_dir = tmp_path / "not" / "there" / "yet"
    settings.update_setting("download_path", str(download_dir))
    scheduler = make_scheduler(concurrency=1, count=1)

    scheduler.schedule()

    assert download_dir.is_dir()
    assert [j["row_idx"] for j in scheduler.active_queue] == [0]


# --- the disk fills up mid-run ---

def _part_file(tmp_path):
    part_path = tmp_path / "game" / "installer" / "setup.exe.part"
    part_path.parent.mkdir(parents=True)
    part_path.write_bytes(b"most of a game")
    return part_path


def _run_out_of_space(job, part_path):
    payload = {"partpath": part_path, "downlink": "https://example.com/f"}
    job["worker"].disk_full.emit(payload)
    return payload


@with_fake_workers
def test_a_full_disk_pauses_the_queue_and_keeps_the_game_resumable(tmp_path):
    # Regression: the full-disk game failed, and the scheduler cheerfully
    # sent the next game into the very same full disk to fail too. Then the
    # next. Dominoes, but sad.
    scheduler = make_scheduler(concurrency=1, count=2)
    scheduler.schedule()
    job = scheduler.active_queue[0]
    part_path = _part_file(tmp_path)
    paused_rows, paused_events, failed_rows = [], [], []
    scheduler.game_paused.connect(paused_rows.append)
    scheduler.paused.connect(lambda: paused_events.append(True))
    scheduler.game_failed.connect(lambda row, msg: failed_rows.append(row))

    payload = _run_out_of_space(job, part_path)

    assert paused_rows == [0]
    assert paused_events == [True]
    assert failed_rows == []
    assert [(j["row_idx"], j["resume_link"]) for j in scheduler.paused_queue] == [(0, payload)]
    assert [j["row_idx"] for j in scheduler.idle_queue] == [1]  # not thrown into the fire
    assert scheduler.active_queue == []
    assert scheduler.tokens == 1
    assert part_path.exists()
    assert "Download folder full: downloads paused" in [line.split(" : ", 1)[1] for line in _log_lines()]


@with_fake_workers
def test_a_full_disk_pauses_the_other_downloads_too(tmp_path):
    # One full disk is everyone's full disk. The neighbour gets asked to
    # pause, and "paused" waits until it actually has.
    scheduler = make_scheduler(concurrency=2, count=2)
    scheduler.schedule()
    full_job, other_job = scheduler.active_queue
    paused_events = []
    scheduler.paused.connect(lambda: paused_events.append(True))

    _run_out_of_space(full_job, _part_file(tmp_path))

    other_job["worker"].pause_worker.assert_called_once()
    assert paused_events == []
    _pause_active_worker(other_job)
    assert paused_events == [True]
    assert sorted(j["row_idx"] for j in scheduler.paused_queue) == [0, 1]


@with_fake_workers
def test_resuming_after_a_full_disk_picks_the_part_file_back_up(tmp_path):
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.schedule()
    payload = _run_out_of_space(scheduler.active_queue[0], _part_file(tmp_path))

    with _disk_with(free=10**9):  # someone finally emptied the recycle bin
        scheduler.resume_all()

    [resumed] = scheduler.active_queue
    assert resumed["worker"].resume_link == payload


@with_fake_workers
def test_a_stop_that_races_a_full_disk_still_stops_and_cleans_up(tmp_path):
    # Stop was clicked, but the worker hit the full disk before it noticed.
    # The user asked for a stop, so they get a stop, not a surprise pause
    # and a window stuck on "Stopping. Please wait...".
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.schedule()
    job = scheduler.active_queue[0]
    part_path = _part_file(tmp_path)
    stopped_rows, events = [], []
    scheduler.game_stopped.connect(stopped_rows.append)
    scheduler.stopped.connect(lambda: events.append("stopped"))
    scheduler.paused.connect(lambda: events.append("paused"))
    scheduler.stop_all()

    _run_out_of_space(job, part_path)

    assert stopped_rows == [0]
    assert events == ["stopped"]
    assert scheduler.paused_queue == []
    assert not (tmp_path / "game").exists()
    messages = [line.split(" : ", 1)[1] for line in _log_lines()]
    assert messages.count("Downloads stopped") == 1
    assert "Download folder ran out of space while stopping" in messages


def _disk_full_events(scheduler):
    events = []
    scheduler.disk_full.connect(lambda: events.append("disk_full"))
    scheduler.paused.connect(lambda: events.append("paused"))
    return events


@with_fake_workers
def test_a_full_disk_tells_the_window_why_before_announcing_paused(tmp_path):
    # The window needs the "why" in hand by the time "paused" lands, or it
    # just shrugs and says "Downloads paused" like the user asked for it.
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.schedule()
    events = _disk_full_events(scheduler)

    _run_out_of_space(scheduler.active_queue[0], _part_file(tmp_path))

    assert events == ["disk_full", "paused"]


@with_fake_workers
def test_two_downloads_hitting_a_full_disk_only_raise_the_alarm_once(tmp_path):
    # Both workers find out the hard way, a heartbeat apart. One dialog,
    # not a matching pair.
    scheduler = make_scheduler(concurrency=2, count=2)
    scheduler.schedule()
    first, second = scheduler.active_queue
    events = _disk_full_events(scheduler)

    _run_out_of_space(first, _part_file(tmp_path))
    second["worker"].disk_full.emit({"partpath": tmp_path / "other" / "x" / "y.part", "downlink": "y"})

    assert events == ["disk_full", "paused"]
    assert sorted(j["row_idx"] for j in scheduler.paused_queue) == [0, 1]


@with_fake_workers
def test_a_full_disk_during_a_pause_the_user_asked_for_stays_quiet(tmp_path):
    # They already clicked Pause. Popping up "the disk is full, pausing!"
    # on top of that is just yelling at someone who's already sitting down.
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.schedule()
    job = scheduler.active_queue[0]
    events = _disk_full_events(scheduler)
    scheduler.pause_all()

    _run_out_of_space(job, _part_file(tmp_path))

    assert events == ["paused"]
    assert [j["row_idx"] for j in scheduler.paused_queue] == [0]


@with_fake_workers
def test_a_full_disk_during_a_stop_stays_quiet(tmp_path):
    scheduler = make_scheduler(concurrency=1, count=1)
    scheduler.schedule()
    job = scheduler.active_queue[0]
    events = _disk_full_events(scheduler)
    scheduler.stop_all()

    _run_out_of_space(job, _part_file(tmp_path))

    assert "disk_full" not in events


# --- resuming counts what's left, not the whole game again ---

def _one_big_game(size=100):
    big_list = lambda ids: [dict(item, size=size) for item in canned_download_list(ids)]
    with patch("gogstash.download_queue.generate_download_list", big_list):
        return make_scheduler(concurrency=1, count=1)


@with_fake_workers
def test_resuming_a_paused_game_only_needs_room_for_what_is_left():
    # Regression: Resume re-counted the whole game from its enqueue-time file
    # list, finished files and .part bytes included. 60 of 100 bytes done,
    # 50 free, and the user got told they needed 100. They needed 40.
    scheduler = _one_big_game(size=100)
    with _disk_with(free=10**9):
        scheduler.schedule()
    job = scheduler.active_queue[0]
    job["worker"].fetched_size = 60
    scheduler.pause_all()
    _pause_active_worker(job)
    events = _low_space_events(scheduler)

    with _disk_with(free=50):
        scheduler.resume_all()

    assert events == []
    assert [j["row_idx"] for j in scheduler.active_queue] == [0]


@with_fake_workers
def test_resuming_after_a_full_disk_reports_what_is_really_needed(tmp_path):
    # Still not enough room, but at least the warning quotes the real bill.
    scheduler = _one_big_game(size=100)
    with _disk_with(free=10**9):
        scheduler.schedule()
    job = scheduler.active_queue[0]
    job["worker"].fetched_size = 60
    _run_out_of_space(job, _part_file(tmp_path))
    events = _low_space_events(scheduler)

    with _disk_with(free=30):
        scheduler.resume_all()

    assert events == [(40, 30)]
    assert scheduler.active_queue == []


@with_fake_workers
def test_a_game_paused_with_nothing_left_needs_no_room_at_all():
    # Pause landed in the split second after the last file finished. Zero
    # bytes to go, and zero is a number, not a "go ask the file list".
    scheduler = _one_big_game(size=100)
    with _disk_with(free=10**9):
        scheduler.schedule()
    job = scheduler.active_queue[0]
    job["worker"].fetched_size = 100
    scheduler.pause_all()
    _pause_active_worker(job)
    events = _low_space_events(scheduler)

    with _disk_with(free=10):
        scheduler.resume_all()

    assert events == []


@with_fake_workers
def test_a_game_that_came_in_smaller_than_listed_doesnt_eat_into_the_others():
    # GOG listed 100 bytes, the CDN sent 120 before the size got corrected.
    # A negative "remaining" would quietly hand the other games 20 bytes
    # that don't exist.
    scheduler = make_scheduler(concurrency=2, count=2)
    with _disk_with(free=10**9):
        scheduler.schedule()
    first, second = scheduler.active_queue
    first["worker"].total_size, first["worker"].fetched_size = 100, 120
    second["worker"].total_size, second["worker"].fetched_size = 50, 0

    with _disk_with(free=10**9):
        assert scheduler._free_check().required == 50


# --- the manifest can't be written because the disk is full ---

def _manifest_write_fails(error_errno=errno.ENOSPC):
    def dump(data, fp):
        raise OSError(error_errno, os.strerror(error_errno))
    return patch("gogstash.manifest.json.dump", dump)


def _pause_and_resume(scheduler):
    job = scheduler.active_queue[0]
    scheduler.pause_all()
    _pause_active_worker(job)
    with _disk_with(free=10**9):
        scheduler.resume_all()


@with_fake_workers
def test_a_file_the_full_disk_wont_let_us_record_gets_recorded_on_resume(tmp_path):
    # Regression: the manifest write blew up on a full disk, the finished
    # file never got its entry, and Resume cheerfully downloaded all 10 GB of
    # it again. Into the disk that was full. You can see the problem.
    scheduler, worker, game_dir = _scheduler_with_game_files(tmp_path, "a.exe")

    with _manifest_write_fails():
        worker.fetched.emit(_fetched_entry(game_dir, "a.exe", size=1))

    assert manifest.stat_file(game_dir, game_dir / "a.exe") == {}
    assert any(f"{game_dir / 'a.exe'} : Fetched" in line for line in _log_lines())  # logged on arrival anyway

    _pause_and_resume(scheduler)

    assert manifest.stat_file(game_dir, game_dir / "a.exe")["checksum"] == "abc"
    assert (game_dir / "a.exe").exists()


@with_fake_workers
def test_a_waiting_record_gets_another_go_with_the_next_file(tmp_path):
    scheduler, worker, game_dir = _scheduler_with_game_files(tmp_path, "a.exe", "b.exe")
    with _manifest_write_fails():
        worker.fetched.emit(_fetched_entry(game_dir, "a.exe", size=1))

    worker.fetched.emit(_fetched_entry(game_dir, "b.exe", size=1))  # someone freed some space

    assert manifest.stat_file(game_dir, game_dir / "a.exe") != {}
    assert manifest.stat_file(game_dir, game_dir / "b.exe") != {}
    assert sum(f"{game_dir / 'a.exe'} : Fetched" in line for line in _log_lines()) == 1  # one line, not two


@with_fake_workers
def test_a_record_that_still_wont_fit_keeps_waiting_and_says_so(tmp_path):
    scheduler, worker, game_dir = _scheduler_with_game_files(tmp_path, "a.exe", "b.exe")

    with _manifest_write_fails():
        worker.fetched.emit(_fetched_entry(game_dir, "a.exe", size=1))
        worker.fetched.emit(_fetched_entry(game_dir, "b.exe", size=1))

    assert any("1 downloaded file still waiting to be recorded" in line for line in _log_lines())

    _pause_and_resume(scheduler)  # finally some room

    assert manifest.stat_file(game_dir, game_dir / "a.exe") != {}
    assert manifest.stat_file(game_dir, game_dir / "b.exe") != {}


@with_fake_workers
def test_a_waiting_record_for_a_file_that_vanished_is_dropped_and_resume_still_works(tmp_path):
    # The user "freed space" by deleting the very file we were waiting to
    # record. Fair enough. Let it go, say so once, and don't brick Resume.
    scheduler, worker, game_dir = _scheduler_with_game_files(tmp_path, "a.exe")
    with _manifest_write_fails():
        worker.fetched.emit(_fetched_entry(game_dir, "a.exe", size=1))
    (game_dir / "a.exe").unlink()

    _pause_and_resume(scheduler)

    assert [j["row_idx"] for j in scheduler.active_queue] == [0]
    errors = [line for line in _log_lines() if "Error recording file" in line]
    assert len(errors) == 1
    worker = scheduler.active_queue[0]["worker"]
    (game_dir / "b.exe").write_bytes(b"x")
    worker.fetched.emit(_fetched_entry(game_dir, "b.exe", size=1))
    assert len([line for line in _log_lines() if "Error recording file" in line]) == 1  # not retried forever


@with_fake_workers
def test_other_manifest_errors_are_logged_and_never_cost_the_user_the_file(tmp_path):
    # A manifest we can't write is our problem, not a reason to bin a
    # perfectly good, freshly verified download.
    scheduler, worker, game_dir = _scheduler_with_game_files(tmp_path, "a.exe", "b.exe")

    with _manifest_write_fails(errno.EACCES):
        worker.fetched.emit(_fetched_entry(game_dir, "a.exe", size=1))

    assert (game_dir / "a.exe").exists()
    assert sum("Error recording file" in line for line in _log_lines()) == 1
    worker.fetched.emit(_fetched_entry(game_dir, "b.exe", size=1))
    assert manifest.stat_file(game_dir, game_dir / "a.exe") == {}  # given up on, not waiting
    assert sum("Error recording file" in line for line in _log_lines()) == 1
