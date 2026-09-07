from unittest.mock import MagicMock, patch

from gogstash import gog_api, library_db


def make_response(json_data):
    response = MagicMock()
    response.json.return_value = json_data
    return response


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
    },
}


@patch("gogstash.gog_api.requests.get")
def test_get_library_single_page(mock_get):
    mock_get.return_value = make_response(
        {"totalProducts": 2, "totalPages": 1, "products": [{"id": 1}, {"id": 2}]}
    )

    result = gog_api.fetch_library("mytoken")

    assert mock_get.call_count == 1
    args, kwargs = mock_get.call_args
    assert args[0] == gog_api.LIBRARY_URL
    assert kwargs["headers"] == {"Authorization": "Bearer mytoken"}
    assert kwargs["params"] == {"page": 1}
    assert result == [{"id": 1}, {"id": 2}]


@patch("gogstash.gog_api.requests.get")
def test_get_library_fetches_every_page_and_flattens_results(mock_get):
    mock_get.side_effect = [
        make_response({"totalPages": 3, "products": [{"id": 1}]}),
        make_response({"totalPages": 3, "products": [{"id": 2}]}),
        make_response({"totalPages": 3, "products": [{"id": 3}]}),
    ]

    result = gog_api.fetch_library("mytoken")

    assert mock_get.call_count == 3
    sent_pages = [call.kwargs["params"]["page"] for call in mock_get.call_args_list]
    assert sent_pages == [1, 2, 3]
    assert result == [{"id": 1}, {"id": 2}, {"id": 3}]


@patch("gogstash.gog_api.requests.get")
def test_get_downloadable_single_batch_under_50(mock_get):
    mock_get.return_value = make_response([{"id": 1}, {"id": 2}, {"id": 3}])

    result = gog_api.fetch_downloadables("token", [1, 2, 3])

    assert mock_get.call_count == 1
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["ids"] == "1,2,3"
    assert kwargs["params"]["expand"] == "downloads"
    assert kwargs["headers"] == {"Authorization": "Bearer token"}
    assert result == [{"id": 1}, {"id": 2}, {"id": 3}]


@patch("gogstash.gog_api.requests.get")
def test_get_downloadable_splits_into_chunks_of_50(mock_get):
    ids = list(range(1, 121))  # 120 ids -> chunks of 50, 50, 20
    mock_get.side_effect = [
        make_response([{"id": "from-batch-1"}]),
        make_response([{"id": "from-batch-2"}]),
        make_response([{"id": "from-batch-3"}]),
    ]

    result = gog_api.fetch_downloadables("token", ids)

    assert mock_get.call_count == 3
    sent_ids = [call.kwargs["params"]["ids"] for call in mock_get.call_args_list]
    assert sent_ids[0] == ",".join(str(i) for i in range(1, 51))
    assert sent_ids[1] == ",".join(str(i) for i in range(51, 101))
    assert sent_ids[2] == ",".join(str(i) for i in range(101, 121))
    assert result == [
        {"id": "from-batch-1"},
        {"id": "from-batch-2"},
        {"id": "from-batch-3"},
    ]


def test_get_downloadable_empty_input_makes_no_requests():
    with patch("gogstash.gog_api.requests.get") as mock_get:
        result = gog_api.fetch_downloadables("token", [])
        mock_get.assert_not_called()
        assert result == []


@patch("gogstash.gog_api.fetch_downloadables")
@patch("gogstash.gog_api.fetch_library")
def test_library_fetch_thread_bootstraps_when_db_empty(mock_fetch_library, mock_fetch_downloadables):
    mock_fetch_library.return_value = [FAKE_PRODUCT]
    mock_fetch_downloadables.return_value = [FAKE_DOWNLOADABLE]
    thread = gog_api.LibraryFetchThread("token")
    received = []
    thread.succeeded.connect(lambda result: received.append(result))
    thread.failed.connect(lambda msg: pytest_fail_helper(msg))

    thread.run()

    mock_fetch_library.assert_called_once_with("token")
    mock_fetch_downloadables.assert_called_once_with("token", [111], thread.update_progress)
    assert len(received) == 1
    assert received[0] == [
        {"product_id": 111, "title": "Fake Game", "download_size": 2000, "fetched_size": 0, "fetched": 0}
    ]


@patch("gogstash.gog_api.fetch_downloadables")
@patch("gogstash.gog_api.fetch_library")
def test_library_fetch_thread_reads_cache_without_hitting_network(mock_fetch_library, mock_fetch_downloadables):
    library_db.update_products([FAKE_PRODUCT])
    thread = gog_api.LibraryFetchThread("token")
    received = []
    thread.succeeded.connect(lambda result: received.append(result))
    thread.failed.connect(lambda msg: pytest_fail_helper(msg))

    thread.run()

    mock_fetch_library.assert_not_called()
    mock_fetch_downloadables.assert_not_called()
    assert received[0][0]["product_id"] == 111


@patch("gogstash.gog_api.fetch_library")
def test_library_fetch_thread_emits_failed_on_exception(mock_fetch_library):
    mock_fetch_library.side_effect = RuntimeError("network exploded")
    thread = gog_api.LibraryFetchThread("token")
    errors = []
    succeeded = []
    thread.failed.connect(lambda msg: errors.append(msg))
    thread.succeeded.connect(lambda result: succeeded.append(result))

    thread.run()

    assert errors == ["network exploded"]
    assert succeeded == []


def test_downloadables_fetch_thread_succeeds_when_data_cached():
    library_db.update_products([FAKE_PRODUCT])
    library_db.update_downloadables([FAKE_DOWNLOADABLE])
    thread = gog_api.DownloadablesFetchThread("token")
    received = []
    errors = []
    thread.succeeded.connect(lambda result: received.append(result))
    thread.failed.connect(lambda msg: errors.append(msg))

    thread.run()

    assert errors == []
    assert len(received) == 1
    assert received[0][0]["file_id"] == "file1"


def test_downloadables_fetch_thread_fails_when_db_empty():
    thread = gog_api.DownloadablesFetchThread("token")
    received = []
    errors = []
    thread.succeeded.connect(lambda result: received.append(result))
    thread.failed.connect(lambda msg: errors.append(msg))

    thread.run()

    assert errors == ["Product does not exist"]
    assert received == []  # regression: succeeded must not also fire after failed


def test_downloadables_fetch_thread_fails_when_specific_id_not_cached():
    library_db.update_products([FAKE_PRODUCT])
    library_db.update_downloadables([FAKE_DOWNLOADABLE])
    thread = gog_api.DownloadablesFetchThread("token")
    received = []
    errors = []
    thread.succeeded.connect(lambda result: received.append(result))
    thread.failed.connect(lambda msg: errors.append(msg))

    thread.run(product_id=(999,))

    assert errors == ["Product does not exist"]
    assert received == []


def pytest_fail_helper(msg):
    raise AssertionError(f"failed signal should not have fired: {msg}")
