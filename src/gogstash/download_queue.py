from gogstash import library_db
from gogstash import settings
from gogstash import gog_api
from pathlib import Path
import urllib
import requests

from PySide6.QtCore import QThread, Signal

class DownloadWorkerThread(QThread):
    succeeded = Signal(list)
    failed = Signal(str, list)
    progress = Signal(int, int)

    def __init__(self, access_token, product_id: int, parent=None):
        super().__init__(parent)
        self.access_token = access_token
        self.product_id = product_id
        self.file_queue = None
        self.fetched_list = []
        self.total_size = 0
        self.fetched_size = 0

    def run(self):
        try:
            self.file_queue = generate_download_list((self.product_id,))
            if not self.file_queue:
                self.failed.emit("No files to download",self.fetched_list)
                return
            slug = library_db.get_product_listing((self.product_id,))[0]['slug']
            download_path: Path = Path(settings.read_setting('download_path')) / slug
        except Exception as e:
            self.failed.emit(str(e),self.fetched_list)
            return
        self.total_size = self.total_size + sum(file['size'] for file in self.file_queue)
        for file in self.file_queue:
            resolved = gog_api.resolve_downlink(self.access_token, file['downlink'])
            cdn_link = resolved['downlink']
            filename = urllib.parse.urlparse(cdn_link).path.rsplit('/',-1)[-1]
            filename = urllib.parse.unquote(filename)
            save_path: Path = download_path / file['directory'] / filename
            save_path.parent.mkdir(parents=True, exist_ok=True)
            download_response = requests.get(cdn_link, stream=True)
            try:
                with open(save_path, 'wb') as fp:
                    for chunk in download_response.iter_content(chunk_size=1024*1024):
                        bytes_written = fp.write(chunk)
                        self.fetched_size = self.fetched_size + bytes_written
                        self.update_progress()
                self.fetched_list.append((save_path.name, save_path.stat().st_size))
            except Exception as e:
                self.fetched_list.append((save_path.name, -1))
                self.failed.emit(str(e), self.fetched_list)
                break
        else:
            self.succeeded.emit(self.fetched_list)


    def update_progress(self):
        self.progress.emit(self.fetched_size, self.total_size)


def _platform_helper(platforms: list[str]) -> list[str]:
    platform_filter = []
    if 'Linux' in platforms:
        platform_filter.append('linux')
    if 'Windows' in platforms:
        platform_filter.append('windows')
    if 'MacOS' in platforms:
        platform_filter.append('mac')
    return platform_filter

def estimate_download_size(product_id: int) -> int:
    return sum(file['size'] for file in generate_download_list((product_id,)))

def generate_download_list(product_ids: tuple[int]) -> list[dict]:
    if not product_ids:
        return
    downloadables = library_db.get_downloadables(product_ids)
    bonus_content = settings.read_setting('bonus_content')
    platforms = _platform_helper(settings.read_setting('platform_filter'))
    patches = settings.read_setting('patches')
    files = []
    for item in downloadables:
        if not item['os'] in platforms and item['os']:
            continue
        file_info = {
            'directory': "",
            'file': item['file_id'],
            'os': item['os'],
            'size': item['file_size'],
            'downlink': item['downlink'],
        }
        if item['category'] == 'installers':
            file_info['directory'] = item['group_id']
        elif item['category'] == 'patches' and patches:
            file_info['directory'] = 'patches'
        elif item['category'] == 'bonus_content' and bonus_content:
            file_info['directory'] = 'bonus_content'
        else:
            continue
        files.append(file_info)
    return files

if __name__ == "__main__":
    file_list = generate_download_list((1929434313,))
    for item in file_list:
        print(item)