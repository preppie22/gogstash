import platformdirs
import json
from pathlib import Path
import requests
from enum import Enum

from PySide6.QtCore import QThread, Signal

class LibraryFetchThread(QThread):
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, access_token, parent=None):
        super().__init__(parent)
        self.access_token = access_token

    def run(self):
        try:
            result = get_library(self.access_token)
            self.succeeded.emit(result)
        except Exception as e:
            self.failed.emit(str(e))

LIBRARY_URL = "https://embed.gog.com/account/getFilteredProducts"

def get_library(access_token: str, page: int = 1) -> dict:
    response = requests.get(
        LIBRARY_URL, 
        headers={
            "Authorization": f"Bearer {access_token}"
        }, 
        params={
            "media_type": 1,
            "page": page
        })
    return response.json()

if __name__ == "__main__":
    from gogstash import gog_auth

    token = gog_auth.load_token()
    result = get_library(token["access_token"])
    print(f"Total Games: {result['totalProducts']}")
    print(f"Products per Page: {result['productsPerPage']}")
    print(f"Total pages: {result['totalPages']}")