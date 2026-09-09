import hashlib
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QObject, Signal

from gogstash import download_queue, library_db, settings

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


def make_streamed_response(chunks):
    response = MagicMock()
    response.iter_content.return_value = chunks
    return response


def make_checksum_response(md5: str):
    response = MagicMock()
    response.text = f'<file md5="{md5}"/>'
    return response


@patch("gogstash.download_queue.get_valid_token")
@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_succeeds_and_writes_file(mock_resolve, mock_get, mock_get_valid_token, tmp_path):
    library_db.update_products([FAKE_PRODUCT])
    settings.update_setting("download_path", str(tmp_path))
    settings.update_setting("patches", False)  # isolate to the single installer file
    mock_get_valid_token.return_value = {"access_token": "token"}
    mock_resolve.return_value = {
        "downlink": "https://cdn.example.com/setup_fake_game.exe",
        "checksum": "https://cdn.example.com/setup_fake_game.exe.xml",
    }
    # file1's declared size in FAKE_DOWNLOADABLE is 1000 bytes, the streamed
    # content must add up to exactly that or the new size-verification check
    # (part_path size vs file['size']) will treat this as a failed download.
    chunk_a = b"a" * 400
    chunk_b = b"b" * 600
    checksum = hashlib.md5(chunk_a + chunk_b).hexdigest()
    mock_get.side_effect = [
        make_streamed_response([chunk_a, chunk_b]),  # the real download
        make_checksum_response(checksum),  # the .xml sidekick that verifies it
    ]

    thread = download_queue.DownloadWorkerThread(111)
    succeeded = []
    failed = []
    thread.succeeded.connect(lambda result: succeeded.append(result))
    thread.failed.connect(lambda msg, fetched: failed.append(msg))

    thread.run()

    mock_resolve.assert_called_once_with("token", "https://example.com/file1")
    assert failed == []
    assert succeeded == [[("setup_fake_game.exe", 1000)]]
    written = tmp_path / "fake-game" / "installer_windows_en" / "setup_fake_game.exe"
    assert written.read_bytes() == chunk_a + chunk_b


@patch("gogstash.download_queue.get_valid_token")
@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_failure_does_not_also_emit_succeeded(mock_resolve, mock_get, mock_get_valid_token, tmp_path):
    library_db.update_products([FAKE_PRODUCT])
    settings.update_setting("download_path", str(tmp_path))
    settings.update_setting("patches", False)  # isolate to the single installer file
    mock_get_valid_token.return_value = {"access_token": "token"}
    mock_resolve.return_value = {
        "downlink": "https://cdn.example.com/setup_fake_game.exe",
        "checksum": "https://cdn.example.com/setup_fake_game.exe.xml",
    }
    # The checksum fetch succeeds fine, the actual download is the one that
    # faceplants once we start reading it. Needs a real dict for .headers
    # though, since a bare MagicMock().headers.get(...) is truthy and would
    # trip up int(cl) before we ever get to the good stuff.
    broken_response = MagicMock()
    broken_response.headers = {}
    broken_response.iter_content.side_effect = RuntimeError("connection reset")
    mock_get.side_effect = [broken_response, make_checksum_response("irrelevant")]

    thread = download_queue.DownloadWorkerThread(111)
    succeeded = []
    failed = []
    thread.succeeded.connect(lambda result: succeeded.append(result))
    thread.failed.connect(lambda msg, fetched: failed.append(msg))

    thread.run()

    assert failed == ["connection reset"]
    assert succeeded == []  # regression: succeeded must not also fire after failed


@patch("gogstash.download_queue.get_valid_token")
def test_download_worker_fails_immediately_when_no_valid_token(mock_get_valid_token, tmp_path):
    # Regression: no token, no refresh_token, no soup for you. get_valid_token()
    # returning None used to send us straight into `None['access_token']`
    # like nothing happened. Should just report the auth failure and bail.
    library_db.update_products([FAKE_PRODUCT])
    settings.update_setting("download_path", str(tmp_path))
    settings.update_setting("patches", False)
    mock_get_valid_token.return_value = None

    thread = download_queue.DownloadWorkerThread(111)
    succeeded = []
    failed = []
    thread.succeeded.connect(lambda result: succeeded.append(result))
    thread.failed.connect(lambda msg, fetched: failed.append(msg))

    thread.run()

    assert failed == ["Authentication failed. Login again."]
    assert succeeded == []


@patch("gogstash.download_queue.get_valid_token")
@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_requests_a_fresh_token_per_file(mock_resolve, mock_get, mock_get_valid_token, tmp_path):
    # Regression: we used to grab one token at thread creation and ride it
    # for the entire download, expiry be damned. Now every file gets its own
    # fresh get_valid_token() call. The actual download is set up to eat dirt
    # immediately, we only care how many times we went back for a token.
    library_db.update_products([FAKE_PRODUCT])
    settings.update_setting("download_path", str(tmp_path))
    settings.update_setting("patches", False)
    settings.update_setting("bonus_content", True)  # installer + bonus, two files, easy math
    mock_get_valid_token.return_value = {"access_token": "token"}
    mock_resolve.return_value = {
        "downlink": "https://cdn.example.com/file.bin",
        "checksum": "https://cdn.example.com/file.bin.xml",
    }
    mock_get.side_effect = RuntimeError("network boom")

    thread = download_queue.DownloadWorkerThread(111)
    thread.run()

    assert mock_get_valid_token.call_count == 2


@patch("gogstash.download_queue.get_valid_token")
@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_stop_mid_chunk_deletes_part_file_and_emits_stopped(
    mock_resolve, mock_get, mock_get_valid_token, tmp_path
):
    library_db.update_products([FAKE_PRODUCT])
    settings.update_setting("download_path", str(tmp_path))
    settings.update_setting("patches", False)
    mock_get_valid_token.return_value = {"access_token": "token"}
    mock_resolve.return_value = {
        "downlink": "https://cdn.example.com/setup_fake_game.exe",
        "checksum": "https://cdn.example.com/setup_fake_game.exe.xml",
    }
    mock_get.side_effect = [
        make_streamed_response([b"a" * 400, b"b" * 600]),
        make_checksum_response("irrelevant"),
    ]

    thread = download_queue.DownloadWorkerThread(111)
    # Rage-click Stop right after chunk one lands. Fuck chunk two.
    thread.update_progress = lambda: thread.stop_worker()
    succeeded, failed, stopped = [], [], []
    thread.succeeded.connect(lambda result: succeeded.append(result))
    thread.failed.connect(lambda msg, fetched: failed.append(msg))
    thread.stopped.connect(lambda fetched: stopped.append(fetched))

    thread.run()

    assert succeeded == []
    assert failed == []
    assert stopped == [[]]
    game_dir = tmp_path / "fake-game" / "installer_windows_en"
    assert not (game_dir / "setup_fake_game.exe.part").exists()
    assert not (game_dir / "setup_fake_game.exe").exists()


@patch("gogstash.download_queue.get_valid_token")
@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_stop_after_full_download_still_saves_the_file(
    mock_resolve, mock_get, mock_get_valid_token, tmp_path
):
    # Stop can land in the sliver of time between the last chunk arriving and
    # the loop noticing the stream ran dry. The file's already fully on disk
    # and checksums clean by then, so binning it would be throwing away
    # used bandwidth
    library_db.update_products([FAKE_PRODUCT])
    settings.update_setting("download_path", str(tmp_path))
    settings.update_setting("patches", False)
    mock_get_valid_token.return_value = {"access_token": "token"}
    mock_resolve.return_value = {
        "downlink": "https://cdn.example.com/setup_fake_game.exe",
        "checksum": "https://cdn.example.com/setup_fake_game.exe.xml",
    }
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
    mock_get.side_effect = [response, make_checksum_response(checksum)]

    succeeded, failed, stopped = [], [], []
    thread.succeeded.connect(lambda result: succeeded.append(result))
    thread.failed.connect(lambda msg, fetched: failed.append(msg))
    thread.stopped.connect(lambda fetched: stopped.append(fetched))

    thread.run()

    assert succeeded == []
    assert failed == []
    assert stopped == [[("setup_fake_game.exe", 1000)]]
    written = tmp_path / "fake-game" / "installer_windows_en" / "setup_fake_game.exe"
    assert written.read_bytes() == chunk_a + chunk_b


@patch("gogstash.download_queue.get_valid_token")
@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_unrelated_failure_with_stop_already_requested_does_not_also_emit_stopped(
    mock_resolve, mock_get, mock_get_valid_token, tmp_path
):
    # Regression: `stopped` used to fire from one blanket check put
    # after the whole file loop, regardless of why the loop
    # actually ended. An unrelated failure (here: the destination folder
    # won't create) landing at the same moment as a stop request used to
    # make the worker kill itself twice, once via `failed` and
    # once via `stopped`, and the scheduler tried to bury the same job out
    # of active_queue twice.
    library_db.update_products([FAKE_PRODUCT])
    settings.update_setting("download_path", str(tmp_path))
    settings.update_setting("patches", False)
    mock_get_valid_token.return_value = {"access_token": "token"}
    mock_resolve.return_value = {
        "downlink": "https://cdn.example.com/setup_fake_game.exe",
        "checksum": "https://cdn.example.com/setup_fake_game.exe.xml",
    }
    mock_get.side_effect = [
        make_streamed_response([b"a"]),
        make_checksum_response("irrelevant"),
    ]

    thread = download_queue.DownloadWorkerThread(111)
    thread.stop_worker()  # stop was already requested before this file even starts
    succeeded, failed, stopped = [], [], []
    thread.succeeded.connect(lambda result: succeeded.append(result))
    thread.failed.connect(lambda msg, fetched: failed.append(msg))
    thread.stopped.connect(lambda fetched: stopped.append(fetched))

    with patch("pathlib.Path.mkdir", side_effect=OSError("disk full")):
        thread.run()

    assert failed == ["disk full"]
    assert stopped == []
    assert succeeded == []


class FakeWorker(QObject):
    """A lazy double for DownloadWorkerThread that never does any actual work.
    Tests drive it by emitting its signals directly, so DownloadScheduler's
    orchestration (dispatch/reap/stop bookkeeping) gets exercised for real,
    minus the real threads, real network calls, and the wait for a QThread
    that will never show up."""

    succeeded = Signal(list)
    failed = Signal(str, list)
    progress = Signal(float, float)
    stopped = Signal(list)

    def __init__(self, product_id):
        super().__init__()
        self.product_id = product_id
        self.stop_worker = MagicMock()

    def start(self):
        pass


def make_scheduler(concurrency, count):
    product_queue = [{"idx": i, "product_id": i} for i in range(count)]
    return download_queue.DownloadScheduler(product_queue, concurrency)


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
    scheduler.game_stopped.connect(lambda row_idx, fetched: stopped_rows.append((row_idx, fetched)))

    scheduler.stop_all()
    active_worker.stopped.emit([])  # the active worker cooperates and taps out

    # Row 0 was mid-download and reports its own (empty) fetched_list. Row 1
    # never dispatched, but it gets the same "stopped" send-off
    # once the scheduler drains the rest of the queue.
    assert stopped_rows == [(0, []), (1, [])]


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
    active_worker.stopped.emit([])

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

    active_worker.succeeded.emit([("file.exe", 100)])

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
