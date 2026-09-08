from gogstash import library_db
from gogstash import settings
from gogstash import gog_api
from pathlib import Path
import urllib
import requests
import hashlib
import xml.etree.ElementTree as ET
import re

from PySide6.QtCore import (
    QThread,
    QObject,
    Signal
)
class DownloadScheduler(QObject):
    game_succeeded = Signal(int, list)
    game_failed = Signal(int, str, list)
    progress_updated = Signal(int, float, float)
    finished = Signal()

    def __init__(self, access_token, product_queue: list[dict], concurrency: int = 1, parent=None):
        super().__init__(parent)
        if concurrency < 1:
            raise ValueError("Concurrency must be more than 0")
        self.tokens = concurrency
        self.download_queue = []
        self.active_queue = []
        for product in product_queue:
            queue_item = {
                'row_idx': product['idx'],
                'worker': DownloadWorkerThread(access_token, product['product_id']),
            }
            self.download_queue.append(queue_item)

    def dispatch(self):
        while self.tokens > 0 and self.download_queue:
            task = self.download_queue.pop(0)
            task['worker'].succeeded.connect(lambda fetched_list, t=task: self._handle_success(t, fetched_list))
            task['worker'].failed.connect(lambda msg, fetched_list, t=task: self._handle_failure(t, msg, fetched_list))
            task['worker'].progress.connect(lambda fetched_size, total_size, t=task: self._report_progress(t, fetched_size, total_size))
            self.active_queue.append(task)
            self.tokens = self.tokens - 1
            task['worker'].start()
        if not self.download_queue and not self.active_queue:
            self.finished.emit()

    def _handle_success(self, job: dict, fetched_list: list) -> None:
        self.game_succeeded.emit(job['row_idx'], fetched_list)
        self.active_queue.remove(job)
        self.tokens = self.tokens + 1
        self.dispatch()

    def _handle_failure(self, job: dict, msg: str, fetched_list: list) -> None:
        self.game_failed.emit(job['row_idx'], msg, fetched_list)
        self.active_queue.remove(job)
        self.tokens = self.tokens + 1
        self.dispatch()

    def _report_progress(self, job: dict, fetched: int, total: int) -> None:
        self.progress_updated.emit(job['row_idx'], fetched, total)
    
class DownloadWorkerThread(QThread):
    succeeded = Signal(list)
    failed = Signal(str, list)
    progress = Signal(float, float)

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
            try:
                resolved = gog_api.resolve_downlink(self.access_token, file['downlink'])
                cdn_link = resolved['downlink']
                checksum_link = resolved['checksum']
                download_response = requests.get(cdn_link, stream=True)
                download_response.raise_for_status()
                checksum_response = requests.get(checksum_link)
                checksum_response.raise_for_status()
                checksum_xml = ET.fromstring(checksum_response.text)
                checksum = checksum_xml.attrib['md5']
                filename = urllib.parse.urlparse(cdn_link).path.rsplit('/',-1)[-1]
                filename = urllib.parse.unquote(filename)
            except Exception as e:
                self.fetched_list.append((f"{file['file']}: {str(e)}", -1))
                continue
            try:
                part_path: Path = download_path / file['directory'] / (filename+'.part')
                save_path: Path = download_path / file['directory'] / filename
                save_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                self.fetched_list.append((f"{file['file']}: {str(e)}", -1))
                self.failed.emit(str(e), self.fetched_list)
                break
            try:
                content_length = int(cl) if (cl:= download_response.headers.get('Content-Length')) else 0
                self.total_size += (content_length - file['size'])
                file_hash = hashlib.md5()
                with open(part_path, 'wb') as fp:
                    for chunk in download_response.iter_content(chunk_size=1024*1024):
                        bytes_written = fp.write(chunk)
                        self.fetched_size = self.fetched_size + bytes_written
                        file_hash.update(chunk)
                        self.update_progress()
                if file_hash.hexdigest() == checksum:
                    part_path.rename(save_path)
                    self.fetched_list.append((save_path.name, save_path.stat().st_size))
                else:
                    # part_path.unlink()
                    failed_path: Path = download_path / file['directory'] / (filename+'.fail')
                    actual_size = part_path.stat().st_size
                    part_path.rename(failed_path)
                    self.fetched_list.append((save_path.name, -1, file['size'], actual_size))
            except requests.exceptions.RequestException as e:
                self.fetched_list.append((f"{save_path.name}: {str(e)}", -1, file['size'], _safe_size(part_path)))
                continue
            except Exception as e:
                self.fetched_list.append((f"{save_path.name}: {str(e)}", -1, file['size'], _safe_size(part_path)))
                self.failed.emit(str(e), self.fetched_list)
                break
        else:
            for item in self.fetched_list:
                if item[1] > -1:
                    self.succeeded.emit(self.fetched_list)
                    break
            else:
                self.failed.emit("All files failed to download", self.fetched_list)


    def update_progress(self):
        self.progress.emit(self.fetched_size, self.total_size)

def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0
    
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