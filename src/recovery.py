"""혼잡 시 예약 저장 결과를 확인하고 제한적으로 재시도한다."""
import asyncio
import random
import re
from collections import Counter
from html import unescape
from urllib.parse import urlsplit


class ResponseError(RuntimeError):
    def __init__(self, step, response):
        self.status = response.status
        super().__init__(f"{step} HTTP 오류: {self.status}")


class RecoveredReservation(Exception):
    def __init__(self, result):
        self.result = result


def retry_delay(attempt, base=2.0, maximum=15.0):
    ceiling = min(maximum, base * 2 ** min(attempt, 20))
    return random.uniform(ceiling * .75, ceiling)


def materials_match(expected, actual):
    if not expected or not actual or len(expected) != len(actual):
        return False
    fields = set(expected[0])
    if not fields or any(set(row) != fields for row in expected):
        return False
    if any(not isinstance(row, dict) or not fields.issubset(row) for row in actual):
        return False
    stable = {field for field in fields if any(
        token in field.lower() for token in ("code", "item", "matnr", "seq", "_id", "cd"))}
    fields = stable or fields
    clean = lambda value: " ".join(unescape(re.sub(r"<[^>]*>", "", str(value or ""))).split())
    normalize = lambda rows: Counter(
        tuple((key, clean(row[key])) for key in sorted(fields)) for row in rows)
    return normalize(expected) == normalize(actual)


class ReservationRecoveryMixin:
    def artifact_prefix(self, hour):
        attempt = self.slot_attempts.get(hour, 1)
        return self.image_prefix if attempt == 1 else f"{self.image_prefix}_retry{attempt}"

    async def snapshot_materials(self, page):
        return await page.locator("#ly_popInreservationMain_itemList tr[id]").evaluate_all(r"""rows => rows.map(row => {
            const out = {};
            for (const cell of row.querySelectorAll('td[aria-describedby]')) {
                const key = cell.getAttribute('aria-describedby').replace(/^ly_popInreservationMain_itemList_/, '');
                if (['cb','rn'].includes(key) || cell.querySelector('input[type="checkbox"],button')) continue;
                const control = cell.querySelector('input,select,textarea');
                const value = (control ? control.value : cell.textContent).replace(/\s+/g,' ').trim();
                if (value) out[key] = value;
            }
            return out;
        })""")

    async def inspect_saved_reservation(self, source_page, hour, day, intent, verification_page=None):
        if not intent or not intent.get("owner") or not intent.get("materials") or not all(intent["materials"]):
            raise RuntimeError("저장 결과 비교 자료가 없습니다.")
        items_url = intent.get("items_url", "")
        source, target = urlsplit(source_page.url), urlsplit(items_url)
        if ((source.scheme, source.netloc) != (target.scheme, target.netloc)
                or not target.path.endswith("/selectInReservationItemListNew.do")):
            raise RuntimeError("저장 품목 조회 주소가 올바르지 않습니다.")
        page = verification_page or await source_page.context.new_page()
        try:
            reservation_path = urlsplit(self.config.get("reservation_url", "")).path
            if urlsplit(page.url).path != reservation_path:
                await self.prepare_reservation_tab(page, hour)
            date_field = page.locator("#srchReservDay")
            if await date_field.input_value() != day:
                await date_field.fill(day)
                await date_field.press("Tab")
            col = str({8:1, 9:2, 10:3, 11:4, 13:5, 14:6, 15:7}[hour])
            found = False
            for tab, status in (("atab1", "CONFIRMED"), ("atab2", "WAIT")):
                if await page.locator(".tabWrap ul li.active a").get_attribute("id") != tab:
                    await page.locator(f"#{tab}").click(timeout=self.site_timeout_ms)
                    await page.wait_for_function(
                        "tab => document.querySelector('.tabWrap ul li.active a')?.id === tab",
                        arg=tab, timeout=self.site_timeout_ms)
                data = await self.refresh_reservation_list(page, hour)
                matches = [row for row in data["rows"]
                           if str(row.get("facgubn")) == "1"
                           and row.get("comptype") in ("C2", "일반품목")
                           and str(row.get("colink" + col, "")) == intent["owner"]
                           and str(row.get("seq" + col, "")).strip() not in ("", "0", "None")]
                if len(matches) > 1:
                    raise RuntimeError("동일 시간대·업체 예약이 여러 건입니다.")
                if not matches:
                    continue
                found = True
                seq = str(matches[0]["seq" + col])
                response = await page.request.post(items_url, form={"srchSeq": seq}, timeout=self.site_timeout_ms)
                detail = await self.read_json_response(response, "저장 품목 재조회")
                if isinstance(detail.get("rows"), list) and materials_match(intent["materials"], detail["rows"]):
                    return dict(hour=hour, day=day, status=status, detail=f"예약번호 {seq} / 재조회 확인")
            return None if found else dict(hour=hour, day=day, status="ABSENT")
        finally:
            if verification_page is None:
                self.dialog_pages.discard(page)
                await page.close()

    async def observe_slow_save(self, page, hour, day, intent):
        await asyncio.sleep(self.config.get("save_probe_after_seconds", 10))
        absent = attempt = 0
        try:
            verification_page = await page.context.new_page()
        except Exception:
            verification_page = None
        try:
            while True:
                try:
                    result = await self.inspect_saved_reservation(
                        page, hour, day, intent, verification_page)
                    if result and result["status"] in ("CONFIRMED", "WAIT"):
                        return result
                    absent = absent + 1 if result and result["status"] == "ABSENT" else 0
                    if absent == self.config.get("save_retry_absence_checks", 2):
                        self.logger.info(
                            f"[{hour}시 탭] [WAITING] 서버 예약 미확인 {absent}회: "
                            "기존 저장 요청 응답을 계속 대기")
                except Exception as error:
                    absent = 0
                    self.logger.warning(f"[{hour}시 탭] 저장 대기 중 결과 조회 실패: {error}")
                attempt += 1
                await asyncio.sleep(min(15, 3 + attempt * 4))
        finally:
            if verification_page:
                self.dialog_pages.discard(verification_page)
                await verification_page.close()

    async def dismiss_retry_notice(self, page, hour):
        """502 등 재시도 전 사이트 HTML 알림을 닫는다. 브라우저 dialog는 이미 리스너가 승인한다."""
        notice = page.locator("#lyNoti")
        try:
            if not await notice.is_visible():
                return
            message = " ".join(await notice.locator("p").all_text_contents()).strip()
            close = notice.locator(".pop_btnclose")
            if await close.count() and await close.is_visible():
                await close.click(timeout=min(self.site_timeout_ms, 2000))
                self.logger.warning(f"[{hour}시 탭] 재시도 전 사이트 알림 닫음: {message or '내용 없음'}")
        except Exception as error:
            self.logger.warning(f"[{hour}시 탭] 재시도 전 사이트 알림 닫기 실패: {error}")

    async def recover_unknown(self, page, hour, day, key, result):
        intent = self.state.get_intent(key)
        if not intent or not intent.get("owner") or not intent.get("materials") or not all(intent["materials"]):
            result["detail"] += " / 비교 자료 없음: 자동 재저장 보류"
            return result
        deadline = asyncio.get_running_loop().time() + self.config.get("recovery_timeout_seconds", 600)
        not_before = asyncio.get_running_loop().time() + self.config.get("save_retry_grace_seconds", 5)
        absent = attempt = 0
        try:
            verification_page = await page.context.new_page()
        except Exception:
            verification_page = None
        try:
            while asyncio.get_running_loop().time() < deadline:
                delay = retry_delay(attempt, self.config.get("retry_base_seconds", 2),
                                    self.config.get("retry_max_seconds", 15))
                if asyncio.get_running_loop().time() + delay >= deadline:
                    break
                await asyncio.sleep(delay)
                try:
                    checked = await self.inspect_saved_reservation(
                        page, hour, day, intent, verification_page)
                    if checked and checked["status"] in ("CONFIRMED", "WAIT"):
                        return checked
                    absent = absent + 1 if checked and checked["status"] == "ABSENT" else 0
                    if ((intent.get("retryable_save") or intent.get("retryable_http"))
                            and absent >= self.config.get("save_retry_absence_checks", 2)
                            and asyncio.get_running_loop().time() >= not_before):
                        return dict(hour=hour, day=day, status="RETRY_READY",
                                    detail=f"저장 결과 없음 재조회 {absent}회 확인")
                except Exception as error:
                    absent = 0
                    self.logger.warning(f"[{hour}시 탭] 결과 재조회 실패: {error}")
                attempt += 1
        finally:
            if verification_page:
                self.dialog_pages.discard(verification_page)
                await verification_page.close()
        result["detail"] += " / 복구 시간 종료: 서버 내역 확인 필요"
        return result

    async def reserve_with_recovery(self, page, hour, day, key):
        for attempt in range(self.config.get("max_save_attempts", 3)):
            self.slot_attempts[hour] = attempt + 1
            if attempt:
                await self.dismiss_retry_notice(page, hour)
                await self.prepare_reservation_tab(page, hour)
            result = await self.reserve_open_slot(page, hour, day, key)
            if result["status"] == "UNKNOWN":
                result = await self.recover_unknown(page, hour, day, key, result)
            if result["status"] == "RETRY_READY":
                self.logger.warning(f"[{hour}시 탭] [RETRY] {attempt + 2}차 저장 시도: {result['detail']}")
                continue
            return result
        return dict(hour=hour, day=day, status="UNKNOWN", detail="저장 재시도 한도 도달")
