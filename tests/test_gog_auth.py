import time

import pytest
import requests
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from gogstash import gog_auth, paths
from gogstash.constants import HTTP_TIMEOUT_SHORT


def make_response(json_data, status_code=200):
    response = MagicMock()
    response.json.return_value = json_data
    response.status_code = status_code
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
    # A token request that hangs would freeze login or a refresh (#29)
    # Token requests block the window while they wait, so they give up fast.
    assert kwargs["timeout"] == HTTP_TIMEOUT_SHORT

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


@patch("gogstash.gog_auth.requests.get")
def test_a_refreshed_token_leaves_a_line_but_not_itself_in_the_log(mock_get, caplog):
    gog_auth.save_token(
        {"access_token": "old-secret-abc", "refresh_token": "refresh-secret-xyz", "expiry": time.time() - 10}
    )
    mock_get.return_value = make_response(
        {"access_token": "new-secret-def", "refresh_token": "refresh-secret-xyz", "expires_in": 3600}
    )

    with caplog.at_level("INFO", logger="gogstash.gog_auth"):
        gog_auth.get_valid_token()

    [record] = caplog.records
    assert record.levelname == "INFO"
    for secret in ("old-secret-abc", "new-secret-def", "refresh-secret-xyz"):
        assert secret not in record.getMessage()  # log files get pasted into bug reports


@patch("gogstash.gog_auth.requests.get")
def test_a_refused_refresh_logs_you_out_instead_of_blowing_up(mock_get, caplog):
    # Regression (#31): GOG's "no" came back as KeyError: 'expires_in', and
    # at startup that took the whole app down before it had a window. A
    # refused login is just a logged out one, and a dead token gets binned
    # instead of being refused all over again on every check.
    gog_auth.save_token(
        {"access_token": "stale", "refresh_token": "myrefresh", "expiry": time.time() - 10}
    )
    mock_get.return_value = make_response({"error": "invalid_grant"}, status_code=400)

    with caplog.at_level("INFO", logger="gogstash.gog_auth"):
        assert gog_auth.get_valid_token() is None

    assert gog_auth._load_token() is None
    assert [r.levelname for r in caplog.records] == ["WARNING", "WARNING"]  # GOG's reason, then what came of it


@patch("gogstash.gog_auth.requests.get")
def test_an_offline_refresh_keeps_the_saved_login(mock_get):
    # Can't reach GOG is not the same as GOG said no. The refresh token is
    # fine, it just can't be cashed in right now, so it stays for next time.
    saved = {"access_token": "stale", "refresh_token": "myrefresh", "expiry": time.time() - 10}
    gog_auth.save_token(saved)
    mock_get.side_effect = requests.ConnectionError("no network")

    with pytest.raises(requests.ConnectionError):
        gog_auth.get_valid_token()

    assert gog_auth._load_token() == saved


@patch("gogstash.gog_auth.requests.get")
def test_gog_refusing_a_token_logs_its_reason_and_status(mock_get, caplog):
    # GOG says why in its answer, and the status code says how loudly. Both
    # go in the log, the refresh token stays out.
    mock_get.return_value = make_response(
        {"error": "invalid_grant", "error_description": "The refresh token is invalid."},
        status_code=400,
    )

    with caplog.at_level("INFO", logger="gogstash.gog_auth"):
        with pytest.raises(gog_auth.AuthenticationFailure):
            gog_auth.fetch_token(type=gog_auth.GrantType.REFRESH, refresh_token="myrefresh")

    [record] = caplog.records
    message = record.getMessage()
    assert record.levelname == "WARNING"
    assert "invalid_grant" in message
    assert "The refresh token is invalid." in message
    assert "400" in message
    assert "myrefresh" not in message


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


LEAKY_URL = "Max retries exceeded with url: /token?grant_type=refresh_token&refresh_token=REFRESH-SECRET&code=CODE-SECRET"


def _full_story(error):
    # Everything a traceback would show, chained exceptions included, which
    # is exactly what log.exception and the excepthook write out.
    import traceback
    return "".join(traceback.format_exception(error))


@pytest.mark.parametrize("error_class", [requests.ConnectionError, requests.Timeout, requests.exceptions.SSLError])
@patch("gogstash.gog_auth.requests.get")
def test_a_failed_token_request_keeps_its_class_but_drops_the_secrets(mock_get, error_class):
    # requests puts the whole query string in its message, and the query is
    # where the refresh token rides. The class stays, so the download worker
    # still knows a dropped connection when it sees one.
    mock_get.side_effect = error_class(LEAKY_URL)
    secret = "REFRESH-" + "SECRET"  # spelled apart, or the traceback quotes this test's own source back at us

    with pytest.raises(error_class) as raised:
        gog_auth.fetch_token(type=gog_auth.GrantType.REFRESH, refresh_token=secret)

    story = _full_story(raised.value)
    assert "REFRESH-SECRET" not in story
    assert "CODE-SECRET" not in story
    assert "During handling" not in story  # the leaky original isn't hitching a ride


@patch("gogstash.gog_auth.requests.get")
def test_an_offline_refresh_during_a_library_refresh_keeps_the_token_out_of_the_log(mock_get, caplog):
    # The way it actually happens: expired token, no network, someone clicks
    # Refresh. library_db logs the traceback, and the traceback used to be
    # carrying a long-lived refresh token to whoever reads the bug report.
    from gogstash import library_db
    gog_auth.save_token({"access_token": "a", "refresh_token": "REFRESH-SECRET", "expiry": time.time() - 10})
    mock_get.side_effect = requests.ConnectionError(LEAKY_URL)
    library_db._create_db(force=True)
    thread = library_db.LibraryFetchThread(force=True)
    failed = []
    thread.failed.connect(failed.append)

    with caplog.at_level("INFO"):
        thread.run()

    logged = "\n".join(f"{r.getMessage()}\n{r.exc_text or ''}" for r in caplog.records)
    assert failed  # it still fails, it just keeps its mouth shut about why
    assert "REFRESH-SECRET" not in logged
    assert "REFRESH-SECRET" not in failed[0]


@patch("gogstash.gog_auth.requests.get")
def test_gog_refusing_a_token_is_an_auth_failure_not_a_key_error(mock_get):
    # A KeyError would be caught by anything catching KeyError, bugs included.
    # Refused is its own thing, and callers need to catch exactly that.
    mock_get.return_value = make_response(
        {"error": "invalid_grant", "error_description": "The refresh token is invalid."},
        status_code=400,
    )

    with pytest.raises(gog_auth.AuthenticationFailure, match="The refresh token is invalid."):
        gog_auth.fetch_token(type=gog_auth.GrantType.REFRESH, refresh_token="whatever")


def test_gog_api_still_answers_to_the_old_name():
    # library_db and the download worker catch gog_api.AuthenticationFailure.
    # One class, two addresses.
    from gogstash import gog_api
    assert gog_api.AuthenticationFailure is gog_auth.AuthenticationFailure


# --- many threads, one token ---

def test_threads_that_find_the_same_expired_token_refresh_it_once():
    # Download workers, the library fetch and the window all check the token
    # on their own. When it expires mid-run, two of them would cash in the
    # same refresh token at once, and if GOG only honours it once, the loser
    # gets "refused" and logs everybody out mid-download.
    import threading
    gog_auth.save_token({"access_token": "old", "refresh_token": "once-only", "expiry": 0})
    refreshes = []

    def slow_refresh(**kwargs):
        refreshes.append(kwargs["refresh_token"])
        time.sleep(0.2)  # long enough for every other thread to pile up behind it
        return {"access_token": "new", "refresh_token": "next", "expires_in": 3600, "expiry": time.time() + 3600}

    start = threading.Barrier(5)
    results = []

    def worker():
        start.wait()
        results.append(gog_auth.get_valid_token())

    with patch("gogstash.gog_auth.fetch_token", side_effect=slow_refresh):
        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

    assert refreshes == ["once-only"]
    assert [r["access_token"] for r in results] == ["new"] * 5


def test_saving_a_token_leaves_no_temp_file_behind():
    gog_auth.save_token({"access_token": "abc", "expiry": 1})

    token_file = paths.config_file_path(paths.ConfigFile.TOKEN)
    assert sorted(p.name for p in token_file.parent.iterdir() if p.name.startswith(token_file.name)) == [token_file.name]
    assert gog_auth._load_token() == {"access_token": "abc", "expiry": 1}


def test_a_save_that_fails_halfway_keeps_the_old_token_intact():
    # Writing straight into token.json emptied it first, so a full disk
    # mid-write left neither the old login nor the new one.
    gog_auth.save_token({"access_token": "old", "expiry": 1})

    def half_a_write(data, fp):
        fp.write('{"access_tok')
        raise OSError(28, "No space left on device")

    with patch("gogstash.gog_auth.json.dump", half_a_write):
        with pytest.raises(OSError):
            gog_auth.save_token({"access_token": "new", "expiry": 2})

    token_file = paths.config_file_path(paths.ConfigFile.TOKEN)
    assert gog_auth._load_token() == {"access_token": "old", "expiry": 1}
    assert not (token_file.parent / (token_file.name + "~")).exists()


# --- a token.json nobody can read ---

@pytest.mark.parametrize("contents", [
    '{"access_tok',          # cut off mid-write by an older version, or a crash
    b"\xff\xfe\x00garbage",  # not even text
    '["a", "list"]',         # valid JSON, wrong shape, would die on token["expiry"]
])
def test_an_unreadable_token_file_logs_you_out_and_gets_out_of_the_way(contents, caplog):
    token_file = paths.config_file_path(paths.ConfigFile.TOKEN)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(contents, bytes):
        token_file.write_bytes(contents)
    else:
        token_file.write_text(contents)

    with caplog.at_level("INFO", logger="gogstash.gog_auth"):
        assert gog_auth.get_valid_token() is None

    assert not token_file.exists()  # binned, not re-read and re-warned about on every check
    [record] = caplog.records
    assert record.levelname == "WARNING"
    assert "access_tok" not in record.getMessage() and "list" not in record.getMessage()  # contents stay out of the log


@patch("gogstash.gog_auth.requests.get")
def test_gog_answering_with_an_html_page_keeps_the_login(mock_get):
    # During an outage GOG can answer with an error page instead of JSON.
    # requests' JSONDecodeError is a ValueError too, so catching ValueError
    # around the refresh would have deleted a perfectly good login over it.
    saved = {"access_token": "old", "refresh_token": "fine", "expiry": 0}
    gog_auth.save_token(saved)
    outage = make_response(None, status_code=503)
    outage.json.side_effect = requests.exceptions.JSONDecodeError("Expecting value", "<html>Service Unavailable</html>", 0)
    mock_get.return_value = outage

    with pytest.raises(requests.RequestException):
        gog_auth.get_valid_token()

    assert gog_auth._load_token() == saved
