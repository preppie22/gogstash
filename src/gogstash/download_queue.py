"""Download scheduling and per-game download workers.

``DownloadScheduler`` owns the job queues, the concurrency limit, the
free space check, manifest updates and the download log. Each game is
downloaded by its own ``DownloadWorkerThread``.
"""

from gogstash import library_db
from gogstash import settings
from gogstash import gog_api
from gogstash import manifest
from gogstash import paths

import humanize
from pathlib import Path
import shutil
import errno

import urllib
import requests
import hashlib
import xml.etree.ElementTree as ET
import time
from typing import NamedTuple

from PySide6.QtCore import (
    QThread,
    QObject,
    Signal
)

class FreeCheckReturn(NamedTuple):
    """Result of the scheduler's free space check.

    Attributes:
        is_available (bool): The remaining downloads fit on the disk.
        required (float): Bytes still to be downloaded, in bytes.
        free (float): Free space in the download directory, in bytes.
            0 if the directory could not be created.
    """
    is_available: bool
    required: float
    free: float

class DownloadScheduler(QObject):
    """Runs queued game downloads with a limit on parallel downloads.

    Jobs move between three queues: idle (waiting to start), active (a
    worker is running) and paused (holding resume information for a
    partly downloaded file). Each job carries the row index of its entry
    in the download window, and every per-game signal reports that index.

    Before starting jobs, the scheduler checks that everything still to be
    downloaded fits on the disk, and holds every job back if it does not.

    Attributes:
        game_succeeded (Signal(int)): A game finished downloading.
        game_started (Signal(int)): A game started downloading.
        game_failed (Signal(int, str)): A game failed, with an error
            message.
        game_stopped (Signal(int)): A game was stopped.
        game_paused (Signal(int)): A game was paused.
        progress_updated (Signal(int, float, float)): Bytes fetched and
            total bytes for a game.
        finished (Signal): All jobs have completed.
        stopped (Signal): All jobs have stopped after ``stop_all``.
        paused (Signal): All active jobs have paused after ``pause_all``.
        low_disk_space (Signal(float, float)): The remaining downloads do
            not fit on the disk, with the bytes required and the bytes
            free. Emitted on every scheduling attempt until they fit.
        disk_full (Signal): A download ran out of disk space and all
            downloads are being paused. Emitted once per pause, before
            ``paused``.
    """
    game_succeeded = Signal(int)
    game_started = Signal(int)
    game_failed = Signal(int, str)
    game_stopped = Signal(int)
    game_paused = Signal(int)
    progress_updated = Signal(int, float, float)
    finished = Signal()
    stopped = Signal()
    paused = Signal()
    low_disk_space = Signal(float, float)
    disk_full = Signal()

    _stopped_flag = False
    _paused_flag = False

    def __init__(self, concurrency: int = 1, parent=None):
        """Create the scheduler.

        Jobs are added with ``enqueue``.

        Args:
            concurrency (int): Maximum number of parallel downloads.
            parent (QObject): Optional parent object.

        Raises:
            ValueError: If ``concurrency`` is less than 1.
        """
        super().__init__(parent)
        if concurrency < 1:
            raise ValueError("Concurrency must be more than 0")
        self.max_tokens = concurrency
        self.tokens = concurrency
        self.idle_queue = []
        self.active_queue = []
        self.paused_queue = []

        self.__free_space_check = True
        self.__unrecorded = []

    @property
    def free_space_check(self):
        """bool: Whether jobs are held back when they do not fit on the disk."""
        return self.__free_space_check

    @free_space_check.setter
    def free_space_check(self, value: bool):
        self.__free_space_check = value

    def set_concurrency(self, value):
        """Change the maximum number of parallel downloads.

        Running jobs are not interrupted. The new limit applies as jobs are
        scheduled.

        Args:
            value (int): The new limit.

        Raises:
            ValueError: If ``value`` is less than 1.
        """
        if value < 1:
            raise ValueError("Concurrency must be more than 0")
        diff = value - self.max_tokens
        self.tokens += diff
        self.max_tokens = value

    def enqueue(self, product: dict) -> int:
        """Add a job to the idle queue.

        The game's download list is built here, without the files that are
        already downloaded. A job for a row that is already waiting is
        ignored. If downloads are running, the scheduler tries to start the
        job right away.

        Args:
            product (dict): Job with ``idx`` (row index) and ``product_id``.

        Returns:
            int: Estimated bytes still to download for the game. 0 if the
            row was already waiting.
        """
        for item in self.idle_queue:
            if item.get('row_idx') == product['idx']:
                return 0
        file_queue = generate_download_list((product['product_id'],))
        queue_item = {
            'row_idx': product['idx'],
            'product_id': product['product_id'],
            'worker': None,
            'file_queue': file_queue,
            'stopped': False,
            'resume_link': {}
        }
        self.idle_queue.append(queue_item)
        download_size = sum(file['size'] for file in file_queue)
        if self.active_queue:
            self.schedule()
        return download_size

    def stop_all(self):
        """Stop all downloads.

        Active workers are asked to stop, waiting jobs are marked as stopped,
        and paused jobs are stopped right away with their partial files
        deleted and empty folders removed. Emits ``stopped`` once nothing
        is left running.
        """
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
            if part_path: 
                _discard_partial_downloads(part_path.parent.parent)
        self.schedule()
            
    def pause_all(self):
        """Ask all active workers to pause.

        No new jobs start while paused. Emits ``paused`` once the last active
        job has paused, or right away if no jobs are active.
        """
        if self._paused_flag:
            return
        _write_log_msg("Downloads paused")
        self._paused_flag = True
        for job in self.active_queue:
            job['worker'].pause_worker()
        self.schedule()

    def resume_all(self):
        """Move paused jobs back to the idle queue and resume scheduling.

        Files that could not be recorded in the manifest while the disk was
        full get another try first, so resumed jobs skip them instead of
        downloading them again.
        """
        if not self._paused_flag:
            return
        _write_log_msg("Downloads resumed")
        self._retry_unrecorded()
        self._paused_flag = False
        while self.paused_queue:
            self.idle_queue.append(self.paused_queue.pop())
        self.schedule()

    def _free_check(self) -> FreeCheckReturn:
        """Check whether the remaining downloads fit on the disk.

        Counts every waiting job that is not stopped, plus the bytes that
        active jobs have not downloaded yet. Waiting jobs that were paused
        count only the bytes they had left, not their whole download list
        again. 2% of the free space is kept
        in reserve. Nothing left to download always fits, without looking
        at the disk. Otherwise the download directory is created if it does
        not exist.

        Returns:
            FreeCheckReturn: Whether the downloads fit, the bytes required
            and the bytes free. The bytes free are 0 when there is nothing
            to download.
        """
        dl_size = 0
        for job in self.idle_queue:
            if job['stopped']:
                continue
            remaining_size = job.get('remaining_size')
            if remaining_size is not None:
                dl_size += max(remaining_size, 0)
            else:
                for item in (job.get('file_queue') or []):
                    dl_size += item['size']
        for job in self.active_queue:
            remaining_size = max(job['worker'].total_size - job['worker'].fetched_size, 0)
            dl_size += remaining_size
        if dl_size == 0:
            return FreeCheckReturn(True, 0, 0)
        dl_path = Path(settings.read_setting('download_path'))
        try:
            dl_path.mkdir(parents=True, exist_ok=True)
        except OSError:
            return FreeCheckReturn(False, dl_size, 0)
        free_space = shutil.disk_usage(dl_path).free
        if dl_size < free_space * 0.98:
            return FreeCheckReturn(True, dl_size, free_space)
        return FreeCheckReturn(False, dl_size, free_space)


    def schedule(self):
        """Start waiting jobs while the concurrency limit allows.

        Jobs start in row order. Jobs marked as stopped are reported through
        ``game_stopped`` instead of starting, and jobs with nothing left to
        download are reported through ``game_succeeded`` without a worker.
        If the free space check is on and the remaining downloads do not
        fit, emits ``low_disk_space`` and starts nothing. Emits
        ``finished``, ``stopped`` or ``paused`` when there is nothing left
        to run.
        """
        self.idle_queue.sort(key=lambda x: x['row_idx'])
        if self._paused_flag:
            if not self.active_queue:
                self.paused.emit()
            return
        if self.free_space_check and not self._stopped_flag:
            space_check = self._free_check()
            if not space_check.is_available:
                self.low_disk_space.emit(space_check.required, space_check.free)
                return        
        while self.tokens > 0 and self.idle_queue:
            job = self.idle_queue.pop(0)
            if job['stopped']:
                self.game_stopped.emit(job['row_idx'])
            elif not job.get('file_queue'):
                self.game_succeeded.emit(job['row_idx'])
            else:
                self._dispatch(job)
        if not self.idle_queue and not self.active_queue:
            if self._stopped_flag:
                self.stopped.emit()
                self._stopped_flag = False
            else:
                self.finished.emit()

    def _dispatch(self, job: dict):
        """Start a worker for a job and move the job to the active queue.

        Args:
            job (dict): The job to start.
        """
        job['worker'] = DownloadWorkerThread(job['product_id'], job.get('file_queue'), job.get('resume_link'))
        job['worker'].succeeded.connect(lambda t=job: self._handle_success(t))
        job['worker'].failed.connect(lambda msg, t=job: self._handle_failure(t, msg))
        job['worker'].progress.connect(lambda fetched_size, total_size, t=job: self._report_progress(t, fetched_size, total_size))
        job['worker'].stopped.connect(lambda t=job: self._handle_stopped(t))
        job['worker'].paused.connect(lambda resume_link, t=job: self._handle_paused(t, resume_link))
        job['worker'].fetched.connect(self._handle_fetched)
        job['worker'].disk_full.connect(lambda resume_link, t=job: self._handle_disk_full(t, resume_link))
        self.active_queue.append(job)
        self.tokens = self.tokens - 1
        job['worker'].start()
        self.game_started.emit(job['row_idx'])

    def _reap(self, job: dict):
        """Remove a job from the active queue and free its concurrency slot.

        Waits for the job's worker thread to exit.

        Args:
            job (dict): The job to remove.
        """
        if job in self.active_queue:
            self.active_queue.remove(job)
            self.tokens = self.tokens + 1
            job['worker'].wait()
            job['worker'] = None

    def _record_downloaded(self, fetched_file) -> bool | None:
        """Record a downloaded file in its game's manifest.

        The downloaded file itself is never touched, whatever happens to
        the manifest.

        Args:
            fetched_file (dict): File result from a worker's ``fetched``
                signal.

        Returns:
            bool | None: True if the file was recorded. False if the disk
            is full, so recording can be tried again later. None if
            recording failed for another reason, which is logged, and is
            not worth trying again.
        """
        try:
            manifest.add_file(
                game_dir=fetched_file.get('game_dir'),
                filepath=fetched_file.get('filepath'),
                category=fetched_file.get('category'),
                downlink=fetched_file.get('downlink'),
                db_size=fetched_file.get('db_size', -1),
                checksum=fetched_file.get('checksum'),
                timestamp=time.time()
            )
        except Exception as e:
            if isinstance(e, OSError) and (e.errno == errno.ENOSPC or e.errno == errno.EDQUOT):
                return False
            _write_log_msg(f"Error recording file {fetched_file.get('filepath')}: {e}")
            return
        return True
            
    def _retry_unrecorded(self) -> None:
        """Try again to record the files that did not fit in the manifest.

        Files that still do not fit keep waiting, and how many are left is
        logged. Files that fail for any other reason are given up on.
        """
        if not self.__unrecorded:
            return
        errors = []
        for file_data in self.__unrecorded:
            result = self._record_downloaded(file_data)
            if result is False:
                errors.append(file_data)
        if len(errors) == 1:
            _write_log_msg("1 downloaded file still waiting to be recorded")
        elif len(errors) > 1:
            _write_log_msg(f"{len(errors)} downloaded files still waiting to be recorded")
        self.__unrecorded = errors

    def _handle_fetched(self, fetched_file: dict) -> None:
        """Record a file result in the manifest and the download log.

        Downloaded files are always recorded. Skipped files update their
        existing entry, which fills in the downlink and listed size of
        entries recorded by older versions. Failed files are only logged.
        Every file is logged once, when it arrives. A file that cannot be
        recorded because the disk is full waits in a list and is retried
        with every later file and on resume. Files still waiting are
        retried first.

        Args:
            fetched_file (dict): File result from a worker's ``fetched``
                signal.
        """
        self._retry_unrecorded()
        skipped = fetched_file.get('skipped', False)
        valid = fetched_file.get('size', -1) > -1
        if valid:
            file_stats = manifest.stat_file(fetched_file.get('game_dir'), fetched_file.get('filepath'))
            if not skipped or file_stats:
                result = self._record_downloaded(fetched_file)
                if result is False:
                    self.__unrecorded.append(fetched_file)
        _write_log_file(fetched_file)

    def _handle_success(self, job: dict) -> None:
        """Report a finished game and schedule the next job.

        Args:
            job (dict): The finished job.
        """
        self.game_succeeded.emit(job['row_idx'])
        self._reap(job)
        self.schedule()

    def _handle_stopped(self, job: dict) -> None:
        """Report a stopped game and schedule the next job.

        Args:
            job (dict): The stopped job.
        """
        self.game_stopped.emit(job['row_idx'])
        self._reap(job)
        self.schedule()

    def _handle_paused(self, job: dict, resume_link: dict) -> None:
        """Move a paused job to the paused queue.

        Args:
            job (dict): The paused job.
            resume_link (dict): Resume information from the worker, with
                ``partpath`` and ``downlink`` of the partial file. Empty if
                the worker paused between files.
        """
        self.game_paused.emit(job['row_idx'])
        if job in self.active_queue:
            paused_job = job.copy()
            paused_job['resume_link'] = resume_link
            paused_job['remaining_size'] = job['worker'].total_size - job['worker'].fetched_size
            self.paused_queue.append(paused_job)
        self._reap(job)
        self.schedule()

    def _handle_disk_full(self, job: dict, resume_link: dict) -> None:
        """Pause all downloads after a worker ran out of disk space.

        The job goes to the paused queue with its resume information, so
        it continues from its ``.part`` file once there is space again.
        Every other active job is asked to pause and no new jobs start.
        Emits ``disk_full`` if this starts the pause. Workers that run out
        of space while a pause is already underway just join it. If a stop
        was already in progress, the job is reported as stopped and its
        partial downloads are discarded instead.

        Args:
            job (dict): The job whose worker ran out of space.
            resume_link (dict): Resume information from the worker, with
                ``partpath`` and ``downlink`` of the partial file.
        """
        if self._stopped_flag:
            _write_log_msg("Download folder ran out of space while stopping")
            if job in self.active_queue:
                self.game_stopped.emit(job['row_idx'])
                part_path : Path = resume_link.get('partpath', None)
                if part_path: 
                    _discard_partial_downloads(part_path.parent.parent)
        else:
            _write_log_msg("Download folder full: downloads paused")
            if not self._paused_flag:
                self.pause_all()
                self.disk_full.emit()
            self.game_paused.emit(job['row_idx'])
            if job in self.active_queue:
                paused_job = job.copy()
                paused_job['resume_link'] = resume_link
                paused_job['remaining_size'] = job['worker'].total_size - job['worker'].fetched_size
                self.paused_queue.append(paused_job)
        self._reap(job)
        self.schedule()

    def _handle_failure(self, job: dict, msg: str) -> None:
        """Report a failed game and schedule the next job.

        Args:
            job (dict): The failed job.
            msg (str): The error message.
        """
        self.game_failed.emit(job['row_idx'], msg)
        self._reap(job)
        self.schedule()

    def _report_progress(self, job: dict, fetched: int, total: int) -> None:
        """Forward a worker's progress with the job's row index.

        Args:
            job (dict): The job reporting progress.
            fetched (int): Bytes downloaded so far.
            total (int): Total bytes for the game.
        """
        self.progress_updated.emit(job['row_idx'], fetched, total)
    
class DownloadWorkerThread(QThread):
    """Downloads all files for one game.

    Each file is resolved to a CDN link, streamed to a ``.part`` file,
    verified against its md5 checksum (or its size, for bonus content)
    and then renamed into place. Files already recorded in the manifest
    are skipped. A paused file is resumed from its ``.part`` file with an
    HTTP range request. Running out of disk space mid-file keeps the
    ``.part`` file so the download can be resumed the same way.

    Attributes:
        succeeded (Signal): All files were downloaded or skipped.
        failed (Signal(str)): The game could not be fully downloaded.
        progress (Signal(float, float)): Bytes fetched and total bytes.
        stopped (Signal): The worker stopped after ``stop_worker``.
        paused (Signal(dict)): The worker paused, with resume information.
        fetched (Signal(dict)): A file was downloaded, skipped or failed.
        disk_full (Signal(dict)): The disk filled up while writing a file.
            Carries the same resume information as ``paused``.
        resume_link (str): Downlink of the file to resume, if any.
        product_id (int): GOG product ID of the game.
        file_queue (list[dict]): Files to download, from
            ``generate_download_list``.
        total_size (int): Total bytes to download. Known from the moment
            the worker is created, and corrected as the real file sizes
            arrive.
        fetched_size (int): Bytes downloaded so far.
    """
    succeeded = Signal()
    failed = Signal(str)
    progress = Signal(float, float)
    stopped = Signal()
    paused = Signal(dict)
    fetched = Signal(dict)
    disk_full = Signal(dict)

    _stop_flag = False
    _pause_flag = False
    _failed_flag = False

    def __init__(self, product_id: int, file_queue: list[dict] | None = None, resume_link: dict | None = None, parent=None):
        """Create the worker.

        Args:
            product_id (int): GOG product ID of the game.
            file_queue (list[dict] | None): Files to download, from
                ``generate_download_list``.
            resume_link (dict | None): Resume information from an earlier
                pause, with the ``downlink`` of the file to resume.
            parent (QObject): Optional parent object.
        """
        super().__init__(parent)
        self.resume_link = resume_link.get('downlink', "") if resume_link else ""
        self.product_id = product_id
        self.file_queue = file_queue or []
        self.__total_size = sum(file.get('size', 0) for file in self.file_queue)
        self.__fetched_size = 0

    @property
    def total_size(self):
        """int: Total bytes to download."""
        return self.__total_size

    @property
    def fetched_size(self):
        """int: Bytes downloaded so far."""
        return self.__fetched_size

    def run(self):
        """Download every file in the game's download list.

        Stop and pause requests are checked after each chunk. A failure on a
        single file is reported through ``fetched`` and the worker moves on
        to the next file. Errors that affect the whole game, such as a login
        failure or an unwritable directory, end the run with ``failed``.
        Running out of disk space ends the run with ``disk_full`` instead,
        keeping the ``.part`` file.
        """
        try:
            if not self.file_queue:
                self.failed.emit("No files to download")
                return
            slug = library_db.get_product_listing((self.product_id,))[0]['slug']
            download_path: Path = Path(settings.read_setting('download_path')) / slug
        except Exception as e:
            self.failed.emit(str(e))
            return
        
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
                    'downlink': file['downlink'],
                    'size': -1,
                    'db_size': file['size'],
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
                    'downlink': file['downlink'], 
                    'size': -1,
                    'db_size': file['size'],
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
                    try:
                        with open(part_path, 'rb') as fp:
                            while True:
                                chunk = fp.read(1024*1024)
                                if not chunk:
                                    break
                                file_hash.update(chunk)
                            fetched_bytes = part_path.stat().st_size
                            header_params['Range'] = f"bytes={fetched_bytes}-"
                            self.__fetched_size += fetched_bytes
                    except FileNotFoundError:
                        pass
                    self.resume_link = ""
                # download_response = requests.get(cdn_link, headers=header_params, stream=True)
                with requests.get(cdn_link, headers=header_params, stream=True) as download_response:
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
                                'category': existing_metadata.get('category', ""),
                                'downlink': file['downlink'],
                                'size': existing_metadata.get('size', -1),
                                'db_size': file['size'],
                                'checksum': existing_metadata.get('checksum', ""),
                                'skipped': True
                            })
                            self.__fetched_size = self.__fetched_size + existing_metadata['size']
                            self.update_progress()
                            continue
                    self.__total_size += (content_length - file['size'])

                    if download_response.status_code == 206:
                        file_mode = 'ab'
                    else:
                        file_mode = 'wb'
                        self.__fetched_size -= fetched_bytes
                        file_hash = hashlib.md5()
                    try:
                        with open(part_path, file_mode) as fp:
                            cleanup = False
                            for chunk in download_response.iter_content(chunk_size=1024*1024):
                                bytes_written = fp.write(chunk)
                                current_size = fp.tell()
                                self.__fetched_size += bytes_written
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
                    except OSError as e:
                        if e.errno == errno.ENOSPC or e.errno == errno.EDQUOT:
                            self.disk_full.emit({
                                'partpath': part_path,
                                'downlink': file['downlink']                                
                            })
                            return
                        raise

                if self._stop_flag and cleanup:
                    _discard_partial_downloads(download_path)
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
                    part_path.replace(save_path)
                    self.fetched.emit({
                        'game_dir': download_path,
                        'filepath': save_path,
                        'category': file['category'],
                        'downlink': file['downlink'],
                        'size': save_path.stat().st_size,
                        'db_size': file['size'],
                        'checksum': checksum
                    })
                else:
                    actual_size = part_path.stat().st_size
                    part_path.unlink()
                    self.fetched.emit({
                        'game_dir': download_path,
                        'filepath': save_path,
                        'category': file['category'],
                        'downlink': file['downlink'],
                        'size': -1,
                        'db_size': file['size'],
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
                    'downlink': file['downlink'],
                    'size': -1,
                    'db_size': file['size'],
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
                    'downlink': file['downlink'],
                    'size': -1,
                    'db_size': file['size'],
                    'checksum': "",
                    'error': f"{str(e)} | Expected size: {file['size']} | Got size: {_safe_size(part_path)}"
                })
                self.failed.emit(str(e))
                break
        else:
            if not self._failed_flag:
                self.succeeded.emit()
            else:
                self.failed.emit("Downloads completed with failures")

    def stop_worker(self):
        """Ask the worker to stop, delete the partial file and remove empty folders."""
        self._stop_flag = True

    def pause_worker(self):
        """Ask the worker to pause and keep the partial file."""
        self._pause_flag = True

    def update_progress(self):
        """Emit the current progress."""
        self.progress.emit(self.__fetched_size, self.__total_size)

def _safe_size(path: Path) -> int:
    """Return a file's size, or 0 if it cannot be read.

    Args:
        path (Path): The file to check.

    Returns:
        int: Size in bytes.
    """
    try:
        return path.stat().st_size
    except OSError:
        return 0

def _write_log_file(fetched_file: dict) -> None:
    """Append a file result to the download log.

    Args:
        fetched_file (dict): File result from a worker's ``fetched``
            signal.
    """
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
    """Append a timestamped message to the download log.

    Args:
        message (str): The message to log. Empty messages are ignored.
    """
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

def _discard_partial_downloads(game_dir: Path) -> None:
    """Tidy up a game's download directory after a download is stopped.

    Deletes leftover ``.part`` files and removes every directory that ends
    up empty, including ``game_dir`` itself. Finished files and the
    manifest are never touched. Best effort: files or directories that
    cannot be removed are left as they are.

    Args:
        game_dir (Path): The game's download directory.
    """
    for root, dirs, files in game_dir.walk(top_down=False):
        for file in files:
            if file.endswith('.part'):
                try:
                    (root / file).unlink(missing_ok=True)
                except OSError:
                    continue
        try:
            root.rmdir()
        except OSError:
            continue

def generate_download_list(product_ids: tuple[int]) -> list[dict] | None:
    """Build the list of files to download under the current settings.

    Installers are always included. Patches and bonus content are
    included when enabled in settings. Files for platforms outside the
    platform filter are skipped. Files with no OS are kept.

    Installers and patches are also filtered by the ``languages``
    setting, separately for each OS. If a game has no installer in any
    of the chosen languages for an OS, that OS falls back to English.
    Files with no language, such as bonus content, are kept.

    Files already downloaded are left out: those whose manifest entry has
    the same downlink and listed size, and whose file is still on disk
    at its recorded size. Each game's manifest is read once.

    Args:
        product_ids (tuple[int]): GOG product IDs.

    Returns:
        list[dict]: Files with ``directory`` (subfolder in the game
        directory), ``category``, ``file``, ``os``, ``size`` and
        ``downlink``. None if ``product_ids`` is empty.
    """
    if not product_ids:
        return
    downloadables = library_db.get_downloadables(product_ids, filtered=True)
    products = library_db.get_product_listing(product_ids)
    slugs = {p['product_id']: p['slug'] for p in products}
    manifest_cache = {}
    game_dirs = {}
    for pid in product_ids:
        game_dirs[pid] = Path(settings.read_setting('download_path')) / slugs[pid]
        manifest_cache[pid] = manifest.read_manifest(game_dirs[pid])

    download_list = []
    for item in downloadables:
        if manifest.check_exist_by_downlink(game_dirs[item['product_id']], item['downlink'], item['file_size'], manifest_cache[item['product_id']]):
            continue
        download_list.append ({
                'directory': item['group_id'] if item['category'] == 'installers' else item['category'],
                'category': item['category'],
                'file': item['file_id'],
                'os': item['os'],
                'size': item['file_size'],
                'downlink': item['downlink'],
        })
    return download_list

if __name__ == "__main__":
    file_list = generate_download_list((1929434313,))
    for item in file_list:
        print(item)