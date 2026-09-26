from gogstash import library_db
from gogstash import settings
from gogstash import gog_api
from gogstash import manifest
from gogstash import paths
import humanize
from pathlib import Path

import urllib
import requests
import hashlib
import xml.etree.ElementTree as ET
import time

from PySide6.QtCore import (
    QThread,
    QObject,
    Signal
)
class DownloadScheduler(QObject):
    game_succeeded = Signal(int)
    game_started = Signal(int)
    game_failed = Signal(int, str)
    game_stopped = Signal(int)
    game_paused = Signal(int)
    progress_updated = Signal(int, float, float)
    finished = Signal()
    stopped = Signal()
    paused = Signal()

    _stopped_flag = False
    _paused_flag = False

    def __init__(self, product_queue: list[dict] | None = None, concurrency: int = 1, parent=None):
        super().__init__(parent)
        if concurrency < 1:
            raise ValueError("Concurrency must be more than 0")
        self.max_tokens = concurrency
        self.tokens = concurrency
        self.idle_queue = []
        self.active_queue = []
        self.paused_queue = []
        if product_queue:
            for product in product_queue:
                queue_item = {
                    'row_idx': product['idx'],
                    'product_id': product['product_id'],
                    'worker': None,
                    'stopped': False,
                    'resume_link': {}
                }
                self.idle_queue.append(queue_item)

    def set_concurrency(self, value):
        if value < 1:
            raise ValueError("Concurrency must be more than 0")
        diff = value - self.max_tokens
        self.tokens += diff
        self.max_tokens = value

    def enqueue(self, product: dict):
        for item in self.idle_queue:
            if item.get('row_idx') == product['idx']:
                return
        queue_item = {
            'row_idx': product['idx'],
            'product_id': product['product_id'],
            'worker': None,
            'stopped': False,
            'resume_link': {}
        }
        self.idle_queue.append(queue_item)
        if self.active_queue:
            self.schedule()

    def stop_all(self):
        _write_log_msg("Downloads stopped")
        self._stopped_flag = True
        self._paused_flag = False
        for job in self.active_queue:
            job['worker'].stop_worker()
        for task in self.idle_queue:
            task['stopped'] = True
        while self.paused_queue:
            job = self.paused_queue.pop()
            self.game_stopped.emit(job['row_idx'])
            part_path : Path = job['resume_link'].get('partpath', None)
            if part_path: part_path.unlink(missing_ok=True)
        self.schedule()
            
    def pause_all(self):
        if self._paused_flag:
            return
        _write_log_msg("Downloads paused")
        self._paused_flag = True
        for job in self.active_queue:
            job['worker'].pause_worker()

    def resume_all(self):
        if not self._paused_flag:
            return
        _write_log_msg("Downloads resumed")
        self._paused_flag = False
        while self.paused_queue:
            self.idle_queue.append(self.paused_queue.pop())
        self.schedule()

    def schedule(self):
        self.idle_queue.sort(key=lambda x: x['row_idx'])
        if self._paused_flag:
            if not self.active_queue:
                self.paused.emit()
            return
        while self.tokens > 0 and self.idle_queue:
            job = self.idle_queue.pop(0)
            if job['stopped']:
                self.game_stopped.emit(job['row_idx'])
            else:
                self._dispatch(job)
        if not self.idle_queue and not self.active_queue:
            if self._stopped_flag:
                self.stopped.emit()
                self._stopped_flag = False
            else:
                self.finished.emit()

    def _dispatch(self, job: dict):
        job['worker'] = DownloadWorkerThread(job['product_id'], job.get('resume_link'))
        job['worker'].succeeded.connect(lambda t=job: self._handle_success(t))
        job['worker'].failed.connect(lambda msg, t=job: self._handle_failure(t, msg))
        job['worker'].progress.connect(lambda fetched_size, total_size, t=job: self._report_progress(t, fetched_size, total_size))
        job['worker'].stopped.connect(lambda t=job: self._handle_stopped(t))
        job['worker'].paused.connect(lambda resume_link, t=job: self._handle_paused(t, resume_link))
        job['worker'].fetched.connect(self._handle_fetched)
        self.active_queue.append(job)
        self.tokens = self.tokens - 1
        job['worker'].start()
        self.game_started.emit(job['row_idx'])

    def _reap(self, job: dict):
        if job in self.active_queue:
            self.active_queue.remove(job)
            self.tokens = self.tokens + 1
            job['worker'].wait()
            job['worker'] = None

    def _handle_fetched(self, fetched_file: dict) -> None:
        skipped = fetched_file.get('skipped', False)
        valid = fetched_file.get('size', -1) > -1
        if valid and not skipped:
            manifest.add_file(
                game_dir=fetched_file.get('game_dir'),
                filepath=fetched_file.get('filepath'),
                category=fetched_file.get('category'),
                checksum=fetched_file.get('checksum'),
                timestamp=time.time()
            )
        _write_log_file(fetched_file)

    def _handle_success(self, job: dict) -> None:
        self.game_succeeded.emit(job['row_idx'])
        self._reap(job)
        self.schedule()

    def _handle_stopped(self, job: dict) -> None:
        self.game_stopped.emit(job['row_idx'])
        self._reap(job)
        self.schedule()

    def _handle_paused(self, job: dict, resume_link: dict) -> None:
        self.game_paused.emit(job['row_idx'])
        if job in self.active_queue:
            paused_job = job.copy()
            paused_job['resume_link'] = resume_link
            self.paused_queue.append(paused_job)
        self._reap(job)
        self.schedule()

    def _handle_failure(self, job: dict, msg: str) -> None:
        self.game_failed.emit(job['row_idx'], msg)
        self._reap(job)
        self.schedule()

    def _report_progress(self, job: dict, fetched: int, total: int) -> None:
        self.progress_updated.emit(job['row_idx'], fetched, total)
    
class DownloadWorkerThread(QThread):
    succeeded = Signal()
    failed = Signal(str)
    progress = Signal(float, float)
    stopped = Signal()
    paused = Signal(dict)
    fetched = Signal(dict)

    _stop_flag = False
    _pause_flag = False
    _failed_flag = False

    def __init__(self, product_id: int, resume_link: dict | None = None, parent=None):
        super().__init__(parent)
        self.resume_link = resume_link.get('downlink', "") if resume_link else ""
        self.product_id = product_id
        self.file_queue = None
        self.total_size = 0
        self.fetched_size = 0

    def run(self):
        try:
            self.file_queue = generate_download_list((self.product_id,))
            if not self.file_queue:
                self.failed.emit("No files to download")
                return
            slug = library_db.get_product_listing((self.product_id,))[0]['slug']
            download_path: Path = Path(settings.read_setting('download_path')) / slug
        except Exception as e:
            self.failed.emit(str(e))
            return
        self.total_size = self.total_size + sum(file['size'] for file in self.file_queue)
        for file in self.file_queue:
            try:
                resolved = gog_api.resolve_downlink(file['downlink'])
                cdn_link = resolved['downlink']
                checksum = ""
                if file['directory'] != 'bonus_content':
                    checksum_link = resolved['checksum']
                    checksum_response = requests.get(checksum_link)
                    checksum_response.raise_for_status()
                    checksum_xml = ET.fromstring(checksum_response.text)
                    checksum = checksum_xml.attrib['md5']
                filename = urllib.parse.urlparse(cdn_link).path.rsplit('/',-1)[-1]
                filename = urllib.parse.unquote(filename)
            except PermissionError as e:
                self.failed.emit(str(e))
                return
            except Exception as e:
                self.fetched.emit({
                    'game_dir': download_path,
                    'filepath': Path(file['file']), 
                    'category': file['category'],
                    'size': -1,
                    'checksum': "",
                    'error': str(e)
                })
                self._failed_flag = True
                continue
            try:
                part_path: Path = download_path / file['directory'] / (filename+'.part')
                save_path: Path = download_path / file['directory'] / filename
                save_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                self.fetched.emit({
                    'game_dir': download_path,
                    'filepath': Path(file['file']),
                    'category': file['category'], 
                    'size': -1,
                    'checksum': "",
                    'error': str(e)
                })
                self.failed.emit(str(e))
                break
            try:
                header_params = {}
                file_hash = hashlib.md5()
                fetched_bytes = 0
                if self.resume_link == file['downlink']:
                    with open(part_path, 'rb') as fp:
                        while True:
                            chunk = fp.read(1024*1024)
                            if not chunk:
                                break
                            file_hash.update(chunk)
                        fetched_bytes = part_path.stat().st_size
                        header_params['Range'] = f"bytes={fetched_bytes}-"
                        self.fetched_size += fetched_bytes
                        self.resume_link = ""
                download_response = requests.get(cdn_link, headers=header_params, stream=True)
                download_response.raise_for_status()
                if download_response.status_code == 206:
                    content_range = download_response.headers.get('Content-Range')
                    if content_range:
                        content_length = int(content_range.split('/')[-1])
                    else:
                        content_length = int(cl) if (cl:= download_response.headers.get('Content-Length')) else 0
                        content_length += fetched_bytes
                else:
                    content_length = int(cl) if (cl:= download_response.headers.get('Content-Length')) else 0
                existing_metadata = manifest.check_exist(download_path, save_path, content_length)                
                if existing_metadata:
                    if (
                        (existing_metadata['category'] != 'bonus_content' and checksum == existing_metadata['checksum']) or
                        (existing_metadata['category'] == 'bonus_content' and content_length == existing_metadata['size'])
                       ):
                        self.fetched.emit({
                            'game_dir': download_path,
                            'filepath': save_path,
                            'category': file['category'],
                            'size': existing_metadata['size'],
                            'checksum': existing_metadata['checksum'],
                            'skipped': True
                        })
                        self.fetched_size = self.fetched_size + existing_metadata['size']
                        self.update_progress()
                        continue
                self.total_size += (content_length - file['size'])

                if download_response.status_code == 206:
                    file_mode = 'ab'
                else:
                    file_mode = 'wb'
                    self.fetched_size -= fetched_bytes
                    file_hash = hashlib.md5()
                with open(part_path, file_mode) as fp:
                    cleanup = False
                    for chunk in download_response.iter_content(chunk_size=1024*1024):
                        bytes_written = fp.write(chunk)
                        current_size = fp.tell()
                        self.fetched_size += bytes_written
                        if file['directory'] != 'bonus_content':
                            file_hash.update(chunk)
                        self.update_progress()
                        if current_size < content_length or content_length == 0:
                            if self._stop_flag:
                                cleanup = True
                                break
                            if self._pause_flag:
                                self.paused.emit({
                                    'partpath': part_path,
                                    'downlink': file['downlink']
                                })
                                return
                if self._stop_flag and cleanup:
                    part_path.unlink()  
                    self.stopped.emit()
                    return
                verified = False
                if file['directory'] == 'bonus_content':
                    if part_path.stat().st_size == content_length:
                        verified = True
                else:
                    if file_hash.hexdigest() == checksum:
                        verified = True
                if verified:
                    part_path.rename(save_path)
                    self.fetched.emit({
                        'game_dir': download_path,
                        'filepath': save_path,
                        'category': file['category'],
                        'size': save_path.stat().st_size,
                        'checksum': checksum
                    })
                else:
                    actual_size = part_path.stat().st_size
                    part_path.unlink()
                    self.fetched.emit({
                        'game_dir': download_path,
                        'filepath': save_path,
                        'category': file['category'],
                        'size': -1, 
                        'checksum': "",
                        'error': f"Checksum mismatch | Expected size: {file['size']} | Got size: {actual_size}"
                    })
                    self._failed_flag = True
                if self._stop_flag:
                    self.stopped.emit()
                    return
                if self._pause_flag:
                    self.paused.emit({})
                    return
            except requests.exceptions.RequestException as e:
                self.fetched.emit({
                    'game_dir': download_path,
                    'filepath': save_path,
                    'category': file['category'],
                    'size': -1,
                    'checksum': "",
                    'error': f"{str(e)} | Expected size: {file['size']} | Got size: {_safe_size(part_path)}"
                })
                self._failed_flag = True
                continue
            except Exception as e:
                self.fetched.emit({
                    'game_dir': download_path,
                    'filepath': save_path,
                    'category': file['category'],
                    'size': -1,
                    'checksum': "",
                    'error': f"{str(e)} | Expected size: {file['size']} | Got size: {_safe_size(part_path)}"
                })
                self.failed.emit(str(e))
                break
        else:
            if not self._failed_flag:
                self.succeeded.emit()
            else:
                self.failed.emit("All files failed to download")

    def stop_worker(self):
        self._stop_flag = True

    def pause_worker(self):
        self._pause_flag = True

    def update_progress(self):
        self.progress.emit(self.fetched_size, self.total_size)

def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0

def _write_log_file(fetched_file: dict) -> None:
    if not fetched_file:
        return
    log_file = paths.config_file_path(paths.ConfigFile.DOWNLOAD_LOG)
    error_msg = fetched_file.get('error', "")
    skipped = fetched_file.get('skipped', False)
    log_time = time.strftime("%Y-%m-%dT%H:%M:%S")
    filepath = str(fetched_file.get('filepath', ""))
    checksum = fetched_file.get('checksum', "")
    if error_msg:
        log_entry = f"[{log_time}] | {filepath} : {error_msg}"
    elif skipped:
        log_entry = f"[{log_time}] | {filepath} : Skipped | Already up to date"
    else:
        log_entry = f"[{log_time}] | {filepath} : Fetched {humanize.naturalsize(fetched_file.get('size',""))}"
        if checksum:
            log_entry += f" | md5: {checksum}"
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, 'a') as wp:
            wp.write(log_entry + "\n")
    except Exception as e:
        print(f"Logging error: {e}\n {log_entry}")

def _write_log_msg(message: str = "") -> None:
    if not message:
        return
    log_file = paths.config_file_path(paths.ConfigFile.DOWNLOAD_LOG)
    log_entry = f"[{time.strftime("%Y-%m-%dT%H:%M:%S")}] : {message}\n"
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, 'a') as wp:
            wp.write(log_entry)
    except Exception as e:
        print(f"Logging error: {e}\n {log_entry}")
    
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
            'category': item['category'],
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