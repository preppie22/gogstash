import requests

from gogstash import library_db
from PySide6.QtCore import QThread, Signal

LIBRARY_URL = "https://embed.gog.com/account/getFilteredProducts"
PRODUCT_URL = "https://api.gog.com/products"

class LibraryFetchThread(QThread):
    succeeded = Signal(list)
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

def get_library(access_token: str) -> list[dict]:
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

def get_downloadable(access_token: str, product_ids: list) -> list[dict]:
    batches = []
    product_info = []
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
    return product_info

if __name__ == "__main__":
    from gogstash import gog_auth

    token = gog_auth.get_valid_token()
    result = get_library(token["access_token"])
    print(f"Total Games: {result['totalProducts']}")
    print(f"Products per Page: {result['productsPerPage']}")
    print(f"Total pages: {result['totalPages']}")