import requests
from typing import Callable

from gogstash import library_db
from PySide6.QtCore import QThread, Signal

LIBRARY_URL = "https://embed.gog.com/account/getFilteredProducts"
PRODUCT_URL = "https://api.gog.com/products"

class LibraryFetchThread(QThread):
    succeeded = Signal(list)
    failed = Signal(str)
    progress = Signal(int)
    
    def __init__(self, access_token, force: bool = False, parent=None):
        super().__init__(parent)
        self.access_token = access_token
        self.force = force

    def run(self, product_id: tuple[int] = ()):
        try:
            product_listing = library_db.get_product_listing(product_id)
            if not (product_listing or product_id) or self.force:
                library_db.update_products(fetch_library(self.access_token))
                product_listing = library_db.get_product_listing()
                all_product_ids = [p['product_id'] for p in product_listing]
                library_db.update_downloadables(fetch_downloadables(self.access_token, all_product_ids, self.update_progress))
                product_listing = library_db.get_product_listing()
            self.succeeded.emit(product_listing)
        except Exception as e:
            self.failed.emit(str(e))

    def update_progress(self, percentage: int):
        self.progress.emit(percentage)

class DownloadablesFetchThread(QThread):
    succeeded = Signal(list)
    failed = Signal(str)

    def __init__(self, access_token, parent=None):
        super().__init__(parent)
        self.access_token = access_token

    def run(self, product_id: tuple[int] = ()):
        try:
            downloadables = library_db.get_downloadables(product_id)
            if not downloadables:
                self.failed.emit("Product does not exist")
                return
            self.succeeded.emit(downloadables)
        except Exception as e:
            self.failed.emit(str(e))

def load_library() -> list[dict]:
    return library_db.get_product_listing(())

def fetch_library(access_token: str) -> list[dict]:
    products = []
    response = requests.get(
        LIBRARY_URL, 
        headers={"Authorization": f"Bearer {access_token}"}, 
        params={
            "page": 1
    })
    response_json = response.json()
    total_pages = response_json.get('totalPages')
    products.extend(response_json.get('products'))
    for i in range(2, total_pages+1):
        response = requests.get(
            LIBRARY_URL, 
            headers={"Authorization": f"Bearer {access_token}"}, 
            params={
                "page": i
        })
        products.extend(response.json().get('products'))
    return products

def fetch_downloadables(access_token: str, product_ids: list, progress_callback: Callable[[int], None] = None) -> list[dict]:
    batches = []
    product_info = []
    total = len(product_ids)
    while product_ids:
        chunk, product_ids = product_ids[:50], product_ids[50:]
        response = requests.get(
            PRODUCT_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                'ids': ','.join(str(pid) for pid in chunk),
                'expand': 'downloads'
            }
        )
        product_info.extend(response.json())
        if progress_callback:
            progress_callback(len(product_info) * 100 / total)
    return product_info

def resolve_downlink(access_token: str, downlink: str) -> dict:
    response = requests.get(
        downlink,
        headers={"Authorization": f"Bearer {access_token}"}
    )
    response.raise_for_status()
    return response.json()

if __name__ == "__main__":
    from gogstash import gog_auth

    token = gog_auth.get_valid_token()
    result = fetch_library(token["access_token"])
    print(f"Total Games: {result['totalProducts']}")
    print(f"Products per Page: {result['productsPerPage']}")
    print(f"Total pages: {result['totalPages']}")