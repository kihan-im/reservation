"""로컬 실행 간 중복 저장 방지. 서버의 예약 목록이 최종 기준이다."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from contextlib import contextmanager

KST = timezone(timedelta(hours=9))


def now_kst():
    return datetime.now(KST)


class ReservationState:
    def __init__(self, log_dir):
        self.path = Path(log_dir) / "reservation_state.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS slots (slot TEXT PRIMARY KEY, status TEXT, detail TEXT)")

    def connect(self):
        return closing_connection(self.path)

    @staticmethod
    def key(account, day, hour):
        return json.dumps([account, day, "1", hour], ensure_ascii=False)

    def get(self, key):
        with self.connect() as db:
            row = db.execute("SELECT status, detail FROM slots WHERE slot=?", (key,)).fetchone()
        return {"status": row[0], "detail": row[1]} if row else None

    def claim(self, key, retry_unknown=False):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT status FROM slots WHERE slot=?", (key,)).fetchone()
            # SUBMITTING may belong to another process; never steal it.
            allowed = {"FAILED"} | ({"UNKNOWN"} if retry_unknown else set())
            if old and old[0] not in allowed:
                raise RuntimeError(f"중복 저장 차단: {old[0]}. 서버 예약 내역과 실행 기록을 확인하세요.")
            db.execute("INSERT OR REPLACE INTO slots VALUES (?, 'SUBMITTING', ?)",
                       (key, now_kst().isoformat()))

    def finish(self, key, status, detail=""):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO slots VALUES (?, ?, ?)", (key, status, detail))


@contextmanager
def closing_connection(path):
    db = sqlite3.connect(path, timeout=5)
    try:
        with db:
            yield db
    finally:
        db.close()


def outcome_exit_code(results, dry_run=False):
    statuses = [result["status"] for result in results]
    if statuses and all(s == ("DRY_RUN" if dry_run else "CONFIRMED") for s in statuses):
        return 0
    return 2 if any(s in ("CONFIRMED", "WAIT", "UNKNOWN", "SUBMITTING", "EXISTING") for s in statuses) else 1
