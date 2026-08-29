import platformdirs
import json
from pathlib import Path
import requests
from enum import StrEnum

# These are public and obtained from https://gogapidocs.readthedocs.io/en/latest/auth.html
CLIENT_ID = "46899977096215655"
CLIENT_SECRET = "9d85c43b1482497dbbce61f6e4aa173a433796eeae2ca8c5f6129f2dc4de46d9"

REDIRECT_URI = "https://embed.gog.com/on_login_success?origin=client"
AUTH_URL = "https://auth.gog.com/auth"
TOKEN_URL = "https://auth.gog.com/token"

class GrantType(StrEnum):
    AUTHORIZE = 'authorization_code'
    REFRESH = 'refresh_token'

def build_auth_uri() -> str:
    return requests.Request('GET', AUTH_URL, params={
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'layout': 'client2'
    }).prepare().url

def fetch_token(code: str, type: GrantType = GrantType.AUTHORIZE, refresh_token: str = None) -> dict:
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

    response = requests.get(TOKEN_URL, params=parameters)
    return response.json()

def _token_path_helper() -> Path:
    config_dir = platformdirs.user_config_dir(appname='gogstash')
    return Path(config_dir) / "token.json"

def save_token(token: dict) -> None:
    save_file = _token_path_helper()
    save_file.parent.mkdir(parents=True, exist_ok=True)
    with open(save_file, 'w') as f:
        json.dump(token, f)

def load_token() -> dict:
    save_file = _token_path_helper()
    token_dict = None
    try:
        with open(save_file, 'r') as f:
            token_dict = json.load(f)
    except FileNotFoundError:
        return None
    return token_dict

if __name__ == "__main__":
    print(build_auth_uri())
    save_token({"foo": "bar"})
    print(load_token())
