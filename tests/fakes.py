"""Fake GOG API payloads shared by the tests."""


def gog_product(product_id, title, slug=None, *, game_type="game", downloads=None, dlcs=None,
                windows=True, linux=False, osx=True):
    """Build an api.gog.com/products entry, as fetch_downloadables returns it.

    Only the fields GogStash reads are filled in. ``dlcs`` takes a list of
    DLC IDs and is shaped like GOG's: an empty list when there are none,
    otherwise a dict with a ``products`` list.
    """
    slug = slug or title.lower().replace(" ", "-")
    return {
        "id": product_id,
        "title": title,
        "slug": slug,
        "game_type": game_type,
        "content_system_compatibility": {"windows": windows, "osx": osx, "linux": linux},
        "links": {"product_card": f"https://www.gog.com/game/{slug}"},
        "images": {"icon": f"//images.example.com/{slug}.png"},
        "dlcs": {"products": [{"id": dlc_id} for dlc_id in dlcs]} if dlcs else [],
        "downloads": downloads if downloads is not None else {},
    }
