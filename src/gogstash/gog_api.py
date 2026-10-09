"""Wrappers around the GOG web API endpoints used by GogStash."""

import requests
from typing import Callable

from gogstash import gog_auth

PRODUCT_URL = "https://api.gog.com/products"
USER_GAMES = "https://embed.gog.com/user/data/games"

class FetchInterrupted(Exception):
    """Raised by ``fetch_downloadables`` when its caller asks it to stop."""

def fetch_owned_ids() -> set:
    """Fetch the IDs of every product the user owns on GOG.

    The list mixes games, DLCs and packs and carries no other details, so
    callers look the IDs up with ``fetch_downloadables`` to tell them apart.
    GOG rejects a bad token by redirecting to its login page, so a redirect
    clears the saved token and counts as a failed login.

    Returns:
        set: Owned GOG product IDs as ints.

    Raises:
        PermissionError: If the user is not logged in or GOG rejects the
            token.
        requests.HTTPError: If GOG answers with an error status.
        KeyError: If the response has no ``owned`` list.
    """
    token = gog_auth.get_valid_token()
    if not token:
        raise PermissionError("Authentication failed. Login again.")
    response = requests.get(
        USER_GAMES,
        headers={"Authorization": f"Bearer {token['access_token']}"},
        allow_redirects=False
    )
    if response.is_redirect:
        gog_auth.clear_token()
        raise PermissionError("Authentication failed. Login again.")
    response.raise_for_status()
    response_dict = response.json()
    owned_list = response_dict['owned']
    return set(owned_list)

def fetch_downloadables(product_ids: list, progress_callback: Callable[[int], None] = None, should_stop: Callable[[], bool] = None) -> list[dict]:
    """Fetch download metadata for a list of products.

    Products are requested in batches of 50. The token is required even
    though GOG answers without one: anonymous requests silently leave out
    secret DLCs and products that are no longer sold.

    Args:
        product_ids (list): GOG product IDs.
        progress_callback (Callable[[int], None]): Optional callable that
            receives the percentage of products fetched after each batch.
        should_stop (Callable[[], bool]): Optional callable checked before
            each batch. Fetching stops once it returns True.

    Returns:
        list[dict]: Product details with the ``downloads`` field expanded.

    Raises:
        PermissionError: If the user is not logged in.
        FetchInterrupted: If ``should_stop`` returned True. Raised instead
            of returning the batches fetched so far, so a caller can't
            mistake part of the library for all of it.
    """
    token = gog_auth.get_valid_token()
    if not token:
        raise PermissionError("Authentication failed. Login again.")
    product_info = []
    total = len(product_ids)
    while product_ids:
        if should_stop and should_stop():
            raise FetchInterrupted
        chunk, product_ids = product_ids[:50], product_ids[50:]
        response = requests.get(
            PRODUCT_URL,
            headers={"Authorization": f"Bearer {token['access_token']}"},
            params={
                'ids': ','.join(str(pid) for pid in chunk),
                'expand': 'downloads'
            },
            allow_redirects=False
        )
        product_info.extend(response.json())
        if progress_callback:
            progress_callback(len(product_info) * 100 / total)
    return product_info

def resolve_downlink(downlink: str) -> dict:
    """Resolve a GOG API downlink to its CDN location.

    Args:
        downlink (str): Downlink URL from the product download metadata.

    Returns:
        dict: Response with the CDN ``downlink`` and, for installers and
        patches, a ``checksum`` URL.

    Raises:
        PermissionError: If the user is not logged in.
        requests.HTTPError: If GOG returns an error status.
    """
    token = gog_auth.get_valid_token()
    if not token:
        raise PermissionError("Authentication failed. Login again.")
    response = requests.get(
        downlink,
        headers={"Authorization": f"Bearer {token['access_token']}"}
    )
    response.raise_for_status()
    return response.json()