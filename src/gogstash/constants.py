"""Values shared across modules.

Attributes:
    HTTP_TIMEOUT (tuple[int, int]): Connect and read timeouts in seconds
        for every request to GOG. The read timeout limits the wait for
        each piece of data, not the whole response, so a slow download
        that keeps receiving data never hits it. ``requests`` has no
        timeout by default and would wait forever on a silent server.
    CLIENT_ID (str): GOG Galaxy's public OAuth client ID, which GogStash
        logs in as.
    CLIENT_SECRET (str): The matching client secret. Public as well, so
        it is fine to ship.
"""
HTTP_TIMEOUT = (5,15)

# These are public and obtained from https://gogapidocs.readthedocs.io/en/latest/auth.html
CLIENT_ID = "46899977096215655"
CLIENT_SECRET = "9d85c43b1482497dbbce61f6e4aa173a433796eeae2ca8c5f6129f2dc4de46d9"