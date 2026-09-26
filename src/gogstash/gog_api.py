"""Wrappers around the GOG web API endpoints used by GogStash."""

import requests
from typing import Callable

from gogstash import gog_auth


LIBRARY_URL = "https://embed.gog.com/account/getFilteredProducts"
PRODUCT_URL = "https://api.gog.com/products"

def fetch_library() -> list[dict]:
    """Fetch every product in the user's GOG library.

    Walks through all pages of the library endpoint.

    Returns:
        list[dict]: Product entries as returned by GOG.

    Raises:
        PermissionError: If the user is not logged in.
    """
    token = gog_auth.get_valid_token()
    if not token:
        raise PermissionError("Authentication failed. Login again.")
    products = []
    response = requests.get(
        LIBRARY_URL, 
        headers={"Authorization": f"Bearer {token['access_token']}"}, 
        params={
            "page": 1
    })
    response_json = response.json()
    total_pages = response_json.get('totalPages')
    products.extend(response_json.get('products'))
    for i in range(2, total_pages+1):
        response = requests.get(
            LIBRARY_URL, 
            headers={"Authorization": f"Bearer {token['access_token']}"}, 
            params={
                "page": i
        })
        products.extend(response.json().get('products'))
    return products

def fetch_downloadables(product_ids: list, progress_callback: Callable[[int], None] = None) -> list[dict]:
    """Fetch download metadata for a list of products.

    Products are requested in batches of 50.

    Args:
        product_ids (list): GOG product IDs.
        progress_callback (Callable[[int], None]): Optional callable that
            receives the percentage of products fetched after each batch.

    Returns:
        list[dict]: Product details with the ``downloads`` field expanded.

    Raises:
        PermissionError: If the user is not logged in.
    """
    token = gog_auth.get_valid_token()
    if not token:
        raise PermissionError("Authentication failed. Login again.")
    product_info = []
    total = len(product_ids)
    while product_ids:
        chunk, product_ids = product_ids[:50], product_ids[50:]
        response = requests.get(
            PRODUCT_URL,
            headers={"Authorization": f"Bearer {token['access_token']}"},
            params={
                'ids': ','.join(str(pid) for pid in chunk),
                'expand': 'downloads'
            }
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