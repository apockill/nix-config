from pathlib import Path
from typing import List, Union, Optional
from concurrent.futures import ThreadPoolExecutor, Future
from threading import RLock
import os
from time import time, sleep


class NodeStat:
    def __init__(self, size, path: os.DirEntry):
        self.path = path
        self.size = size


class DirectoryStat(NodeStat):
    """Crawl a filesystem in parallel and get statistics about structure and
    size of directories."""

    def __init__(self,
                 path: Union[str, os.DirEntry],
                 executor: Optional[ThreadPoolExecutor] = None,
                 on_stats_change=None):
        super().__init__()
        self.finished = False
        self.path = path
        self._on_stats_change = on_stats_change

        # Statistics
        """This is turned true when all children have finished scanning"""
        self.n_items = 0

        self.executor = executor
        if self.executor is None:
            self.executor = ThreadPoolExecutor(max_workers=1)

        # self._future = Future()
        # self._future.set_result(self._get_children())
        self._future = self.executor.submit(self._get_children)

    def __repr__(self):
        try:
            dir = self.path.path
        except AttributeError:
            dir = str(self.path)
        return f"{self.__class__.__name__}(" \
               f"directory={dir}, " \
               f"n_items={self.n_items}, " \
               f"finished={self.finished})"

    @property
    def children(self) -> List['DirectoryStat']:
        return self._future.result()

    def _get_children(self):
        try:
            scan = os.scandir(self.path)
            entries = list(scan)
        except (PermissionError, FileNotFoundError):
            entries = []

        child_directories = []
        for entry in entries:
            # if entry.is_symlink():
            #     continue

            try:
                self._record_statistics(entry)
            except (PermissionError, FileNotFoundError) as e:
                print(f"Error: {type(e)}")

            if (entry.is_dir()
                    and not os.path.ismount(entry)
                    and not entry.is_symlink()):
                child_directories.append(entry)

        if len(child_directories) == 0:
            self.finished = True

        if self._on_stats_change is not None:
            self._on_stats_change(
                n_items=self.n_items,
                is_child_finished=self.finished)

        # Start jobs for future
        child_dirstats = [DirectoryStat(
            path=dir,
            executor=self.executor,
            on_stats_change=self.add_items) for dir in child_directories]
        return child_dirstats

    def _record_statistics(self, entry: os.DirEntry):
        """Get statistics about a file or directory and record them """
        self.n_items += 1

    def add_items(self, n_items, is_child_finished):
        """Children nodes call this on parent methods so that parents can
        reflect the sum of items that children have found."""

        self.n_items += n_items
        assert not self.finished, \
            "How can a child update a parent if the parent has already been" \
            "marked as 'finished'?"

        # Check if this node is ready to be 'finished' as well
        if is_child_finished:
            self.finished = all(dir.finished for dir in self.children)

        if self._on_stats_change is not None:
            # Optimization: Make sure there re changes that actually need to be
            # passed up the chain
            if n_items > 0 or self.finished:
                self._on_stats_change(
                    n_items=n_items,
                    is_child_finished=self.finished)


if __name__ == "__main__":
    start = time()
    dirstat = DirectoryStat("/")
    print(dirstat)
    while not dirstat.finished:
        sleep(0.001)
    print("Elapsed", time() - start)
    print(dirstat)
