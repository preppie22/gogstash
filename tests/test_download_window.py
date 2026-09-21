from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap

from gogstash import library_db, manifest
from gogstash.download_window import DownloadWindow, UserRole
from gogstash.settings import update_setting

FAKE_PRODUCT = {
    "id": 42,
    "title": "Some Game",
    "slug": "some-game",
    "isMovie": False,
    "url": "/en/game/some_game",
    "image": "//images.example.com/some_game",
    "worksOn": {"Windows": True, "Linux": False, "Mac": True},
}


@pytest.fixture(autouse=True)
def db():
    library_db._create_db(force=True)
    library_db.update_products([FAKE_PRODUCT])


def _non_null_icon():
    # A plain QIcon() is null, and _color_scheme_refresh's "skip icon-less
    # entries" guard would then treat every recolored button as icon-less too.
    return QIcon(QPixmap(4, 4))


def _row(title="Some Game", size="2 GB", product_id=42):
    return {"title": title, "size": size, "product_id": product_id}


@patch("gogstash.download_window.estimate_download_size")
def test_add_to_queue_inserts_row_with_title_and_size(mock_estimate):
    mock_estimate.return_value = 2_000_000_000  # 2.0 GB
    window = DownloadWindow()

    window.add_to_queue(_row(title="Some Game"))

    assert window.game_queue_table.rowCount() == 1
    assert window.game_queue_table.item(0, 0).text() == "Some Game"
    assert window.game_queue_table.item(0, 1).text() == "0 / 2.0 GB"


def test_add_to_queue_stores_the_product_id_on_the_title_item():
    window = DownloadWindow()

    window.add_to_queue(_row(product_id=99))

    item = window.game_queue_table.item(0, 0)
    assert item.data(UserRole.PRODUCT_ID_ROLE.value) == 99


def test_add_to_queue_sets_initial_progress_to_zero():
    window = DownloadWindow()

    window.add_to_queue(_row())

    assert window.game_queue_table.item(0, 0).data(UserRole.PROGRESS_ROLE.value) == 0


def test_add_to_queue_selects_the_new_row():
    window = DownloadWindow()
    window.add_to_queue(_row(title="First Game"))

    window.add_to_queue(_row(title="Second Game"))

    assert window.game_queue_table.currentRow() == 1


def test_add_to_queue_returns_incrementing_row_index():
    window = DownloadWindow()

    first_idx = window.add_to_queue(_row(title="First Game"))
    second_idx = window.add_to_queue(_row(title="Second Game"))

    assert first_idx == 0
    assert second_idx == 1


def test_set_progress_updates_progress_role_data():
    window = DownloadWindow()
    window.add_to_queue(_row())

    window.set_progress(0, 42)

    assert window.game_queue_table.item(0, 0).data(UserRole.PROGRESS_ROLE.value) == 42


@patch("gogstash.download_window.get_icon")
def test_color_scheme_refresh_reloads_each_button_from_its_own_icon_file(mock_get_icon):
    mock_get_icon.return_value = _non_null_icon()
    window = DownloadWindow()
    mock_get_icon.reset_mock()

    window._color_scheme_refresh()

    called_files = {call.args[0] for call in mock_get_icon.call_args_list}
    assert called_files == {"trash.svg", "start_download.svg", "stop.svg"}


@patch("gogstash.download_window.get_icon")
def test_color_scheme_refresh_sets_the_reloaded_icon_on_each_button(mock_get_icon):
    mock_get_icon.return_value = _non_null_icon()
    window = DownloadWindow()
    mock_get_icon.reset_mock()
    mock_get_icon.return_value = _non_null_icon()  # a fresh, distinct icon to detect the swap

    window._color_scheme_refresh()

    for button in window.dialog_buttons.buttons():
        assert button.icon().cacheKey() == mock_get_icon.return_value.cacheKey()


@patch("gogstash.download_window.DownloadScheduler")
@patch("gogstash.download_window.estimate_download_size")
def test_start_downloads_builds_scheduler_from_queued_rows(mock_estimate, mock_scheduler_cls):
    # Regression: token-fetching moved out to DownloadWorkerThread, so this
    # window shouldn't be lugging a token around anymore. Just the queue
    # and a concurrency number, nothing fancier.
    mock_estimate.return_value = 0
    update_setting("download_concurrency", 3)
    window = DownloadWindow()
    window.add_to_queue(_row(title="First Game", product_id=1))
    window.add_to_queue(_row(title="Second Game", product_id=2))

    window.start_downloads()

    mock_scheduler_cls.assert_called_once_with(
        [{"idx": 0, "product_id": 1}, {"idx": 1, "product_id": 2}], 3
    )


@patch("gogstash.download_window.DownloadScheduler")
@patch("gogstash.download_window.estimate_download_size")
def test_start_downloads_does_not_require_a_stored_token(mock_estimate, mock_scheduler_cls):
    # Regression: this used to puke ValueError("Invalid
    # access token") the moment nothing was on disk. Not this window's
    # problem anymore, the worker threads sort out their own tokens now.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row())

    window.start_downloads()  # if this blows up, we've regressed

    mock_scheduler_cls.assert_called_once()


def test_stop_downloads_does_not_crash_without_a_scheduler():
    # Regression: stop_downloads() used to call self.scheduler.stop_all() no
    # questions asked, a great way to raise AttributeError if Stop gets
    # clicked before Start ever ran, or after a previous stop already
    # jacked the scheduler back to None.
    window = DownloadWindow()

    window.stop_downloads()  # must not raise


@patch("gogstash.download_window.DownloadScheduler")
@patch("gogstash.download_window.estimate_download_size")
def test_on_stopped_reenables_start_button_and_clears_scheduler(mock_estimate, mock_scheduler_cls):
    # Regression: _on_stopped() forgot to re-enable start_pause_button, so
    # one stopped download later, Start stayed disabled.
    # "Have you tried turning it off and on again" is not a UX strategy.
    mock_estimate.return_value = 0
    window = DownloadWindow()
    window.add_to_queue(_row())
    window.start_downloads()
    assert window.start_button.isEnabled() is False

    window._on_stopped()

    assert window.start_button.isEnabled() is True
    assert window.scheduler is None


@patch("gogstash.download_window.estimate_download_size")
def test_on_game_stopped_logs_each_entry_the_same_way_on_game_failed_does(mock_estimate):
    # A stopped job's fetched_list can be a grab bag: files that finished
    # right before the stop landed, sitting next to per-file failures from
    # earlier in the same batch. _on_game_stopped should write each one
    # through the same write_log() path _on_game_failed uses, not some
    # bespoke tuple-unpacking format of its own.
    mock_estimate.return_value = 2_000_000_000
    window = DownloadWindow()
    window.add_to_queue(_row())

    window._on_game_stopped(0, [
        {"filepath": Path("good.exe"), "size": 500, "checksum": "abc123", "fetched_at": 1.0},
        {
            "filepath": Path("bad.exe"), "size": -1, "checksum": "", "fetched_at": 2.0,
            "error": "Checksum mismatch | Expected size: 1000 | Got size: 400",
        },
    ])

    log_contents = window.log_file.read_text()
    assert "good.exe: Fetched 500 Bytes | md5: abc123" in log_contents
    assert "bad.exe: Checksum mismatch | Expected size: 1000 | Got size: 400" in log_contents


@patch("gogstash.download_window.estimate_download_size")
def test_on_game_stopped_resets_row_progress_and_size_text(mock_estimate):
    mock_estimate.return_value = 2_000_000_000  # 2.0 GB
    window = DownloadWindow()
    window.add_to_queue(_row())
    window.set_progress(0, 55)

    window._on_game_stopped(0, [])

    assert window.game_queue_table.item(0, 0).data(UserRole.PROGRESS_ROLE.value) == 0
    assert window.game_queue_table.item(0, 1).text() == "0 / 2.0 GB"


def test_write_log_formats_a_successful_entry():
    window = DownloadWindow()

    window.write_log({
        "filepath": Path("setup.exe"), "size": 500, "checksum": "abc123", "fetched_at": 1.0
    })

    assert "setup.exe: Fetched 500 Bytes | md5: abc123" in window.log_file.read_text()


def test_write_log_formats_an_error_entry():
    window = DownloadWindow()

    window.write_log({
        "filepath": Path("setup.exe"), "size": -1, "checksum": "", "fetched_at": 1.0,
        "error": "connection reset",
    })

    log_contents = window.log_file.read_text()
    assert "setup.exe: connection reset" in log_contents
    assert "Fetched" not in log_contents


def test_write_log_does_nothing_for_an_empty_entry():
    # _on_game_stopped can hand write_log a job that never dispatched at all.
    window = DownloadWindow()

    window.write_log({})

    assert not window.log_file.exists()


@patch("gogstash.download_window.estimate_download_size")
def test_on_game_succeeded_records_completed_files_in_the_manifest(mock_estimate, tmp_path):
    mock_estimate.return_value = 0
    update_setting("download_path", str(tmp_path))
    game_dir = tmp_path / "some-game"
    game_dir.mkdir(parents=True)
    (game_dir / "setup.exe").write_bytes(b"hello")
    window = DownloadWindow()
    window.add_to_queue(_row())

    window._on_game_succeeded(0, [
        {"filepath": game_dir / "setup.exe", "category": "installers", "size": 5, "checksum": "abc123", "fetched_at": 1.0},
    ])

    assert manifest.stat_file(game_dir, game_dir / "setup.exe") == {
        "category": "installers", "size": 5, "checksum": "abc123", "fetched_at": 1.0
    }


@patch("gogstash.download_window.estimate_download_size")
def test_on_game_succeeded_skips_the_manifest_for_failed_entries_in_the_same_batch(mock_estimate, tmp_path):
    # Regression: a partially-successful batch can contain failed entries
    # (size -1, no real file behind them) right next to the real ones.
    # Calling manifest.add_file on those blindly used to raise
    # FileNotFoundError and abort the rest of the batch's manifest writes.
    mock_estimate.return_value = 0
    update_setting("download_path", str(tmp_path))
    game_dir = tmp_path / "some-game"
    game_dir.mkdir(parents=True)
    (game_dir / "good.exe").write_bytes(b"hello")
    window = DownloadWindow()
    window.add_to_queue(_row())

    window._on_game_succeeded(0, [
        {
            "filepath": Path("bad_file_id"), "size": -1, "checksum": "", "fetched_at": 1.0,
            "error": "boom",
        },
        {"filepath": game_dir / "good.exe", "category": "installers", "size": 5, "checksum": "abc123", "fetched_at": 2.0},
    ])

    assert manifest.stat_file(game_dir, game_dir / "good.exe") == {
        "category": "installers", "size": 5, "checksum": "abc123", "fetched_at": 2.0
    }
