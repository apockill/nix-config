import os
import math
import logging
from threading import Event
from typing import List, Union, Optional
from concurrent.futures import ThreadPoolExecutor, Future
from pathlib import Path


def fmt_bytes(size_bytes):
    """Return a nice 'total_size' string with Gb, Mb, Kb, and Byte ranges"""
    units = ["Bytes", "kB", "MB", "GB"]
    if size_bytes == 0:
        return f"{0} Bytes"
    for unit in units:
        digits = int(math.log10(size_bytes)) + 1
        if digits < 4:
            return f"{round(size_bytes, 1)} {unit}"
        size_bytes /= 1024
    return f"{size_bytes} TB"


class NodeStat:
    path: Path
    size: float
    """Size is in Gigabytes"""

    def __init__(self, path: Union[str, os.DirEntry]):
        if isinstance(path, os.DirEntry):
            self.path = Path(path.path)
            self.size = path.stat().st_size

        elif isinstance(path, str):
            self.path = Path(path)
            self.size = os.stat(path).st_size
        else:
            raise RuntimeError(f"Invalid type for path: {type(path)} {path}")

    def __repr__(self):
        return f"NodeStat(path={self.path}, size={self.size_pretty})"

    @property
    def size_pretty(self) -> str:
        return fmt_bytes(size_bytes=self.size)


class DirectoryStat(NodeStat):
    """Crawl a filesystem in parallel and get statistics about structure and
    size of directories."""

    def __init__(self,
                 path: Union[str, os.DirEntry],
                 executor: Optional[ThreadPoolExecutor] = None,
                 on_stats_change=None,
                 parent: 'DirectoryStat' = None):
        super().__init__(path=path)
        self.finished: Event = Event()
        self.parent = parent
        self._on_stats_change = on_stats_change

        # Statistics
        """This is turned true when all children have finished scanning"""
        self.total_items = 0
        self.total_size = 0

        self.executor = executor
        if self.executor is None:
            self.executor = ThreadPoolExecutor(max_workers=1)

        self._future = self.executor.submit(self._get_children)

    def __repr__(self):
        return f"{self.__class__.__name__}(" \
               f"directory='{str(self.path)}', " \
               f"total_items={self.total_items}, " \
               f"total_size={self.total_size_pretty}, " \
               f"finished={self.finished.is_set()})"

    def __iter__(self):
        for child in self.children:
            yield child

    @property
    def children(self) -> List['DirectoryStat']:
        dirs, files = self._future.result()
        return dirs + files

    @property
    def directories(self) -> List['DirectoryStat']:
        dirs, _ = self._future.result()
        return dirs

    @property
    def files(self) -> List['NodeStat']:
        _, files = self._future.result()
        return files

    @property
    def total_size_pretty(self):
        return fmt_bytes(size_bytes=self.total_size)

    def _get_children(self):
        try:
            try:
                scan = os.scandir(self.path)
                entries = list(scan)
            except (PermissionError, FileNotFoundError):
                entries = []

            child_directories = []
            child_files = []

            for entry in entries:
                try:
                    self._record_statistics(entry)
                    if not entry.is_symlink():
                        if entry.is_dir() and not os.path.ismount(entry):
                            child_directories.append(entry)
                        else:
                            child_files.append(entry)

                except (PermissionError, FileNotFoundError) as e:
                    logging.warning(
                        f"Error scanning file {entry.path}: {type(e)}")
                except Exception as e:
                    logging.critical("Unexpected error scanning file "
                                     f"{entry.path}: {type(e)} {e}")
            if len(child_directories) == 0:
                self.finished.set()

            # Start jobs for future
            child_dirstats = [DirectoryStat(
                path=entry,
                executor=self.executor,
                parent=self,
                on_stats_change=self.add_items) for entry in child_directories]

            # Get information about child folders
            child_files = [NodeStat(path=entry) for entry in child_files]
            for node in child_files + child_dirstats:
                self.total_size += node.size

            if self._on_stats_change is not None:
                self._on_stats_change(self)

            return child_dirstats, child_files
        except Exception as e:
            print(e, type(e))

    def _record_statistics(self, entry: os.DirEntry):
        """Get statistics about a file or directory and record them """
        self.total_items += 1

    def add_items(self, changed_dirstat: 'DirectoryStat'):
        """Children nodes call this on parent methods so that parents can
        reflect the sum of items that children have found."""

        self.total_items += changed_dirstat.total_items
        self.total_size += changed_dirstat.total_size
        assert not self.finished.is_set(), \
            "How can a child update a parent if the parent has already been" \
            "marked as 'finished'?"

        # Check if this node is ready to be 'finished' as well
        if (changed_dirstat.finished.is_set()
                and all(dir.finished.is_set() for dir in self.directories)):
            self.finished.set()

        if self._on_stats_change is not None:
            # Optimization: Make sure there re changes that actually need to be
            # passed up the chain
            if changed_dirstat.total_items > 0 or self.finished.is_set():
                self._on_stats_change(changed_dirstat)
