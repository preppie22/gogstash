from unittest.mock import MagicMock, patch

import pytest

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
                # "os" intentionally omitted -- GOG's real bonus_content entries
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
    # Regression: bonus_content entries have no "os" key (None, not ""), and
    # the platform filter must not treat that as "wrong platform".
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


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_succeeds_and_writes_file(mock_resolve, mock_get, tmp_path):
    library_db.update_products([FAKE_PRODUCT])
    settings.update_setting("download_path", str(tmp_path))
    settings.update_setting("patches", False)  # isolate to the single installer file
    mock_resolve.return_value = {
        "downlink": "https://cdn.example.com/setup_fake_game.exe",
        "checksum": "https://cdn.example.com/setup_fake_game.exe.xml",
    }
    mock_get.return_value = make_streamed_response([b"abcd", b"efgh"])

    thread = download_queue.DownloadWorkerThread("token", 111)
    succeeded = []
    failed = []
    thread.succeeded.connect(lambda result: succeeded.append(result))
    thread.failed.connect(lambda msg: failed.append(msg))

    thread.run()

    mock_resolve.assert_called_once_with("token", "https://example.com/file1")
    assert failed == []
    assert succeeded == [[("setup_fake_game.exe", 8)]]
    written = tmp_path / "fake-game" / "installer_windows_en" / "setup_fake_game.exe"
    assert written.read_bytes() == b"abcdefgh"


@patch("gogstash.download_queue.requests.get")
@patch("gogstash.gog_api.resolve_downlink")
def test_download_worker_failure_does_not_also_emit_succeeded(mock_resolve, mock_get, tmp_path):
    library_db.update_products([FAKE_PRODUCT])
    settings.update_setting("download_path", str(tmp_path))
    mock_resolve.return_value = {
        "downlink": "https://cdn.example.com/setup_fake_game.exe",
        "checksum": "https://cdn.example.com/setup_fake_game.exe.xml",
    }
    broken_response = MagicMock()
    broken_response.iter_content.side_effect = RuntimeError("connection reset")
    mock_get.return_value = broken_response

    thread = download_queue.DownloadWorkerThread("token", 111)
    succeeded = []
    failed = []
    thread.succeeded.connect(lambda result: succeeded.append(result))
    thread.failed.connect(lambda msg: failed.append(msg))

    thread.run()

    assert failed == ["connection reset"]
    assert succeeded == []  # regression: succeeded must not also fire after failed
