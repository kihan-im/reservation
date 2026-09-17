"""현재 실행 안에서 시간대별 중복 저장을 막는다. 최종 기준은 서버 예약 목록이다."""
import json
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def now_kst():
    return datetime.now(KST)


class ReservationState:
    """스케줄러와 수동 실행이 겹치지 않는 운영 전제의 인메모리 상태."""
    def __init__(self, state_dir=None, legacy_paths=()):
        self.slots = {}
        self.intents = {}

    @staticmethod
    def key(account, day, hour):
        return json.dumps([account, day, "1", hour], ensure_ascii=False)

    def get(self, key):
        value = self.slots.get(key)
        return dict(value) if value else None

    def claim(self, key, allow_completed=False):
        old = self.slots.get(key)
        allowed = {"FAILED", "UNKNOWN"}
        if allow_completed:
            allowed.update(("CONFIRMED", "WAIT", "EXISTING_CONFIRMED"))
        if old and old["status"] not in allowed:
            raise RuntimeError(f"중복 저장 차단: {old['status']}. 서버 예약 내역과 실행 기록을 확인하세요.")
        self.slots[key] = {"status": "SUBMITTING", "detail": now_kst().isoformat()}
        return dict(old) if old else None

    def release(self, key, previous):
        if previous is None:
            self.slots.pop(key, None)
        else:
            self.slots[key] = dict(previous)

    def finish(self, key, status, detail=""):
        self.slots[key] = {"status": status, "detail": detail}

    def save_intent(self, key, intent):
        self.intents[key] = json.loads(json.dumps(intent, ensure_ascii=False))

    def get_intent(self, key):
        intent = self.intents.get(key)
        return json.loads(json.dumps(intent, ensure_ascii=False)) if intent else None


def outcome_exit_code(results, dry_run=False):
    statuses = [result["status"] for result in results]
    successful = {"DRY_RUN"} if dry_run else {"CONFIRMED", "EXISTING_CONFIRMED"}
    if statuses and all(s in successful for s in statuses):
        return 0
    return 2 if any(s in ("CONFIRMED", "WAIT", "UNKNOWN", "SUBMITTING", "EXISTING",
                          "EXISTING_CONFIRMED", "NO_CHANGE") for s in statuses) else 1
