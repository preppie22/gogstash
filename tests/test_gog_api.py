from unittest.mock import MagicMock, patch

from gogstash import gog_api


def make_response(json_data):
    response = MagicMock()
    response.json.return_value = json_data
    return response


@patch("gogstash.gog_api.requests.get")
def test_get_library_calls_correct_url_headers_and_params(mock_get):
    mock_get.return_value = make_response({"totalProducts": 5, "products": []})

    result = gog_api.get_library("mytoken", page=2)

    args, kwargs = mock_get.call_args
    assert args[0] == gog_api.LIBRARY_URL
    assert kwargs["headers"] == {"Authorization": "Bearer mytoken"}
    assert kwargs["params"] == {"page": 2}
    assert result == {"totalProducts": 5, "products": []}


@patch("gogstash.gog_api.requests.get")
def test_get_downloadable_single_batch_under_50(mock_get):
    mock_get.return_value = make_response([{"id": 1}, {"id": 2}, {"id": 3}])

    result = gog_api.get_downloadable("token", [1, 2, 3])

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

    result = gog_api.get_downloadable("token", ids)

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
        result = gog_api.get_downloadable("token", [])
        mock_get.assert_not_called()
        assert result == []


@patch("gogstash.gog_api.get_library")
def test_library_fetch_thread_emits_succeeded_with_result(mock_get_library):
    mock_get_library.return_value = {"products": []}
    thread = gog_api.LibraryFetchThread("token")
    received = []
    thread.succeeded.connect(lambda result: received.append(result))
    thread.failed.connect(lambda msg: pytest_fail_helper(msg))

    thread.run()

    assert received == [{"products": []}]


@patch("gogstash.gog_api.get_library")
def test_library_fetch_thread_emits_failed_on_exception(mock_get_library):
    mock_get_library.side_effect = RuntimeError("network exploded")
    thread = gog_api.LibraryFetchThread("token")
    errors = []
    thread.failed.connect(lambda msg: errors.append(msg))

    thread.run()

    assert errors == ["network exploded"]


def pytest_fail_helper(msg):
    raise AssertionError(f"failed signal should not have fired: {msg}")
