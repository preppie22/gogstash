"""OAuth login and token storage for the GOG API.

Uses the public GOG Galaxy client credentials. The token is stored as
JSON in the config directory with an added ``expiry`` Unix timestamp.
"""

import json
import requests
import threading
import time
from pathlib import Path
from enum import StrEnum
from urllib.parse import urlsplit, parse_qs
import logging

from gogstash import paths
from gogstash.constants import (
    HTTP_TIMEOUT_SHORT,
    CLIENT_ID,
    CLIENT_SECRET
)

log = logging.getLogger(__name__)
_token_lock = threading.Lock()

class AuthenticationFailure(Exception):
    """Raised when the user isn't logged in, or GOG refuses the token, the
    login code or the refresh token."""

REDIRECT_URI = "https://embed.gog.com/on_login_success?origin=client"
AUTH_URL = "https://auth.gog.com/auth"
TOKEN_URL = "https://auth.gog.com/token"

class GrantType(StrEnum):
    """OAuth grant types accepted by the GOG token endpoint."""
    AUTHORIZE = 'authorization_code'
    REFRESH = 'refresh_token'

def build_auth_uri() -> str:
    """Build the GOG login URL opened by the embedded browser.

    Returns:
        str: The authorization URL.
    """
    return requests.Request('GET', AUTH_URL, params={
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'layout': 'client2'
    }).prepare().url

def extract_code(url) -> str | None:
    """Get the authorization code from the login success address.

    Args:
        url (str): The address GOG redirects to after login, e.g.
            ``https://embed.gog.com/on_login_success?origin=client&code=...``.

    Returns:
        str | None: The authorization code, or None if ``url`` is empty,
        isn't the login success page or has no code.
    """
    if not url:
        return None
    parts = urlsplit(url)
    if parts.hostname == "embed.gog.com" and parts.path == "/on_login_success":
        codes = parse_qs(parts.query).get("code")
        return codes[0] if codes else None
    return None

def fetch_token(code: str = None, type: GrantType = GrantType.AUTHORIZE, refresh_token: str = None) -> dict:
    """Request an access token from GOG.

    Args:
        code (str): Authorization code from the login redirect. Used with
            ``GrantType.AUTHORIZE``.
        type (GrantType): The grant type to request.
        refresh_token (str): Refresh token of an existing login. Used with
            ``GrantType.REFRESH``.

    Returns:
        dict: The token response with an added ``expiry`` Unix timestamp.

    Raises:
        requests.RequestException: If the request fails. It is the same
            class ``requests`` raised, with a message that leaves out the
            URL, whose query holds the code or refresh token.
        AuthenticationFailure: If GOG refuses the code or refresh token.
            The message is GOG's ``error_description``.
    """
    parameters = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'grant_type': type
    }
    if type == GrantType.AUTHORIZE:
        parameters['code'] = code
        parameters['redirect_uri'] = REDIRECT_URI
    else:
        parameters['refresh_token'] = refresh_token

    start_time = time.time()
    try:
        response = requests.get(TOKEN_URL, params=parameters, timeout=HTTP_TIMEOUT_SHORT)
    except requests.RequestException as e:
        raise e.__class__("token request to gog failed") from None
    token_json = response.json()
    if token_json.get('expires_in') is None:
        log.warning(f"{token_json.get('error',"")}: {token_json.get('error_description',"")} | status code: {response.status_code} ")
        raise AuthenticationFailure(token_json.get('error_description',""))
    token_json["expiry"] = start_time+token_json["expires_in"]
    return token_json

def is_token_expired(token: dict) -> bool:
    """Check whether a token has expired.

    Args:
        token (dict): Token with an ``expiry`` key.

    Returns:
        bool: True if the expiry time has passed.
    """
    return time.time() >= token["expiry"]

def get_valid_token() -> dict | None:
    """Load the saved token, refreshing it if it has expired.

    A refreshed token is saved to disk before it is returned. If GOG
    refuses the refresh, the saved token is deleted, since it will never
    work again, and the user is logged out. The whole check runs under a
    lock, so threads that find the same expired token refresh it once:
    the first one refreshes it and the rest load the new one.

    Returns:
        dict | None: A valid token, or None if the user is not logged in.

    Raises:
        requests.RequestException: If GOG can't be reached to refresh an
            expired token. The saved token is kept.
    """
    with _token_lock:
        token = _load_token()
        if not token:
            return None
        if is_token_expired(token):
            try:
                new_token = fetch_token(type=GrantType.REFRESH, refresh_token=token["refresh_token"])
            except AuthenticationFailure:
                log.warning("logged out because saved login was refused")
                clear_token()
                return None
            log.info("token expired and was refreshed")
            save_token(new_token)
            return new_token
    return token

def save_token(token: dict) -> None:
    """Save a token to the config directory.

    The token is written to a temporary file first, which then replaces
    the saved one, so a reader never sees a half-written file. If the
    write fails, the temporary file is removed and the saved token is
    left as it was.

    Args:
        token (dict): The token to save.
    """
    save_file = paths.config_file_path(paths.ConfigFile.TOKEN)
    save_file.parent.mkdir(parents=True, exist_ok=True)

    temp_filename = save_file.name + "~"
    temp_file: Path = save_file.parent / temp_filename

    try:
        with open(temp_file, 'w') as f:
            json.dump(token, f)
    except Exception:
        log.exception(f"failed to save token")
        temp_file.unlink(missing_ok=True)
        raise
    temp_file.replace(save_file)

def clear_token() -> None:
    """Delete the saved token, which logs the user out."""
    token_file = paths.config_file_path(paths.ConfigFile.TOKEN)
    token_file.unlink(missing_ok=True)

def _load_token() -> dict | None:
    """Load the saved token from disk.

    A file that isn't valid JSON, or doesn't hold a JSON object, can never
    be used to log in, so it is deleted and the user is logged out.

    Returns:
        dict | None: The saved token, or None if there is no usable token
        file.
    """
    save_file = paths.config_file_path(paths.ConfigFile.TOKEN)
    token_dict = None
    try:
        with open(save_file, 'r') as f:
            token_dict = json.load(f)
    except FileNotFoundError:
        return None
    except ValueError:
        clear_token()
        log.warning("logged out because token on disk was malformed or invalid")
        return None
    if isinstance(token_dict, dict):
        return token_dict
    clear_token()
    log.warning("logged out because token on disk was malformed or invalid")
    return None

if __name__ == "__main__":
    print(build_auth_uri())
    # save_token({"foo": "bar"})
    print(_load_token())
