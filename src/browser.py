#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""COSMAX eBiz 예약 준비, 정상 클릭, 서버 저장 및 재조회 검증."""

import os
import asyncio
import logging
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, parse_qs
from src.reservation_state import ReservationState, now_kst


class CosmaxAutomation:
    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.current_step = "초기화"
        self.has_captured_screenshot = False
        self.state = ReservationState(config.get("state_dir", config.get("log_dir", "log")),
                                      legacy_paths=config.get("legacy_state_paths", []))
        self.submitted_hours = set()
        self.server_offset_seconds = 0.0  # 서버 시간 - 로컬 시간 (초 단위 오차)

        now = datetime.now()
        self.output_dir = getattr(logger, "run_dir", None) or os.path.abspath(
            os.path.join(config.get("log_dir", "log"), now.strftime("%Y%m%d")))
        self.run_id = getattr(logger, "run_id", None) or now.strftime("%Y%m%d_%H%M%S_%f")
        self.image_prefix = f"reservation_{self.run_id}_attempt{config.get('attempt', 1)}"

    def get_tab_output_dir(self, hour: int) -> str:
        """날짜별 로그 폴더 아래에서 시간대 탭 전용 산출물 경로를 반환한다."""
        path = os.path.join(self.output_dir, str(hour))
        os.makedirs(path, exist_ok=True)
        return path

    async def capture_failure_screenshot(self, page, error: Exception, step_name: str = "", hour: int = None) -> str:
        """실패 화면을 해당 시간대 폴더에 저장한다. 공통 실패는 각 시간대에 남긴다."""
        if hour is None:
            paths = []
            for target_hour in self.config.get("target_hours", [13, 14, 15]):
                paths.append(await self.capture_failure_screenshot(page, error, step_name, target_hour))
            return next((path for path in paths if path), "")
        active_step = step_name or self.current_step or "오류발생"
        tab_label = f"[{hour}시 탭] " if hour is not None else ""
        self.logger.error(f"❌ {tab_label}[FAIL] 단계 '{active_step}' 수행 중 예외 발생: {error}",
                          exc_info=(type(error), error, error.__traceback__))

        if page and not page.is_closed():
            try:
                screenshot_path = os.path.join(
                    self.get_tab_output_dir(hour), f"{self.image_prefix}_{hour:02d}_failure.png")
                await page.screenshot(path=screenshot_path, full_page=False)
                self.has_captured_screenshot = True
                self.logger.error(f"★ {tab_label}[FAIL] 실패 지점 스크린샷 저장 완료: {screenshot_path}")
                return screenshot_path
            except Exception as ss_err:
                self.logger.error(f"실패 지점 스크린샷 캡처 중 추가 에러 발생: {ss_err}")
        else:
            self.logger.warning("페이지가 열려있지 않거나 이미 닫혀 있어 실패 스크린샷을 저장할 수 없습니다.")
        return ""

    async def save_final_screenshot(self, page, hour: int) -> str:
        """현재 시간대의 마지막 화면을 같은 폴더에 저장한다."""
        path = await self.save_stage_screenshot(page, hour, 10, "final")
        self.has_captured_screenshot = bool(path) or self.has_captured_screenshot
        return path

    async def save_stage_screenshot(self, page, hour: int, stage: int, name: str) -> str:
        """현재 뷰포트를 캡처한다. 전체 페이지 캡처는 사이트의 resize 핸들러로 팝업 순서를 바꾼다."""
        if not page or page.is_closed():
            self.logger.warning(f"[{hour}시 탭] 단계 {stage:02d} 스크린샷을 저장할 페이지가 없습니다.")
            return ""

        path = os.path.join(
            self.get_tab_output_dir(hour),
            f"{self.image_prefix}_{hour:02d}_{stage:02d}_{name}.png",
        )
        try:
            await page.screenshot(path=path, full_page=False)
            self.logger.info(f"📷 [{hour}시 탭] 단계 {stage:02d} ({name}) 스크린샷 저장: {path}")
            return path
        except Exception as error:
            self.logger.warning(f"[{hour}시 탭] 단계 {stage:02d} ({name}) 스크린샷 저장 실패: {error}")
            return ""

    async def launch_browser(self, playwright_obj):
        """Playwright 브라우저 고속 실행 (Chromium 경량화 가속 플래그 적용)"""
        headless_mode = self.config.get("headless", False)
        launch_args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
            "--disable-extensions",
            "--disable-sync",
            "--disable-default-apps"
        ]
        if not headless_mode:
            launch_args.append("--start-maximized")
        self.logger.info(f"[Step 1] 고속 경량 브라우저 기동 중... (Headless: {headless_mode})")

        try:
            return await playwright_obj.chromium.launch(headless=headless_mode, args=launch_args)
        except Exception as err1:
            self.logger.warning(f"번들 Chromium 실행 실패({err1}). 시스템 설치 Chrome으로 재시도합니다...")
            try:
                return await playwright_obj.chromium.launch(channel="chrome", headless=headless_mode, args=launch_args)
            except Exception as err2:
                self.logger.error(f"브라우저 실행 실패: {err2}")
                raise err2

    async def set_maximized(self, context, page):
        """로그인/팝업을 열기 전에 탭과 주소 표시줄을 유지하며 실제 Chromium 창을 최대화한다."""
        if self.config.get("headless", False):
            return
        session = await context.new_cdp_session(page)
        try:
            window = await session.send("Browser.getWindowForTarget")
            await session.send("Browser.setWindowBounds", {
                "windowId": window["windowId"], "bounds": {"windowState": "maximized"}
            })
            async with asyncio.timeout(6):
                while True:
                    state = await session.send("Browser.getWindowBounds", {"windowId": window["windowId"]})
                    if state["bounds"]["windowState"] == "maximized":
                        break
                    await asyncio.sleep(0.1)
            # 팝업이 없는 초기 화면에서만 창 크기를 변경한다.
            await page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        finally:
            await session.detach()

    async def perform_login(self, page):
        """로그인 폼 입력 및 로그인 제출 & 서버 시계 오차(HTTP Date 참고값) 1회 측정"""
        self.current_step = "Step2_로그인_접속"
        target_url = self.config["url"]
        user_id = self.config["user_id"]
        user_pw = self.config["user_pw"]

        self.logger.info(f"[Step 2] 로그인 페이지 접속: {target_url}")
        resp = await page.goto(target_url, wait_until="commit")

        # COSMAX 서버 시계와 로컬 PC 시계 간의 오차(HTTP Date 참고값) 자동 계산
        if resp:
            date_hdr = resp.headers.get("date")
            if date_hdr:
                try:
                    server_dt = parsedate_to_datetime(date_hdr).astimezone()
                    local_dt = now_kst()
                    self.server_offset_seconds = (server_dt - local_dt).total_seconds()
                    self.logger.info(f"★ [HTTP Date 시각 참고] COSMAX 서버 시계 오차: {self.server_offset_seconds:+.3f}초 (서버 시각: {server_dt.strftime('%H:%M:%S')})")
                except Exception as ntp_err:
                    self.logger.warning(f"서버 시간 파싱 실패(로컬 PC 시계 사용): {ntp_err}")

        self.current_step = "Step3_계정정보_입력"
        self.logger.info(f"[Step 3] 아이디/비밀번호 Fast Fill: {user_id}")
        await page.fill("#userId", user_id)
        await page.fill("#passwd", user_pw)

        self.current_step = "Step4_로그인_제출"
        self.logger.info("[Step 4] 로그인 버튼 클릭 / 제출")
        login_btn = page.locator("a:has-text('로그인'), input[type='submit'], .btn_login, #btnLogin")
        if await login_btn.count() > 0 and await login_btn.first.is_visible():
            await login_btn.first.click()
        else:
            await page.keyboard.press("Enter")

        # 로그인 제출 후 세션 확립 및 페이지 전환 대기
        try:
            await page.wait_for_url(lambda u: "loginForm.do" not in u, timeout=5000)
        except Exception:
            try:
                await page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                await page.wait_for_timeout(2000)

    async def verify_session(self, context, page):
        """세션 쿠키(JSESSIONID) 및 현재 URL 확인"""
        cookies = await context.cookies()
        jsessionid = next((c['value'] for c in cookies if c['name'] == 'JSESSIONID'), None)
        if not jsessionid or "loginForm.do" in page.url or await page.locator("#passwd").is_visible():
            raise RuntimeError("로그인 완료를 확인할 수 없습니다. 세션 및 로그인 결과를 확인하세요.")
        self.logger.info(f"★ 세션 인증 확인 완료! (JSESSIONID: {jsessionid})")
        self.logger.info(f"현재 접속 위치: {page.url}")

    async def prepare_reservation_tab(self, page, hour: int):
        """
        개별 탭의 사전 준비 단계:
        1. 브라우저 다이얼로그(alert/confirm) 자동 승인 리스너 등록
        2. 예약 페이지 이동
        3. [지류]청북2층 라디오 버튼 선택
        4. 예약 그리드 로딩 완료 대기
        """
        tab_label = f"{hour}시 탭"
        self.logger.info(f"[{tab_label}] 예약 탭 준비 시작...")

        # 다이얼로그 자동 승인 리스너 등록
        async def handle_dialog(dialog):
            self.logger.info(f"★ [{tab_label}] 브라우저 알림/팝업 즉시 승인: '{dialog.message}'")
            try:
                await dialog.accept()
            except Exception:
                pass

        page.on("dialog", handle_dialog)

        reservation_url = self.config.get("reservation_url")
        if reservation_url:
            self.logger.info(f"[{tab_label}] 예약 페이지로 이동 중: {reservation_url}")
            await page.goto(reservation_url, wait_until="domcontentloaded")

        if "loginForm.do" in page.url:
            raise RuntimeError(f"[{tab_label}] 예약 페이지가 로그인 화면으로 돌아갔습니다.")
        await self.check_site_notice(page, hour, "예약 페이지 준비")
        # jqTransform의 표시용 라디오를 정상 클릭하고 실제 input 선택도 검사한다.
        radio = page.locator('#selFactory1')
        await radio.wait_for(state="attached", timeout=6000)
        if not await radio.is_checked():
            wrapper = page.locator('.jqTransformRadioWrapper:has(#selFactory1) a.jqTransformRadio')
            if await wrapper.is_visible():
                await wrapper.click(timeout=6000)
            else:
                await radio.check(timeout=6000)
        if not await radio.is_checked():
            raise RuntimeError(f"[{tab_label}] [지류]청북2층 선택 실패")
        await self.refresh_reservation_list(page, hour)
        self.logger.info(f"[{tab_label}] 로그인·창고·예약 목록 준비 확인 완료")

    async def refresh_reservation_list(self, page, hour):
        async with page.expect_response(
            lambda r: urlsplit(r.url).path.endswith('/selectInreservationListNew.do'), timeout=6000
        ) as response_info:
            await self.click_reservation_button(page, hour, '#btnSelect', '예약 목록 조회')
        data = await self.read_json_response(await response_info.value, "예약 목록 조회")
        if data.get("returnCode") in ("FAIL", "NOSES") or not isinstance(data.get("rows"), list):
            raise RuntimeError(f"[{hour}시 탭] 예약 목록 조회 실패: {data.get('returnMessage', '')}")
        await page.locator('table#list tr[id="1"]').wait_for(state='attached', timeout=6000)
        await page.locator('#load_list').wait_for(state='hidden', timeout=6000)
        await self.check_site_notice(page, hour, "예약 목록 조회")
        return data

    async def wait_until_target_time(self, page):
        """한국 시각과 HTTP Date 참고 오차로 대기한다. 마지막 5초에는 ping하지 않는다."""
        h, m, sec = map(int, self.config.get("target_time", "10:00:00").split(":"))
        current = now_kst() + timedelta(seconds=self.server_offset_seconds)
        target = current.replace(hour=h, minute=m, second=sec, microsecond=0)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0, (target - current).total_seconds())
        next_ping = loop.time()
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            if remaining > 5 and loop.time() >= next_ping:
                timeout = min(self.config.get("keep_alive_timeout_seconds", 3), remaining - 5)
                try:
                    response = await page.request.get(page.url, timeout=timeout * 1000)
                    if not response.ok or "loginForm.do" in response.url:
                        raise RuntimeError(f"세션 유지 응답 오류: HTTP {response.status}, {response.url}")
                except Exception as error:
                    self.logger.warning(f"[Keep-Alive] 실패: {error}")
                    raise RuntimeError("세션 유지 실패: 예약 시작 전 세션 복구가 필요합니다.") from error
                next_ping = loop.time() + self.config.get("keep_alive_interval_seconds", 30)
            # 네트워크 요청에 걸린 시간을 반영하여 남은 시간을 다시 계산한다.
            remaining = deadline - loop.time()
            if remaining > 0:
                await asyncio.sleep(min(remaining, 0.02 if remaining <= 1 else 1))
        self.logger.info(f"목표 시각 {self.config.get('target_time', '10:00:00')} 도달. 예약을 시작합니다.")

    async def read_json_response(self, response, step):
        if not response.ok:
            raise RuntimeError(f"{step} HTTP 오류: {response.status}")
        try:
            data = await asyncio.wait_for(response.json(), timeout=6)
        except Exception as error:
            raise RuntimeError(f"{step} JSON 응답을 확인할 수 없습니다.") from error
        if not isinstance(data, dict):
            raise RuntimeError(f"{step} 응답은 JSON 객체여야 합니다.")
        return data

    async def check_site_notice(self, page, hour: int, step: str):
        """브라우저 dialog와 별개인 사이트 HTML 오류 알림을 보존하고 중단한다."""
        notice = page.locator("#lyNoti")
        if await notice.is_visible():
            message = " ".join(await notice.locator("p").all_text_contents()).strip()
            message = message or "내용 없는 알림 (통신 오류 또는 서버 응답 확인 필요)"
            raise RuntimeError(f"[{hour}시 탭] {step}: 사이트 알림 - {message}")

    async def click_reservation_button(self, page, hour: int, selector: str, step: str):
        """가려진 버튼을 우회하지 않고 사이트의 정상 클릭 경로로 진행한다."""
        await self.check_site_notice(page, hour, step)
        try:
            await page.locator(selector).click(timeout=6000)
        except Exception:
            await self.check_site_notice(page, hour, step)
            raise
        await self.check_site_notice(page, hour, step)

    async def add_self_materials(self, page, hour: int):
        """자급자재 창 열기부터 조회·선택·메인 창 추가까지 완료 상태를 확인한다."""
        def log_failed_request(request):
            if request.resource_type in ("xhr", "fetch"):
                self.logger.error(
                    f"[{hour}시 탭] 통신 실패: {request.method} {urlsplit(request.url).path} - {request.failure}"
                )

        def log_error_response(response):
            if response.status >= 400 and response.request.resource_type in ("xhr", "fetch"):
                self.logger.error(
                    f"[{hour}시 탭] HTTP 오류: {response.status} {urlsplit(response.url).path}"
                )

        page.on("requestfailed", log_failed_request)
        page.on("response", log_error_response)
        step = "자급자재 창 열기"
        try:
            main_rows = page.locator('#ly_popInreservationMain_itemList tr[id]')
            main_count_before = await main_rows.count()
            expected_main_count = main_count_before + 3
            await self.click_reservation_button(
                page, hour, "#ly_popInreservationMain_btnSelfAdd", step
            )
            await page.locator("#ly_popInreservationSelf").wait_for(state="visible", timeout=6000)
            await self.check_site_notice(page, hour, step)
            await self.save_stage_screenshot(page, hour, 3, "self_material_modal_opened")

            step = "자급자재 조회"
            async with page.expect_response(
                lambda response: response.request.method == "POST"
                and response.url.split("?", 1)[0].endswith("/selectMMIF0015List.do"),
                timeout=6000,
            ) as response_info:
                await self.click_reservation_button(
                    page, hour, "#ly_popInreservationSelf_btnSelect", step
                )
            response = await response_info.value
            self.logger.info(f"[{hour}시 탭] 자급자재 조회 응답: HTTP {response.status}")
            if not response.ok:
                raise RuntimeError(f"[{hour}시 탭] 자급자재 조회 HTTP 오류: {response.status}")
            try:
                data = await asyncio.wait_for(response.json(), timeout=6)
            except asyncio.TimeoutError as error:
                raise RuntimeError(f"[{hour}시 탭] 자급자재 조회 응답 본문 수신 시간이 초과되었습니다.") from error
            except Exception as error:
                raise RuntimeError(f"[{hour}시 탭] 자급자재 조회 응답이 JSON이 아닙니다.") from error
            if not isinstance(data, dict):
                raise RuntimeError(f"[{hour}시 탭] 자급자재 조회 응답 형식이 올바르지 않습니다.")
            if data.get("returnCode") in ("FAIL", "NOSES"):
                message = data.get("returnMessage") or "오류 메시지 없음"
                raise RuntimeError(f"[{hour}시 탭] 자급자재 조회 실패: {data['returnCode']} - {message}")
            if not isinstance(data.get("rows"), list):
                raise RuntimeError(f"[{hour}시 탭] 자급자재 조회 응답 형식이 올바르지 않습니다.")
            if not data["rows"]:
                raise RuntimeError(f"[{hour}시 탭] 조회된 자급자재가 없습니다.")

            # 응답 헤더 수신이 아니라 jqGrid의 데이터 반영과 로딩 종료를 기다린다.
            await page.wait_for_function("""() => {
                const notice = document.getElementById('lyNoti');
                if (notice && notice.getClientRects().length && getComputedStyle(notice).visibility !== 'hidden') return true;
                const loading = document.getElementById('load_ly_popInreservationSelf_itemList');
                return (!loading || !loading.getClientRects().length)
                    && Boolean(document.querySelector('#ly_popInreservationSelf_itemList tr[id] input[type="checkbox"]'));
            }""", timeout=6000)
            await self.check_site_notice(page, hour, step)
            await self.save_stage_screenshot(page, hour, 4, "self_materials_loaded")

            step = "자급자재 품목 선택"
            table = page.locator("#ly_popInreservationSelf_itemList")
            checked_count = await table.locator('input[type="checkbox"]:checked').count()
            expected_count = checked_count + 3
            eligible = table.locator(
                'tr[id]:has(td[aria-describedby="ly_popInreservationSelf_itemList_grctrl"]:text-is("O")) '
                'input[type="checkbox"]:enabled:not(:checked)'
            )
            count = await eligible.count()
            if count < 3:
                raise RuntimeError(f"[{hour}시 탭] 미선택 납품허용 자급자재가 3개 미만입니다. (추가 선택 가능: {count}개, 기존 선택: {checked_count}개)")
            for _ in range(3):
                await self.check_site_notice(page, hour, step)
                # 체크하면 후보에서 빠지므로 매번 첫 번째 미선택 항목을 선택한다.
                await eligible.first.check(timeout=6000)
            await self.check_site_notice(page, hour, step)
            if await table.locator('input[type="checkbox"]:checked').count() != expected_count:
                raise RuntimeError(f"[{hour}시 탭] 선택 자재 수가 기대값 {expected_count}개와 다릅니다.")
            self.logger.info(f"[{hour}시 탭] 기존 선택 {checked_count}개 유지, 납품허용 자급자재 3개 추가 선택 완료 (총 {expected_count}개)")
            await self.save_stage_screenshot(page, hour, 5, "three_materials_selected")

            step = "선택 자급자재 추가"
            await self.click_reservation_button(
                page, hour, "#ly_popInreservationSelf_btnAdd", step
            )
            await page.wait_for_function("""(expectedCount) => {
                const notice = document.getElementById('lyNoti');
                if (notice && notice.getClientRects().length && getComputedStyle(notice).visibility !== 'hidden') return true;
                const subModal = document.getElementById('ly_popInreservationSelf');
                const rows = document.querySelectorAll('#ly_popInreservationMain_itemList tr[id]');
                return subModal && !subModal.getClientRects().length && rows.length >= expectedCount;
            }""", arg=expected_main_count, timeout=6000)
            await self.check_site_notice(page, hour, step)
            main_count_after = await main_rows.count()
            if main_count_after != expected_main_count:
                raise RuntimeError(f"[{hour}시 탭] 자급자재 추가 확인 실패: 메인 기존 {main_count_before}개 + 신규 3개, 실제 {main_count_after}개")
            self.logger.info(f"[{hour}시 탭] 메인 예약창 자급자재 추가 완료: 기존 {main_count_before}개 + 신규 3개 = 총 {main_count_after}개")
            await self.save_stage_screenshot(page, hour, 6, "materials_added_to_main")
        except Exception:
            await self.check_site_notice(page, hour, step)
            raise
        finally:
            page.remove_listener("requestfailed", log_failed_request)
            page.remove_listener("response", log_error_response)

    async def validate_reservation_form(self, page, hour, day, col_arg):
        if await page.locator('#srchReservDay').input_value() != day:
            raise RuntimeError(f"[{hour}시 탭] 조회 예약일이 변경되었습니다.")
        for field, expected in [('srchReservDay', day), ('srchReservTime', col_arg),
                                ('srchFacgubn', '1'), ('srchComptype', 'C2')]:
            actual = await page.locator(f'#ly_popInreservationMain_{field}').input_value()
            if actual != expected:
                raise RuntimeError(f"[{hour}시 탭] 예약 정보 불일치: {field}={actual}, 기대값={expected}")

    async def load_existing_materials(self, page, hour, seq):
        """기존 예약 품목을 먼저 읽어 자급자재 조회 시 기존 체크가 반영되게 한다."""
        async with page.expect_response(
            lambda r: r.request.method == 'POST'
            and urlsplit(r.url).path.endswith('/selectInReservationItemListNew.do')
            and parse_qs(r.request.post_data or '').get('srchSeq') == [seq],
            timeout=6000,
        ) as info:
            await self.click_reservation_button(page, hour, '#ly_popInreservationMain_btnSelect', '기존 예약 품목 조회')
        data = await self.read_json_response(await info.value, '기존 예약 품목 조회')
        if data.get('returnCode') in ('FAIL', 'NOSES') or not isinstance(data.get('rows'), list):
            raise RuntimeError(f"[{hour}시 탭] 기존 예약 품목 조회 실패: {data.get('returnMessage', '')}")
        await page.wait_for_function("""(count) => {
            const loading = document.querySelector('#load_ly_popInreservationMain_itemList');
            return (!loading || !loading.getClientRects().length)
                && document.querySelectorAll('#ly_popInreservationMain_itemList tr[id]').length === count;
        }""", arg=len(data['rows']), timeout=6000)
        await self.check_site_notice(page, hour, '기존 예약 품목 조회')
        self.logger.info(f"[{hour}시 탭] 기존 예약번호 {seq}: 품목 {len(data['rows'])}개 조회 완료, 추가 선택 진행")

    async def reserve_single_slot(self, page, hour: int):
        tab_label = f"{hour}시 탭"
        col_arg = str({8: 1, 9: 2, 10: 3, 11: 4, 13: 5, 14: 6, 15: 7}[hour])
        day = await page.locator('#srchReservDay').input_value()
        try:
            datetime.strptime(day, '%Y%m%d')
        except ValueError as error:
            raise RuntimeError(f"[{tab_label}] 예약일 형식 오류: {day}") from error
        if day < now_kst().strftime('%Y%m%d'):
            raise RuntimeError(f"[{tab_label}] 과거 예약일: {day}")
        account = self.config.get('user_id', '')
        key = self.state.key(account, day, hour)
        old = self.state.get(key)
        if not self.config.get('dry_run') and old:
            if old['status'] in ('CONFIRMED', 'WAIT'):
                self.logger.info(f"[{tab_label}] 기존 처리 기록 유지: {old['status']} / {day}")
                return dict(hour=hour, day=day, **old)
            if old['status'] == 'SUBMITTING':
                self.logger.warning(f"[{tab_label}] 진행 중인 저장 기록 유지: SUBMITTING / {day}")
                return dict(hour=hour, day=day, **old)
            if old['status'] == 'UNKNOWN':
                self.logger.info(f"[{tab_label}] 이전 UNKNOWN 기록을 재시도합니다: {old['detail']}")
        row = page.locator('table#list tr[id="1"]')
        warehouse = await row.locator('[aria-describedby="list_facgubn"]').text_content()
        if warehouse.strip() != '1':
            raise RuntimeError(f"[{tab_label}] 예약 행의 창고가 청북2층이 아닙니다.")
        checkbox = row.locator(f'td[aria-describedby="list_checkYn{col_arg}"] input[type="checkbox"]')
        try:
            async with asyncio.timeout(self.config.get('grid_wait_timeout_seconds', 5)):
                while not (await checkbox.count() and await checkbox.is_enabled()):
                    await self.check_site_notice(page, hour, '시간대 활성화 대기')
                    await self.refresh_reservation_list(page, hour)
                    await asyncio.sleep(0.1)
        except TimeoutError as error:
            raise RuntimeError(f"[{tab_label}] 대상 시간대 체크박스가 활성화되지 않았습니다. (마감 또는 미오픈)") from error
        seq = (await row.locator(f'[aria-describedby="list_seq{col_arg}"]').text_content()).strip()
        existing_reservation = bool(seq and seq != '0')
        await checkbox.check(timeout=6000)
        await self.save_stage_screenshot(page, hour, 1, "slot_selected")
        await self.click_reservation_button(
            page, hour, f'table#list tr[id="1"] td[aria-describedby="list_cobut{col_arg}"] a', '예약 창 열기'
        )
        await page.locator('#ly_popInreservationMain').wait_for(state='visible', timeout=6000)
        await self.validate_reservation_form(page, hour, day, col_arg)
        if existing_reservation:
            await self.load_existing_materials(page, hour, seq)
        await self.save_stage_screenshot(page, hour, 2, "main_modal_opened")

        # 3~6. 실제 팝업 표시와 조회 완료를 확인하며 자급자재를 추가한다.
        await self.add_self_materials(page, hour)

        # 7. 실제 입력란에 수량을 입력하고 change 이벤트가 발생하도록 포커스를 이동한다.
        await self.check_site_notice(page, hour, "수량 입력")
        for field in ("paletteTotal", "carTotal"):
            control = page.locator(f"#ly_popInreservationMain_{field}")
            if existing_reservation and (await control.input_value()).strip():
                continue
            await control.fill("1", timeout=6000)
            await control.press("Tab")
        await self.check_site_notice(page, hour, "수량 입력")
        await self.save_stage_screenshot(page, hour, 7, "quantities_entered")

        await self.validate_reservation_form(page, hour, day, col_arg)
        if self.config.get('dry_run'):
            self.logger.info(f"[{tab_label}] [DRY_RUN] {day} / {hour}시 / 청북2층 / 일반품목 / 기존 선택 유지 및 자재 3개 추가 검증 완료. 저장 생략")
            return dict(hour=hour, day=day, status='DRY_RUN')

        self.state.claim(key)
        self.submitted_hours.add(hour)
        result = dict(hour=hour, day=day, status='UNKNOWN', detail='저장 결과 확인 필요')
        responses = []
        def collect(response):
            if response.request.method == 'POST' and urlsplit(response.url).path.endswith('/saveInReservationWait.do'):
                responses.append(response)
        page.on('response', collect)
        try:
            async with page.expect_response(
                lambda r: r.request.method == 'POST' and urlsplit(r.url).path.endswith('/saveInReservationItemListNew.do'),
                timeout=12000
            ) as info:
                # 이후 성공 안내도 lyNoti를 쓰므로 클릭 직후의 일반 오류 검사는 하지 않는다.
                await self.check_site_notice(page, hour, '예약 저장 전')
                await page.locator('#ly_popInreservationMain_btnSave').click(timeout=6000)
            response = await info.value
            data = await self.read_json_response(response, '예약 저장')
            code = data.get('returnCode')
            self.logger.info(f"[{tab_label}] 저장 응답: {code} / {data.get('returnMessage', '')}")
            if code not in ('SUCCESS', 'WAIT'):
                result.update(status='FAILED' if code in ('FAIL', 'NOSES') else 'UNKNOWN',
                              detail=str(data.get('returnMessage') or f'알 수 없는 저장 응답: {code}'))
                return result
            status = 'CONFIRMED'
            if code == 'WAIT':
                wait_data = data.get('returnCosmaxData') or {}
                if not (wait_data.get('seq') and wait_data.get('seq') == wait_data.get('waitSeq')):
                    deadline = asyncio.get_running_loop().time() + 12
                    while not responses:
                        if asyncio.get_running_loop().time() >= deadline:
                            raise RuntimeError('대기 등록 후속 저장 응답 미확인')
                        await asyncio.sleep(0.05)
                    followup = await self.read_json_response(responses[0], '대기 등록')
                    if followup.get('returnCode') != 'SUCCESS':
                        raise RuntimeError(f"대기 등록 실패: {followup.get('returnMessage', '')}")
                status = 'WAIT'
            # 정상 안내 문구만 닫고, 새 서버 조회로 예약번호와 업체를 대조한다.
            await page.wait_for_function("""() => {
                const el=document.querySelector('#lyNoti');
                return el && el.getClientRects().length && (el.textContent.includes('등록') || el.textContent.includes('확정'));
            }""", timeout=6000)
            notice_text = await page.locator('#lyNoti').text_content()
            self.logger.info(f"[{tab_label}] 저장 완료 안내: {notice_text.strip()}")
            await self.save_stage_screenshot(page, hour, 8, 'save_notice')
            expected = '입고 예약이 확정' if status == 'CONFIRMED' else '입고예약 대기'
            if expected not in notice_text or f'[{hour:02d}:00]' not in notice_text:
                raise RuntimeError(f'예상하지 않은 저장 알림: {notice_text}')
            await page.locator('#lyNoti .pop_btnclose').click(timeout=6000)
            active_tab = await page.locator('.tabWrap ul li.active a').get_attribute('id')
            if active_tab != ('atab1' if status == 'CONFIRMED' else 'atab2'):
                raise RuntimeError('저장 후 확정/대기 목록 탭이 예상과 다릅니다.')
            data = await self.refresh_reservation_list(page, hour)
            owner = parse_qs(response.request.post_data or '').get('colink', [''])[0]
            # 실제 저장 요청의 업체 번호를 사용한다. 서버 목록 형식 변경 시 확정하지 않는다.
            matches = [r for r in data['rows'] if str(r.get('facgubn')) == '1'
                       and r.get('comptype') in ('C2', '일반품목')
                       and str(r.get('colink' + col_arg, '')) == owner and owner
                       and str(r.get('seq' + col_arg, '')).strip() not in ('', '0', 'None')]
            if len(matches) != 1 or await page.locator('#srchReservDay').input_value() != day:
                raise RuntimeError('저장 후 예약 목록에서 동일 날짜·창고·시간·업체의 예약번호를 확인하지 못했습니다.')
            result.update(status=status, detail=f"예약번호 {matches[0]['seq' + col_arg]}")
            self.logger.info(f"[{tab_label}] [{status}] {day} {hour}시 {result['detail']}")
            return result
        except Exception as error:
            result['detail'] = str(error)
            self.logger.error(f"[{tab_label}] [UNKNOWN] {error}. 이번 실행에서는 추가 저장하지 않습니다.")
            await self.capture_failure_screenshot(page, error, '저장_결과_미확인', hour)
            return result
        finally:
            page.remove_listener('response', collect)
            self.state.finish(key, result['status'], result['detail'])
            await self.save_stage_screenshot(page, hour, 9, 'reservation_result')


async def execute_automation(config: dict, logger: logging.Logger):
    """
    Playwright 초고속 멀티탭 병렬 예약 오케스트레이션
    - 리소스 차단(폰트/미디어)으로 3개 탭 기동 가속
    - 1회 로그인 후 13시, 14시, 15시 3개 탭 생성
    - 서버 시계 10:00:00 정각 동시 예약 트리거 (asyncio.gather)
    - 시간대별 최종 화면 저장
    """
    from playwright.async_api import async_playwright

    automation = CosmaxAutomation(config, logger)
    target_hours = config.get("target_hours", [13, 14, 15])

    async with async_playwright() as p:
        browser = None
        tabs = []  # [(hour, page), ...]

        try:
            # 1. 브라우저 및 컨텍스트 생성 (세션 쿠키 공유)
            browser = await automation.launch_browser(p)
            vp_w = config.get("viewport_width", 2200)
            vp_h = config.get("viewport_height", 1080)
            context = await browser.new_context(
                viewport={"width": vp_w, "height": vp_h} if config.get("headless", False) else None,
                no_viewport=not config.get("headless", False),
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

            # 리소스 차단 (웹폰트 및 불필요 미디어 차단으로 탭 3개 로딩 및 메모리 최적화)
            async def route_filter(route):
                if config.get("dry_run") and any(name in urlsplit(route.request.url).path for name in (
                    "saveInReservation", "deleteInReservation"
                )):
                    logger.error("[DRY_RUN] 저장/삭제 요청 차단")
                    await route.abort()
                elif route.request.resource_type in ["media", "font"]:
                    await route.abort()
                else:
                    await route.continue_()

            await context.route("**/*", route_filter)

            # 2. 첫 번째 탭에서 로그인 1회 수행 (JSESSIONID 확립 및 서버 시계 오차 계산)
            main_page = await context.new_page()
            tabs.append((target_hours[0], main_page))
            await automation.set_maximized(context, main_page)
            await automation.perform_login(main_page)
            await automation.verify_session(context, main_page)

            # 3. 추가 시간대(14시, 15시 등)를 위한 병렬 탭 동시 생성 (동일 context 내 세션 공유)
            for hr in target_hours[1:]:
                tab_page = await context.new_page()
                await automation.set_maximized(context, tab_page)
                tabs.append((hr, tab_page))

            # 4. 각 탭 사전 준비 (예약 페이지 이동 + [지류]청북2층 선택 + dialog 자동 승인)
            logger.info("======================================================================")
            logger.info(f"⚡ [Step 5] {len(target_hours)}개 탭({target_hours}) 예약 페이지 사전 접속 및 위치 선택 병렬 준비...")
            logger.info("======================================================================")
            prep_tasks = [
                automation.prepare_reservation_tab(page_obj, hr)
                for hr, page_obj in tabs
            ]
            prep_results = await asyncio.gather(*prep_tasks, return_exceptions=True)
            ready_tabs = []
            prep_failed_errors = []
            for (hr, page_obj), result in zip(tabs, prep_results):
                if isinstance(result, Exception):
                    logger.error(f"❌ [{hr}시 탭] 사전 준비 실패: {result}")
                    await automation.capture_failure_screenshot(page_obj, result, "사전_준비", hour=hr)
                    prep_failed_errors.append((hr, result))
                else:
                    ready_tabs.append((hr, page_obj))

            if not ready_tabs:
                first_hr, first_error = prep_failed_errors[0]
                raise RuntimeError(f"모든 시간대({target_hours}) 사전 준비 실패: {prep_failed_errors}") from first_error

            logger.info(
                f"★ 사전 준비 완료 탭: {[hr for hr, _ in ready_tabs]} | "
                f"사전 준비 실패 탭: {[hr for hr, _ in prep_failed_errors]}"
            )

            # 5. 서버 시계 기준 목표 시각(10:00:00)까지 세션 유지 대기
            logger.info("======================================================================")
            logger.info(f"[Step 6] 목표 시각 {config.get('target_time')} 대기 (dry_run이면 생략)")
            logger.info("======================================================================")
            if not config.get("dry_run"):
                await automation.wait_until_target_time(ready_tabs[0][1])

            # 6. 정각 도달: 3개 탭 동시 비동기 병렬 예약 실행 (asyncio.gather)
            logger.info("======================================================================")
            ready_hours_text = ", ".join(f"{hr}시" for hr, _ in ready_tabs)
            logger.info(f"🚀 [Step 7] {ready_hours_text} 탭 비동기 병렬 동시 예약 트리거! (asyncio.gather)")
            logger.info("======================================================================")
            reserve_tasks = [
                automation.reserve_single_slot(page_obj, hr)
                for hr, page_obj in ready_tabs
            ]

            # 1개 탭의 실패가 다른 탭에 영향을 주지 않도록 return_exceptions=True 적용
            results = await asyncio.gather(*reserve_tasks, return_exceptions=True)

            outcomes = [dict(hour=hr, status='FAILED', detail=str(error)) for hr, error in prep_failed_errors]
            for (hr, page_obj), result in zip(ready_tabs, results):
                if isinstance(result, Exception):
                    await automation.capture_failure_screenshot(page_obj, result, '예약_처리', hour=hr)
                    result = dict(hour=hr, status='UNKNOWN' if hr in automation.submitted_hours else 'FAILED', detail=str(result))
                outcomes.append(result)
                logger.info(f"[{hr}시 탭] [RESULT] {result}")
            for hr, page_obj in ready_tabs:
                await automation.save_final_screenshot(page_obj, hr)
            return outcomes

        except Exception as exc:
            if not automation.has_captured_screenshot:
                fallback_page = tabs[0][1] if tabs else None
                await automation.capture_failure_screenshot(fallback_page, exc)
            if automation.submitted_hours:
                return [dict(hour=hr, status="UNKNOWN", detail=str(exc)) for hr in target_hours]
            raise
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
