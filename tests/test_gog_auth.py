import time
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from gogstash import gog_auth


def make_response(json_data):
    response = MagicMock()
    response.json.return_value = json_data
    return response


def test_build_auth_uri_contains_expected_params():
    uri = gog_auth.build_auth_uri()
    parsed = urlparse(uri)
    query = parse_qs(parsed.query)

    assert uri.startswith(gog_auth.AUTH_URL)
    assert query["client_id"] == [gog_auth.CLIENT_ID]
    assert query["redirect_uri"] == [gog_auth.REDIRECT_URI]
    assert query["response_type"] == ["code"]
    assert query["layout"] == ["client2"]


@patch("gogstash.gog_auth.requests.get")
def test_fetch_token_authorize_sends_code_and_redirect_uri(mock_get):
    mock_get.return_value = make_response(
        {"access_token": "abc", "refresh_token": "def", "expires_in": 3600}
    )

    before = time.time()
    token = gog_auth.fetch_token(code="somecode")
    after = time.time()

    _, kwargs = mock_get.call_args
    params = kwargs["params"]
    assert params["grant_type"] == gog_auth.GrantType.AUTHORIZE
    assert params["code"] == "somecode"
    assert params["redirect_uri"] == gog_auth.REDIRECT_URI
    assert "refresh_token" not in params

    assert token["access_token"] == "abc"
    assert before + 3600 <= token["expiry"] <= after + 3600


@patch("gogstash.gog_auth.requests.get")
def test_fetch_token_refresh_sends_refresh_token_not_code(mock_get):
    mock_get.return_value = make_response(
        {"access_token": "new", "refresh_token": "def", "expires_in": 3600}
    )

    gog_auth.fetch_token(type=gog_auth.GrantType.REFRESH, refresh_token="oldrefresh")

    _, kwargs = mock_get.call_args
    params = kwargs["params"]
    assert params["grant_type"] == gog_auth.GrantType.REFRESH
    assert params["refresh_token"] == "oldrefresh"
    assert "code" not in params
    assert "redirect_uri" not in params


def test_is_token_expired_true_for_past_expiry():
    assert gog_auth.is_token_expired({"expiry": time.time() - 10}) is True


def test_is_token_expired_false_for_future_expiry():
    assert gog_auth.is_token_expired({"expiry": time.time() + 3600}) is False


def test_save_and_load_token_roundtrip():
    gog_auth.save_token({"foo": "bar"})
    assert gog_auth._load_token() == {"foo": "bar"}


def test_load_token_returns_none_when_missing():
    assert gog_auth._load_token() is None


def test_get_valid_token_returns_none_when_not_logged_in():
    assert gog_auth.get_valid_token() is None


@patch("gogstash.gog_auth.requests.get")
def test_get_valid_token_returns_saved_token_without_refresh(mock_get):
    saved = {"access_token": "still-good", "expiry": time.time() + 3600}
    gog_auth.save_token(saved)

    token = gog_auth.get_valid_token()

    assert token == saved
    mock_get.assert_not_called()


@patch("gogstash.gog_auth.requests.get")
def test_get_valid_token_refreshes_and_persists_when_expired(mock_get):
    gog_auth.save_token(
        {"access_token": "stale", "refresh_token": "myrefresh", "expiry": time.time() - 10}
    )
    mock_get.return_value = make_response(
        {"access_token": "refreshed", "refresh_token": "myrefresh", "expires_in": 3600}
    )

    token = gog_auth.get_valid_token()

    assert token["access_token"] == "refreshed"
    assert gog_auth._load_token()["access_token"] == "refreshed"
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["refresh_token"] == "myrefresh"


SUCCESS_URL = "https://embed.gog.com/on_login_success?origin=client&code=thecode"


def test_extract_code_returns_code_from_success_url():
    assert gog_auth.extract_code(SUCCESS_URL) == "thecode"


def test_extract_code_does_not_care_about_parameter_order():
    assert gog_auth.extract_code("https://embed.gog.com/on_login_success?code=thecode&origin=client") == "thecode"


def test_extract_code_returns_none_for_empty_input():
    assert gog_auth.extract_code("") is None
    assert gog_auth.extract_code(None) is None


def test_extract_code_returns_none_without_a_code():
    # The right page with nothing on it. Sending GOG an empty code just to
    # hear "no" is a round trip nobody needs.
    assert gog_auth.extract_code("https://embed.gog.com/on_login_success?origin=client") is None


def test_extract_code_rejects_other_pages_and_hosts():
    # People will paste the login page, the GOG homepage, and whatever else
    # was on the clipboard. Only the success page carries a real code.
    assert gog_auth.extract_code(gog_auth.build_auth_uri()) is None
    assert gog_auth.extract_code("https://embed.gog.com/somewhere_else?code=thecode") is None
    assert gog_auth.extract_code("https://www.gog.com/on_login_success?code=thecode") is None
    assert gog_auth.extract_code("hello") is None


def test_extract_code_rejects_lookalike_hosts():
    # Starts with the right name, ends somewhere else entirely.
    assert gog_auth.extract_code("https://embed.gog.com.example.net/on_login_success?code=thecode") is None
