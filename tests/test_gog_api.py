from unittest.mock import MagicMock, patch

import pytest

from gogstash import gog_api


FAKE_TOKEN = {"access_token": "mytoken"}


def make_response(json_data):
    response = MagicMock()
    response.json.return_value = json_data
    return response


@patch("gogstash.gog_api.requests.get")
@patch("gogstash.gog_api.gog_auth.get_valid_token")
def test_get_library_single_page(mock_get_valid_token, mock_get):
    mock_get_valid_token.return_value = FAKE_TOKEN
    mock_get.return_value = make_response(
        {"totalProducts": 2, "totalPages": 1, "products": [{"id": 1}, {"id": 2}]}
    )

    result = gog_api.fetch_library()

    assert mock_get.call_count == 1
    args, kwargs = mock_get.call_args
    assert args[0] == gog_api.LIBRARY_URL
    assert kwargs["headers"] == {"Authorization": "Bearer mytoken"}
    assert kwargs["params"] == {"page": 1}
    assert result == [{"id": 1}, {"id": 2}]


@patch("gogstash.gog_api.requests.get")
@patch("gogstash.gog_api.gog_auth.get_valid_token")
def test_get_library_fetches_every_page_and_flattens_results(mock_get_valid_token, mock_get):
    mock_get_valid_token.return_value = FAKE_TOKEN
    mock_get.side_effect = [
        make_response({"totalPages": 3, "products": [{"id": 1}]}),
        make_response({"totalPages": 3, "products": [{"id": 2}]}),
        make_response({"totalPages": 3, "products": [{"id": 3}]}),
    ]

    result = gog_api.fetch_library()

    assert mock_get.call_count == 3
    sent_pages = [call.kwargs["params"]["page"] for call in mock_get.call_args_list]
    assert sent_pages == [1, 2, 3]
    assert result == [{"id": 1}, {"id": 2}, {"id": 3}]


@patch("gogstash.gog_api.gog_auth.get_valid_token")
def test_fetch_library_raises_permission_error_when_not_logged_in(mock_get_valid_token):
    mock_get_valid_token.return_value = None

    with pytest.raises(PermissionError):
        gog_api.fetch_library()


@patch("gogstash.gog_api.requests.get")
@patch("gogstash.gog_api.gog_auth.get_valid_token")
def test_get_downloadable_single_batch_under_50(mock_get_valid_token, mock_get):
    mock_get_valid_token.return_value = FAKE_TOKEN
    mock_get.return_value = make_response([{"id": 1}, {"id": 2}, {"id": 3}])

    result = gog_api.fetch_downloadables([1, 2, 3])

    assert mock_get.call_count == 1
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["ids"] == "1,2,3"
    assert kwargs["params"]["expand"] == "downloads"
    assert kwargs["headers"] == {"Authorization": "Bearer mytoken"}
    assert result == [{"id": 1}, {"id": 2}, {"id": 3}]


@patch("gogstash.gog_api.requests.get")
@patch("gogstash.gog_api.gog_auth.get_valid_token")
def test_get_downloadable_splits_into_chunks_of_50(mock_get_valid_token, mock_get):
    mock_get_valid_token.return_value = FAKE_TOKEN
    ids = list(range(1, 121))  # 120 ids -> chunks of 50, 50, 20
    mock_get.side_effect = [
        make_response([{"id": "from-batch-1"}]),
        make_response([{"id": "from-batch-2"}]),
        make_response([{"id": "from-batch-3"}]),
    ]

    result = gog_api.fetch_downloadables(ids)

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


@patch("gogstash.gog_api.requests.get")
@patch("gogstash.gog_api.gog_auth.get_valid_token")
def test_get_downloadable_empty_input_makes_no_requests(mock_get_valid_token, mock_get):
    mock_get_valid_token.return_value = FAKE_TOKEN

    result = gog_api.fetch_downloadables([])

    mock_get.assert_not_called()
    assert result == []


@patch("gogstash.gog_api.requests.get")
@patch("gogstash.gog_api.gog_auth.get_valid_token")
def test_fetch_downloadables_raises_permission_error_when_not_logged_in(mock_get_valid_token, mock_get):
    mock_get_valid_token.return_value = None

    with pytest.raises(PermissionError):
        gog_api.fetch_downloadables([1, 2, 3])

    mock_get.assert_not_called()


@patch("gogstash.gog_api.requests.get")
@patch("gogstash.gog_api.gog_auth.get_valid_token")
def test_resolve_downlink_returns_cdn_url_and_checksum(mock_get_valid_token, mock_get):
    mock_get_valid_token.return_value = FAKE_TOKEN
    mock_get.return_value = make_response({
        "downlink": "https://gog-cdn.example.com/secure/offline/111/setup_fake_game.exe",
        "checksum": "https://gog-cdn.example.com/secure/offline/111/setup_fake_game.exe.xml",
    })

    result = gog_api.resolve_downlink("https://api.gog.com/products/111/downlink/installer/file1")

    assert mock_get.call_count == 1
    args, kwargs = mock_get.call_args
    assert args[0] == "https://api.gog.com/products/111/downlink/installer/file1"
    assert kwargs["headers"] == {"Authorization": "Bearer mytoken"}
    assert result == {
        "downlink": "https://gog-cdn.example.com/secure/offline/111/setup_fake_game.exe",
        "checksum": "https://gog-cdn.example.com/secure/offline/111/setup_fake_game.exe.xml",
    }


@patch("gogstash.gog_api.requests.get")
@patch("gogstash.gog_api.gog_auth.get_valid_token")
def test_resolve_downlink_raises_permission_error_when_not_logged_in(mock_get_valid_token, mock_get):
    mock_get_valid_token.return_value = None

    with pytest.raises(PermissionError):
        gog_api.resolve_downlink("https://api.gog.com/products/111/downlink/installer/file1")

    mock_get.assert_not_called()
