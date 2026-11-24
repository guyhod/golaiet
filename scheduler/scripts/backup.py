"""The nightly dump: one file a night in the backup folder, thirty days kept.

Its files carry a prefix of their own, and only files of that prefix are
ever removed, and only once tonight's is in place: a night whose dump failed
removes nothing, and a dump taken by hand or by a deploy stays until a
person removes it. With an old dump goes the small file of counts beside it.
A half file that a killed run left, of this job or of a dump by hand, is
removed the night after. A dump that fails raises, so the run is recorded as
failed and the failure notice reaches Telegram."""
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from core import backup

KEEP = timedelta(days=30)
HALF_FILE_KEEP = timedelta(days=1)


def run(job, run) -> dict:
    if not settings.BACKUP_DIR:
        raise RuntimeError("BACKUP_DIR is not set: there is no folder to write the dump to")
    folder = Path(settings.BACKUP_DIR)
    made = backup.dump(folder, f"{backup.NIGHTLY}{timezone.localdate():%Y-%m-%d}.dump")
    now = time.time()
    removed = 0
    for earlier in folder.glob(f"{backup.NIGHTLY}*.dump"):
        if earlier != made.path and earlier.stat().st_mtime < now - KEEP.total_seconds():
            earlier.unlink()
            backup.beside(earlier).unlink(missing_ok=True)
            removed += 1
    for prefix in (backup.NIGHTLY, backup.BY_HAND):
        for half in folder.glob(f"{prefix}*{backup.PARTIAL}"):
            if half.stat().st_mtime < now - HALF_FILE_KEEP.total_seconds():
                half.unlink()
    return {"summary": f"{made.path.name} · {made.size} bytes · {removed} older than {KEEP.days} days removed"}
