#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""COSMAX eBiz 예약 준비, 정상 클릭, 서버 저장 및 재조회 검증."""

import os
import asyncio
import logging
import time
import re
from statistics import median
from pathlib import Path
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit, parse_qs
from playwright.async_api import Error as PlaywrightError
from src.reservation_state import ReservationState, now_kst
from src.recovery import ReservationRecoveryMixin, ResponseError, retry_delay


class CosmaxAutomation(ReservationRecoveryMixin):
    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.current_step = "초기화"
        self.has_captured_screenshot = False
        self.state = ReservationState()
        self.submitted_hours = set()
        self.browser_alerts = {}
        self.dialog_pages = set()
        self.network_pages = set()
        self.network_state = {}
        self.slot_attempts = {}
        self.slot_write_attempts = {}
        self.slot_timing_started = {}
        self.site_timeout_ms = config.get('site_timeout_seconds', 60) * 1000
        self.save_timeout_seconds = config.get('save_timeout_seconds', 60)
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
                    self.get_tab_output_dir(hour), f"{self.artifact_prefix(hour)}_{hour:02d}_failure.png")
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

    async def save_recorded_videos(self, tabs):
        """컨텍스트 종료로 녹화가 끝난 뒤 시간대별 파일명으로 옮긴다."""
        for hour, page in tabs:
            if page.video is None:
                continue
            try:
                source = Path(await page.video.path())
                target = Path(self.get_tab_output_dir(hour)) / (
                    f"video_{self.run_id}_attempt{self.config.get('attempt', 1)}_{hour:02d}.webm")
                source.replace(target)
                self.logger.info(f"🎥 [{hour}시 탭] 동영상 저장: {target}")
            except Exception as error:
                self.logger.warning(f"[{hour}시 탭] 동영상 저장 실패: {error}")

    async def save_stage_screenshot(self, page, hour: int, stage: int, name: str) -> str:
        """현재 뷰포트를 캡처한다. 전체 페이지 캡처는 사이트의 resize 핸들러로 팝업 순서를 바꾼다."""
        if self.config.get("capture_pre_save_screenshots", False) is False:
            return ""
        if not page or page.is_closed():
            self.logger.warning(f"[{hour}시 탭] 단계 {stage:02d} 스크린샷을 저장할 페이지가 없습니다.")
            return ""

        path = os.path.join(
            self.get_tab_output_dir(hour),
            f"{self.artifact_prefix(hour)}_{hour:02d}_{stage:02d}_{name}.png",
        )
        try:
            await page.screenshot(path=path, full_page=False)
            self.logger.info(f"📷 [{hour}시 탭] 단계 {stage:02d} ({name}) 스크린샷 저장: {path}")
            return path
        except Exception as error:
            self.logger.warning(f"[{hour}시 탭] 단계 {stage:02d} ({name}) 스크린샷 저장 실패: {error}")
            return ""

    def record_slot_timing(self, hour: int, event: str):
        """10시 경쟁 구간의 단계별 지연을 단조 시계 기준으로 남긴다."""
        now = time.monotonic()
        started = self.slot_timing_started.setdefault(hour, now)
        self.logger.info(f"[{hour}시 탭] [TIMING] {event}: +{now - started:.3f}초")

    def list_recovery_delay(self, hour: int) -> float:
        hours = sorted(self.config.get('target_hours', [13, 14, 15]))
        if len(hours) == 1:
            return 2
        return 2 + 3 * hours.index(hour) / (len(hours) - 1)

    def monitor_network(self, page, hour: int):
        """예약 조회 요청의 상태를 headless/headful에서 같은 형식으로 기록한다."""
        if page in self.network_pages:
            return
        self.network_pages.add(page)
        self.network_state[page] = {}
        mode = 'headless' if self.config.get('headless', False) else 'headful'

        def relevant(url):
            path = urlsplit(url).path
            return path.endswith(('selectInreservationListNew.do',
                                   'selectInReservationItemListNew.do',
                                   'selectMMIF0015List.do'))

        def on_request(request):
            if request.resource_type not in ('xhr', 'fetch') or not relevant(request.url):
                return
            path = urlsplit(request.url).path
            self.network_state[page][path] = {'failure': '', 'mode': mode}
            self.logger.info(f"[{hour}시 탭] [NETWORK] 요청 {request.method} {path} ({mode})")

        def on_response(response):
            if response.request.resource_type not in ('xhr', 'fetch') or not relevant(response.url):
                return
            path = urlsplit(response.url).path
            headers = response.headers
            safe_headers = ', '.join(
                f'{name}={headers[name]}' for name in ('date', 'retry-after', 'content-type', 'server')
                if headers.get(name)) or '기록할 응답 헤더 없음'
            state = self.network_state[page].setdefault(path, {})
            state.update(status=response.status, headers=safe_headers, mode=mode)
            self.logger.info(
                f"[{hour}시 탭] [NETWORK] 응답 HTTP {response.status} {path} "
                f"({mode}; {safe_headers})")

        def on_failed(request):
            if request.resource_type not in ('xhr', 'fetch') or not relevant(request.url):
                return
            path = urlsplit(request.url).path
            failure = request.failure or '원인 정보 없음'
            self.network_state[page].setdefault(path, {})['failure'] = failure
            self.logger.error(
                f"[{hour}시 탭] [NETWORK] 요청 실패 {request.method} {path} ({mode}): {failure}")

        page.on('request', on_request)
        page.on('response', on_response)
        page.on('requestfailed', on_failed)

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
            await page.wait_for_url(lambda u: "loginForm.do" not in u, timeout=self.site_timeout_ms)
        except Exception:
            try:
                await page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                await page.wait_for_timeout(2000)

    async def calibrate_server_time(self, page):
        """낮은 트래픽 시점에 HTTP Date를 여러 번 측정해 단일 응답 지연 오차를 줄인다."""
        offsets = []
        for _ in range(3):
            started = now_kst()
            try:
                response = await page.request.get(
                    self.config.get("reservation_url", page.url),
                    timeout=self.config.get("keep_alive_timeout_seconds", 3) * 1000)
                finished = now_kst()
                value = response.headers.get("date")
                if response.ok and value and "loginForm.do" not in response.url:
                    server = parsedate_to_datetime(value) + timedelta(milliseconds=500)
                    midpoint = started + (finished - started) / 2
                    offsets.append((server - midpoint).total_seconds())
            except Exception as error:
                self.logger.warning(f"서버 시각 재측정 실패: {error}")
        if offsets:
            self.server_offset_seconds = median(offsets)
            self.logger.info(f"★ HTTP Date 3회 보정 결과: {self.server_offset_seconds:+.3f}초")

    async def verify_session(self, context, page):
        """세션 쿠키(JSESSIONID) 및 현재 URL 확인"""
        cookies = await context.cookies()
        jsessionid = next((c['value'] for c in cookies if c['name'] == 'JSESSIONID'), None)
        if not jsessionid or "loginForm.do" in page.url or await page.locator("#passwd").is_visible():
            raise RuntimeError("로그인 완료를 확인할 수 없습니다. 세션 및 로그인 결과를 확인하세요.")
        self.logger.info(f"★ 세션 인증 확인 완료! (JSESSIONID: {jsessionid})")
        self.logger.info(f"현재 접속 위치: {page.url}")

    async def handle_browser_dialog(self, page, hour, dialog):
        message = ' '.join(dialog.message.split())
        if dialog.type == 'alert':
            self.browser_alerts.setdefault(hour, []).append(message)
        log = self.logger.error if '품목 수 제한' in message else self.logger.info
        log(f"★ [{hour}시 탭] 브라우저 알림/팝업 ({dialog.type}): {message}")
        try:
            await dialog.accept()
        except Exception as error:
            self.logger.warning(f"[{hour}시 탭] 브라우저 팝업 승인 실패: {error}")

    async def prepare_reservation_tab(self, page, hour: int, activate_factory=True):
        """
        개별 탭의 사전 준비 단계:
        1. 브라우저 다이얼로그(alert/confirm) 자동 승인 리스너 등록
        2. 예약 페이지 이동
        3. 필요할 때만 [지류]청북2층 라디오 버튼과 예약 목록 활성화
        """
        tab_label = f"{hour}시 탭"
        self.logger.info(f"[{tab_label}] 예약 탭 준비 시작...")

        async def handle_dialog(dialog):
            await self.handle_browser_dialog(page, hour, dialog)

        if page not in self.dialog_pages:
            page.on("dialog", handle_dialog)
            self.dialog_pages.add(page)
        self.monitor_network(page, hour)

        reservation_url = self.config.get("reservation_url")
        if reservation_url:
            self.logger.info(f"[{tab_label}] 예약 페이지로 이동 중: {reservation_url}")
            await page.goto(reservation_url, wait_until="domcontentloaded")

        if "loginForm.do" in page.url:
            raise RuntimeError(f"[{tab_label}] 예약 페이지가 로그인 화면으로 돌아갔습니다.")
        await self.check_site_notice(page, hour, "예약 페이지 준비")
        if activate_factory:
            await self.activate_reservation_factory(page, hour)
        else:
            self.logger.info(f"[{tab_label}] 로그인·예약 페이지 준비 완료. 목표 시각에 창고·예약 목록을 활성화합니다.")

    async def activate_reservation_factory(self, page, hour: int):
        """목표 시각에 현재 탭에서만 청북2층과 예약 목록을 활성화한다."""
        tab_label = f"{hour}시 탭"
        if "loginForm.do" in page.url:
            raise RuntimeError(f"[{tab_label}] 예약 페이지가 로그인 화면으로 돌아갔습니다.")
        await self.check_site_notice(page, hour, "예약 목록 활성화")
        # jqTransform의 표시용 라디오를 정상 클릭하고 실제 input 선택도 검사한다.
        radio = page.locator('#selFactory1')
        await radio.wait_for(state="attached", timeout=self.site_timeout_ms)
        if not await radio.is_checked():
            self.record_slot_timing(hour, '청북2층 라디오 클릭')
            wrapper = page.locator('.jqTransformRadioWrapper:has(#selFactory1) a.jqTransformRadio')
            if await wrapper.is_visible():
                await wrapper.click(timeout=self.site_timeout_ms)
            else:
                await radio.check(timeout=self.site_timeout_ms)
        if not await radio.is_checked():
            raise RuntimeError(f"[{tab_label}] [지류]청북2층 선택 실패")
        await self.refresh_reservation_list(page, hour)
        self.logger.info(f"[{tab_label}] 로그인·창고·예약 목록 준비 확인 완료")

    async def refresh_reservation_list(self, page, hour):
        self.record_slot_timing(hour, '예약 목록 AJAX 시작')
        response = await self.query_response(
            page, hour, '#btnSelect', '예약 목록 조회',
            '/selectInreservationListNew.do'
        )
        self.record_slot_timing(hour, f'예약 목록 응답 수신 (HTTP {response.status})')
        data = await self.read_json_response(response, "예약 목록 조회", timeout=0)
        if data.get("returnCode") in ("FAIL", "NOSES") or not isinstance(data.get("rows"), list):
            raise RuntimeError(f"[{hour}시 탭] 예약 목록 조회 실패: {data.get('returnMessage', '')}")
        next_log = asyncio.get_running_loop().time() + 10
        while True:
            if "loginForm.do" in page.url or await page.locator("#passwd").is_visible():
                raise RuntimeError(f"[{hour}시 탭] 예약 목록 조회 중 세션이 종료되었습니다.")
            await self.check_site_notice(page, hour, "예약 목록 조회")
            ready = await page.evaluate("""() => {
                const loading = document.querySelector('#load_list');
                const loadingVisible = loading && loading.getClientRects().length;
                const row = document.querySelector('table#list tr[id="1"]');
                const ajaxDone = !window.jQuery || window.jQuery.active === 0;
                return Boolean(row && !loadingVisible && ajaxDone);
            }""")
            if ready:
                break
            if asyncio.get_running_loop().time() >= next_log:
                self.logger.warning(
                    f"[{hour}시 탭] [WAITING] 예약 목록 화면 반영 지연: 조회중 상태가 끝날 때까지 계속 대기")
                next_log += 10
            await asyncio.sleep(.25)
        self.record_slot_timing(hour, '체크박스 화면 반영')
        return data

    async def wait_until_target_time(self, page):
        """한국 시각과 HTTP Date 참고 오차로 대기한다. 마지막 5초에는 ping하지 않는다."""
        h, m, sec = map(int, self.config.get("target_time", "10:00:01").split(":"))
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
                for attempt in range(3):
                    try:
                        response = await page.request.get(page.url, timeout=timeout * 1000)
                        if not response.ok or "loginForm.do" in response.url:
                            raise RuntimeError(f"세션 유지 응답 오류: HTTP {response.status}, {response.url}")
                        break
                    except Exception as error:
                        self.logger.warning(f"[Keep-Alive] 실패 ({attempt + 1}/3): {error}")
                        if attempt == 2:
                            raise RuntimeError("세션 유지 실패: 예약 시작 전 세션 복구가 필요합니다.") from error
                        await asyncio.sleep(min(1, max(0.1, remaining / 10)))
                next_ping = loop.time() + self.config.get("keep_alive_interval_seconds", 30)
            # 네트워크 요청에 걸린 시간을 반영하여 남은 시간을 다시 계산한다.
            remaining = deadline - loop.time()
            if remaining > 0:
                await asyncio.sleep(min(remaining, 0.02 if remaining <= 1 else 1))
        self.logger.info(f"목표 시각 {self.config.get('target_time', '10:00:01')} 도달. 예약을 시작합니다.")

    async def wait_with_progress(self, awaitable, hour, step, page=None, request_path=''):
        """같은 요청을 기다리는 동안 진행 로그를 남긴다. 새 요청은 보내지 않는다."""
        task = asyncio.ensure_future(awaitable)
        elapsed = 0
        try:
            next_log = asyncio.get_running_loop().time() + 10
            while not task.done():
                done, _ = await asyncio.wait({task}, timeout=.25 if page else 10)
                if not done:
                    if page:
                        if "loginForm.do" in page.url or await page.locator("#passwd").is_visible():
                            raise RuntimeError(f"[{hour}시 탭] {step} 중 세션이 종료되었습니다.")
                        await self.check_site_notice(page, hour, step)
                        failure = self.network_state.get(page, {}).get(request_path, {}).get('failure')
                        if failure:
                            raise RuntimeError(f"[{hour}시 탭] {step} 요청 실패: {failure}")
                    if asyncio.get_running_loop().time() >= next_log:
                        elapsed += 10
                        self.logger.warning(f"[{hour}시 탭] [WAITING] {step}: {elapsed}초 응답 지연, 기존 요청 계속 대기")
                        next_log += 10
            return await task
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def query_response(self, page, hour, selector, step, request_path, *, timeout_ms=None, attempts=3):
        """조회중에는 기존 요청을 기다리고, 명확한 HTTP/통신 실패만 재시도한다."""
        self.monitor_network(page, hour)
        timeout_ms = 0 if timeout_ms is None else timeout_ms
        matcher = lambda response: (response.request.method == 'POST'
                                    and urlsplit(response.url).path.endswith(request_path))
        for attempt in range(attempts):
            response = None
            try:
                async with page.expect_response(matcher, timeout=timeout_ms) as info:
                    await self.click_reservation_button(page, hour, selector, step)
                    response = await self.wait_with_progress(
                        info.value, hour, step, page=page, request_path=request_path)
                if not (response.status in (408, 429) or response.status >= 500) or attempt == attempts - 1:
                    return response
                reason = f'HTTP {response.status}'
            except PlaywrightError as error:
                if attempt == attempts - 1:
                    raise
                reason = f'조회 통신 오류: {error}'
            if response is not None and response.status == 429:
                retry_after = response.headers.get('retry-after', '').strip()
                try:
                    delay = max(0, float(retry_after))
                except ValueError:
                    try:
                        retry_at = parsedate_to_datetime(retry_after)
                        delay = max(0, (retry_at - datetime.now(retry_at.tzinfo)).total_seconds())
                    except (TypeError, ValueError):
                        delay = retry_delay(attempt, self.config.get("retry_base_seconds", 2),
                                            self.config.get("retry_max_seconds", 15))
                reason = f'{reason}, Retry-After {retry_after or "없음"}'
            elif response is not None and response.status in (502, 503, 504):
                delay = (self.list_recovery_delay(hour)
                         if request_path == '/selectInreservationListNew.do'
                         else retry_delay(attempt, .5, 1))
            else:
                delay = retry_delay(attempt, self.config.get("retry_base_seconds", 2),
                                    self.config.get("retry_max_seconds", 15))
            self.logger.warning(f"[{hour}시 탭] [RETRY] {step}: {reason}, {delay}초 후 조회 재시도 ({attempt + 2}/{attempts})")
            await asyncio.sleep(delay)

    async def read_json_response(self, response, step, timeout=None):
        if not response.ok:
            raise ResponseError(step, response)
        try:
            if timeout == 0:
                data = await response.json()
            else:
                data = await asyncio.wait_for(
                    response.json(), timeout=timeout or self.site_timeout_ms / 1000)
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
            list_path = '/selectInreservationListNew.do'
            state = self.network_state.get(page, {}).get(list_path, {})
            self.logger.error(
                f"[{hour}시 탭] [NETWORK] 사이트 알림 시점 마지막 목록 요청: {list_path}, "
                f"HTTP={state.get('status', '응답 없음')}, 실패={state.get('failure') or '없음'}, "
                f"모드={state.get('mode', '알 수 없음')}, 헤더={state.get('headers', '없음')}")
            raise RuntimeError(f"[{hour}시 탭] {step}: 사이트 알림 - {message}")

    async def click_reservation_button(self, page, hour: int, selector: str, step: str):
        """가려진 버튼을 우회하지 않고 사이트의 정상 클릭 경로로 진행한다."""
        await self.check_site_notice(page, hour, step)
        try:
            await page.locator(selector).click(timeout=self.site_timeout_ms)
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
            main_count_before = await self.read_material_count(page, hour)
            limit = await self.validate_material_limit(page, hour, main_count_before)
            remaining = limit - main_count_before
            if remaining == 0:
                self.logger.info(f"[{hour}시 탭] 품목 수 한도 도달: 기존 {main_count_before}개 / 허용 {limit}개. 추가·저장 생략")
                return 0
            await self.click_reservation_button(
                page, hour, "#ly_popInreservationMain_btnSelfAdd", step
            )
            await page.locator("#ly_popInreservationSelf").wait_for(state="visible", timeout=self.site_timeout_ms)
            await self.check_site_notice(page, hour, step)
            await self.save_stage_screenshot(page, hour, 3, "self_material_modal_opened")

            step = "자급자재 조회"
            # 진행 중인 조회는 기다리고, 실패한 경우만 현재 모달에서 한 번 다시 조회한다.
            for grid_attempt in range(2):
                try:
                    response = await self.query_response(
                        page, hour, '#ly_popInreservationSelf_btnSelect', step,
                        '/selectMMIF0015List.do',
                        attempts=1,
                    )
                    self.logger.info(f"[{hour}시 탭] 자급자재 조회 응답: HTTP {response.status}")
                    if not response.ok:
                        raise ResponseError(f"[{hour}시 탭] 자급자재 조회", response)
                    data = await self.read_json_response(response, f"[{hour}시 탭] 자급자재 조회", timeout=0)
                    if data.get("returnCode") in ("FAIL", "NOSES"):
                        message = data.get("returnMessage") or "오류 메시지 없음"
                        raise RuntimeError(f"[{hour}시 탭] 자급자재 조회 실패: {data['returnCode']} - {message}")
                    if not isinstance(data.get("rows"), list):
                        raise RuntimeError(f"[{hour}시 탭] 자급자재 조회 응답 형식이 올바르지 않습니다.")
                    if not data["rows"]:
                        raise RuntimeError(f"[{hour}시 탭] 조회된 자급자재가 없습니다.")

                    next_log = asyncio.get_running_loop().time() + 10
                    while True:
                        if "loginForm.do" in page.url or await page.locator("#passwd").is_visible():
                            raise RuntimeError(f"[{hour}시 탭] 자급자재 조회 중 세션이 종료되었습니다.")
                        await self.check_site_notice(page, hour, step)
                        ready = await page.evaluate("""() => {
                            const loading = document.getElementById('load_ly_popInreservationSelf_itemList');
                            return (!loading || !loading.getClientRects().length)
                                && Boolean(document.querySelector('#ly_popInreservationSelf_itemList tr[id] input[type="checkbox"]'));
                        }""")
                        if ready:
                            break
                        if asyncio.get_running_loop().time() >= next_log:
                            self.logger.warning(
                                f"[{hour}시 탭] [WAITING] 자급자재 조회 화면 반영 지연: 조회중 상태가 끝날 때까지 계속 대기")
                            next_log += 10
                        await asyncio.sleep(.25)
                    break
                except (PlaywrightError, ResponseError) as error:
                    if grid_attempt:
                        alerts = self.browser_alerts.get(hour, [])
                        alert = f" / 브라우저 경고: {' / '.join(alerts)}" if alerts else ""
                        raise RuntimeError(
                            f"[{hour}시 탭] 자급자재 조회 화면 반영 지연: 동일 탭 조회 2회 후 체크박스가 나타나지 않았습니다.{alert}"
                        ) from error
                    await self.dismiss_retry_notice(page, hour)
                    self.logger.warning(f"[{hour}시 탭] [RETRY] 자급자재 조회 화면 반영 지연: 현재 탭에서 즉시 재조회 (2/2)")
            await self.save_stage_screenshot(page, hour, 4, "self_materials_loaded")

            step = "자급자재 품목 선택"
            table = page.locator("#ly_popInreservationSelf_itemList")
            checked_count = await table.locator('input[type="checkbox"]:checked').count()
            eligible = table.locator(
                'tr[id]:has(td[aria-describedby="ly_popInreservationSelf_itemList_grctrl"]:text-is("O")) '
                'input[type="checkbox"]:enabled:not(:checked)'
            )
            count = await eligible.count()
            # 일반품목(C2)은 사이트의 소품목 상한보다 많아야 한다.
            minimum_field = page.locator('#ly_popInreservationMain_itemcntLimitC3')
            minimum_text = (await minimum_field.input_value(timeout=self.site_timeout_ms)).strip()
            if not minimum_text.isascii() or not minimum_text.isdigit():
                raise RuntimeError(f"[{hour}시 탭] 일반품목 최소 수량을 확인하지 못했습니다. 저장 생략")
            minimum = int(minimum_text) + 1
            target = self.config.get("material_count_by_hour", {}).get(str(hour))
            if target is not None and not minimum <= target <= limit:
                raise RuntimeError(f"[{hour}시 탭] 설정 종목 수 {target}개가 사이트 허용 범위 {minimum}~{limit}개 밖입니다.")
            desired = min(3, remaining) if target is None else min(3, max(0, target - main_count_before))
            add_count = min(desired, remaining, count)
            if target is not None and main_count_before >= target:
                return 0
            if add_count == 0:
                raise RuntimeError(f"[{hour}시 탭] 추가 가능한 미선택 납품허용 자급자재가 없습니다. (기존 {main_count_before}개 / 허용 {limit}개)")
            if target is not None and main_count_before + add_count < target:
                raise RuntimeError(f"[{hour}시 탭] 목표 {target}개에 필요한 선택 가능 자재가 부족합니다.")
            if main_count_before + add_count <= int(minimum_text):
                raise RuntimeError(f"[{hour}시 탭] 일반품목 최소 수량 미달: 추가 후 {main_count_before + add_count}개 / 최소 {int(minimum_text) + 1}개. 저장 생략")
            expected_count = checked_count + add_count
            self.logger.info(f"[{hour}시 탭] 자동 선택 계산: 기존 {main_count_before}개 / 허용 {limit}개 / 선택 가능 {count}개 → 신규 {add_count}개")
            for _ in range(add_count):
                await self.check_site_notice(page, hour, step)
                # 체크하면 후보에서 빠지므로 매번 첫 번째 미선택 항목을 선택한다.
                await eligible.first.check(timeout=self.site_timeout_ms)
            await self.check_site_notice(page, hour, step)
            if await table.locator('input[type="checkbox"]:checked').count() != expected_count:
                raise RuntimeError(f"[{hour}시 탭] 선택 자재 수가 기대값 {expected_count}개와 다릅니다.")
            self.logger.info(f"[{hour}시 탭] 기존 선택 {checked_count}개 유지, 납품허용 자급자재 {add_count}개 추가 선택 완료 (총 {expected_count}개)")
            await self.save_stage_screenshot(page, hour, 5, "materials_selected")

            step = "선택 자급자재 추가"
            await self.click_reservation_button(
                page, hour, "#ly_popInreservationSelf_btnAdd", step
            )
            await page.wait_for_function("""(previousCount) => {
                const notice = document.getElementById('lyNoti');
                if (notice && notice.getClientRects().length && getComputedStyle(notice).visibility !== 'hidden') return true;
                const subModal = document.getElementById('ly_popInreservationSelf');
                const total = document.getElementById('ly_popInreservationMain_itemcntTotal');
                return subModal && !subModal.getClientRects().length
                    && total && Number(total.value) > previousCount;
            }""", arg=main_count_before, timeout=self.site_timeout_ms)
            await self.check_site_notice(page, hour, step)
            main_count_after = await self.read_material_count(page, hour)
            if main_count_after <= main_count_before:
                raise RuntimeError(f"[{hour}시 탭] 자급자재 추가 후 종목 수가 증가하지 않았습니다. 저장 생략")
            self.logger.info(f"[{hour}시 탭] 메인 예약창 자급자재 추가 완료: 기존 종목 {main_count_before}개 / 체크박스 {add_count}개 추가 / 현재 종목 {main_count_after}개")
            await self.save_stage_screenshot(page, hour, 6, "materials_added_to_main")
            return add_count
        except Exception:
            await self.check_site_notice(page, hour, step)
            raise
        finally:
            page.remove_listener("requestfailed", log_failed_request)
            page.remove_listener("response", log_error_response)

    async def read_material_count(self, page, hour):
        """목록 행 수와 종목 수는 다를 수 있으므로 사이트 표시값을 읽는다."""
        try:
            await page.wait_for_function("""() => {
                const input = document.querySelector('#ly_popInreservationMain_itemcntTotal');
                return input && /^[0-9]+$/.test(input.value.trim());
            }""", timeout=self.site_timeout_ms)
            return int(await page.locator('#ly_popInreservationMain_itemcntTotal').input_value())
        except Exception as error:
            raise RuntimeError(f"[{hour}시 탭] 현재 종목 수를 확인하지 못했습니다. 저장 생략") from error

    async def validate_material_limit(self, page, hour, count):
        """사이트가 조회한 시간대별 한도로 검사한다. 한도를 추측하지 않는다."""
        try:
            await page.wait_for_function("""() => {
                const input = document.querySelector('#ly_popInreservationMain_itemcntLimit');
                return input && /^[0-9]+$/.test(input.value.trim()) && Number(input.value) > 0;
            }""", timeout=self.site_timeout_ms)
            limit = int(await page.locator('#ly_popInreservationMain_itemcntLimit').input_value())
        except Exception as error:
            raise RuntimeError(f"[{hour}시 탭] 품목 수 허용 한도를 확인하지 못했습니다. 저장 생략") from error
        if count > limit:
            raise RuntimeError(
                f"[{hour}시 탭] {hour:02d}:00 시간의 품목 수 제한을 초과 했습니다. "
                f"(현재 종목 {count}개 / 허용 {limit}개). 저장 생략"
            )
        self.logger.info(f"[{hour}시 탭] 품목 수 한도 확인: 현재 {count}개 / 허용 {limit}개")
        return limit

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
        response = await self.query_response(
            page, hour, '#ly_popInreservationMain_btnSelect', '기존 예약 품목 조회',
            '/selectInReservationItemListNew.do'
        )
        data = await self.read_json_response(response, '기존 예약 품목 조회')
        if data.get('returnCode') in ('FAIL', 'NOSES') or not isinstance(data.get('rows'), list):
            raise RuntimeError(f"[{hour}시 탭] 기존 예약 품목 조회 실패: {data.get('returnMessage', '')}")
        await page.wait_for_function("""(count) => {
            const loading = document.querySelector('#load_ly_popInreservationMain_itemList');
            return (!loading || !loading.getClientRects().length)
                && document.querySelectorAll('#ly_popInreservationMain_itemList tr[id]').length === count;
        }""", arg=len(data['rows']), timeout=self.site_timeout_ms)
        await self.check_site_notice(page, hour, '기존 예약 품목 조회')
        self.logger.info(f"[{hour}시 탭] 기존 예약번호 {seq}: 자재 목록 {len(data['rows'])}행 조회 완료, 화면 종목 수로 추가 가능 여부 확인")

    async def reserve_single_slot(self, page, hour: int):
        tab_label = f"{hour}시 탭"
        day = await page.locator('#srchReservDay').input_value()
        try:
            datetime.strptime(day, '%Y%m%d')
        except ValueError as error:
            raise RuntimeError(f"[{tab_label}] 예약일 형식 오류: {day}") from error
        if day < now_kst().strftime('%Y%m%d'):
            raise RuntimeError(f"[{tab_label}] 과거 예약일: {day}")
        expected_day = self.config.get('reservation_date')
        if expected_day and day != expected_day:
            raise RuntimeError(f"[{tab_label}] 예약일 불일치: 화면 {day}, 기대값 {expected_day}")
        account = self.config.get('user_id', '')
        key = self.state.key(account, day, hour)
        dry_run = self.config.get('dry_run', False)
        previous = None
        if not dry_run:
            try:
                # 같은 슬롯의 조회부터 저장까지 한 실행만 소유한다. 다른 시간대는 별개 키다.
                previous = self.state.claim(key, allow_completed=True)
            except RuntimeError:
                active = self.state.get(key)
                if active and active['status'] == 'SUBMITTING':
                    detail = '같은 실행에서 해당 시간대를 처리 중이므로 이번 요청 생략'
                    self.logger.warning(f"[{tab_label}] [SUBMITTING] {detail}")
                    return dict(hour=hour, day=day, status='SUBMITTING', detail=detail)
                else:
                    raise
            self.submitted_hours.discard(hour)
            if previous:
                self.logger.info(f"[{tab_label}] 이전 기록 {previous['status']} / {day}: 현재 체크박스와 품목 수를 다시 확인합니다")
        result = None
        try:
            prior_intent = self.state.get_intent(key) if previous and previous['status'] == 'UNKNOWN' else None
            if prior_intent and (prior_intent.get('retryable_save') or prior_intent.get('retryable_http')):
                self.submitted_hours.add(hour)
                self.slot_write_attempts[hour] = prior_intent.get('save_attempt', 1)
                result = dict(hour=hour, day=day, status='UNKNOWN', detail=previous['detail'])
                result = await self.recover_unknown(page, hour, day, key, result)
                if result['status'] == 'RETRY_READY':
                    result = await self.reserve_with_recovery(page, hour, day, key)
            else:
                result = await self.reserve_with_recovery(page, hour, day, key)
            return result
        finally:
            if not dry_run:
                if result and result['status'] not in ('NO_CHANGE', 'DRY_RUN'):
                    self.state.finish(key, result['status'], result.get('detail', ''))
                elif hour in self.submitted_hours:
                    self.state.finish(key, 'UNKNOWN', '저장 또는 결과 확인 중 실행 중단')
                else:
                    self.state.release(key, previous)

    async def reserve_open_slot(self, page, hour, day, key):
        tab_label = f"{hour}시 탭"
        col_arg = str({8: 1, 9: 2, 10: 3, 11: 4, 13: 5, 14: 6, 15: 7}[hour])
        rows = page.locator('table#list tr[id]').filter(
            has=page.locator('td[aria-describedby="list_facgubn"]', has_text=re.compile(r'^\s*1\s*$'))
        ).filter(
            has=page.locator('td[aria-describedby="list_comptype"]',
                             has_text=re.compile(r'^\s*(?:C2|일반품목)\s*$'))
        )
        row_count = await rows.count()
        if row_count == 0:
            raise RuntimeError(f"[{tab_label}] 청북2층 일반품목 예약 행이 없습니다.")
        if row_count > 1:
            raise RuntimeError(f"[{tab_label}] 청북2층 예약 행이 여러 개여서 처리할 수 없습니다.")
        row = rows.first
        warehouse = await row.locator('[aria-describedby="list_facgubn"]').text_content()
        if warehouse.strip() != '1':
            raise RuntimeError(f"[{tab_label}] 예약 행의 창고가 청북2층이 아닙니다.")
        checkbox = row.locator(f'td[aria-describedby="list_checkYn{col_arg}"] input[type="checkbox"]')
        open_button = row.locator(f'td[aria-describedby="list_cobut{col_arg}"] a')
        async def slot_available():
            return (await checkbox.count() and await checkbox.is_enabled()
                    and await open_button.count() and await open_button.is_visible())
        if not await slot_available():
            await self.check_site_notice(page, hour, '시간대 활성화 대기')
            if not await checkbox.count() or not await open_button.count():
                raise RuntimeError(f"[{tab_label}] 대상 시간대 체크박스가 없습니다. (마감 또는 미오픈)")
            raise RuntimeError(f"[{tab_label}] 대상 시간대 체크박스가 활성화되지 않았습니다. (마감 또는 미오픈)")
        seq = (await row.locator(f'[aria-describedby="list_seq{col_arg}"]').text_content()).strip()
        existing_reservation = bool(seq and seq != '0')
        await checkbox.check(timeout=self.site_timeout_ms)
        await self.save_stage_screenshot(page, hour, 1, "slot_selected")
        await self.check_site_notice(page, hour, '예약 창 열기')
        await open_button.click(timeout=self.site_timeout_ms)
        await self.check_site_notice(page, hour, '예약 창 열기')
        await page.locator('#ly_popInreservationMain').wait_for(state='visible', timeout=self.site_timeout_ms)
        await self.validate_reservation_form(page, hour, day, col_arg)
        if existing_reservation:
            await self.load_existing_materials(page, hour, seq)
        await self.save_stage_screenshot(page, hour, 2, "main_modal_opened")

        # 3~6. 실제 팝업 표시와 조회 완료를 확인하며 자급자재를 추가한다.
        added_count = await self.add_self_materials(page, hour)
        if added_count == 0:
            status = 'EXISTING_CONFIRMED' if existing_reservation else 'NO_CHANGE'
            detail = (f'기존 예약번호 {seq} / 품목 수가 목표 또는 허용 한도에 도달'
                      if existing_reservation else '품목 수가 목표 또는 허용 한도에 도달하여 추가·저장 생략')
            return dict(hour=hour, day=day, status=status, detail=detail)

        # 7. 실제 입력란에 수량을 입력하고 change 이벤트가 발생하도록 포커스를 이동한다.
        await self.check_site_notice(page, hour, "수량 입력")
        for field in ("paletteTotal", "carTotal"):
            control = page.locator(f"#ly_popInreservationMain_{field}")
            if existing_reservation and (await control.input_value()).strip():
                continue
            await control.fill("1", timeout=self.site_timeout_ms)
            await control.press("Tab")
        await self.check_site_notice(page, hour, "수량 입력")
        await self.save_stage_screenshot(page, hour, 7, "quantities_entered")

        await self.validate_reservation_form(page, hour, day, col_arg)
        await self.validate_material_limit(
            page, hour, await self.read_material_count(page, hour)
        )
        if self.config.get('dry_run'):
            self.logger.info(f"[{tab_label}] [DRY_RUN] {day} / {hour}시 / 청북2층 / 일반품목 / 기존 선택 유지 및 자재 {added_count}개 추가 검증 완료. 저장 생략")
            return dict(hour=hour, day=day, status='DRY_RUN')

        self.slot_write_attempts[hour] = self.slot_write_attempts.get(hour, 0) + 1
        owner_control = page.locator(
            '#ly_popInreservationMain_colink, #ly_popInreservationMain input[name="colink"]')
        owner = (await owner_control.first.input_value()).strip() if await owner_control.count() else ''
        intent = dict(materials=await self.snapshot_materials(page), owner=owner,
                      items_url=urljoin(page.url, 'selectInReservationItemListNew.do'),
                      save_attempt=self.slot_write_attempts[hour], retryable_save=False)
        self.state.save_intent(key, intent)
        self.submitted_hours.add(hour)
        result = dict(hour=hour, day=day, status='UNKNOWN', detail='저장 결과 확인 필요')
        responses = []
        self.browser_alerts[hour] = []
        save_requested = False
        save_triggered = False
        rejection_signal = asyncio.get_running_loop().create_future()
        def track_request(request):
            nonlocal save_requested
            if request.method == 'POST' and urlsplit(request.url).path.endswith('/saveInReservationItemListNew.do'):
                save_requested = True
                intent['owner'] = parse_qs(request.post_data or '').get('colink', [''])[0]
                intent['items_url'] = request.url.split('?', 1)[0].replace(
                    '/saveInReservationItemListNew.do', '/selectInReservationItemListNew.do')
                self.state.save_intent(key, intent)
        def collect(response):
            if response.request.method == 'POST' and urlsplit(response.url).path.endswith('/saveInReservationWait.do'):
                responses.append(response)
        def detect_rejection(dialog):
            message = ' '.join(dialog.message.split())
            if (dialog.type == 'alert' and not save_requested and not rejection_signal.done()
                    and '품목 수 제한' in message and ('초과' in message or '미달' in message)):
                rejection_signal.set_result(message)
        async def response_or_rejection(awaitable):
            response_task = asyncio.ensure_future(awaitable)
            try:
                done, _ = await asyncio.wait(
                    {response_task, rejection_signal}, return_when=asyncio.FIRST_COMPLETED)
                if response_task in done:
                    return await response_task
                if rejection_signal in done:
                    raise RuntimeError(rejection_signal.result())
            finally:
                if not response_task.done():
                    response_task.cancel()
                await asyncio.gather(response_task, return_exceptions=True)
        page.on('response', collect)
        page.on('request', track_request)
        page.on('dialog', detect_rejection)
        try:
            async with page.expect_response(
                lambda r: r.request.method == 'POST' and urlsplit(r.url).path.endswith('/saveInReservationItemListNew.do'),
                timeout=self.save_timeout_seconds * 1000
            ) as info:
                # 이후 성공 안내도 lyNoti를 쓰므로 클릭 직후의 일반 오류 검사는 하지 않는다.
                await self.check_site_notice(page, hour, '예약 저장 전')
                save_triggered = True
                await page.locator('#ly_popInreservationMain_btnSave').click(timeout=self.site_timeout_ms)
                response = await self.wait_with_progress(response_or_rejection(info.value), hour, '예약 저장 응답')
            data = await self.wait_with_progress(
                self.read_json_response(response, '예약 저장', self.save_timeout_seconds), hour, '예약 저장 응답 본문'
            )
            code = data.get('returnCode')
            self.logger.info(f"[{tab_label}] 저장 응답: {code} / {data.get('returnMessage', '')}")
            if code not in ('SUCCESS', 'WAIT'):
                detail = str(data.get('returnMessage') or f'알 수 없는 저장 응답: {code}')
                terminal = code in ('FAIL', 'NOSES') and any(
                    word in detail for word in ('마감', '한도', '초과', '미달', '권한', '불가'))
                result.update(status='FAILED' if terminal else 'UNKNOWN', detail=detail)
                if terminal:
                    result['retryable'] = False
                intent['retryable_save'] = not terminal
                self.state.save_intent(key, intent)
                await self.capture_failure_screenshot(
                    page, RuntimeError(detail), '예약_저장_응답', hour)
                return result
            status = 'CONFIRMED'
            if code == 'WAIT':
                wait_data = data.get('returnCosmaxData') or {}
                if not (wait_data.get('seq') and wait_data.get('seq') == wait_data.get('waitSeq')):
                    deadline = asyncio.get_running_loop().time() + self.save_timeout_seconds
                    next_log = asyncio.get_running_loop().time() + 10
                    while not responses:
                        if asyncio.get_running_loop().time() >= deadline:
                            raise RuntimeError('대기 등록 후속 저장 응답 미확인')
                        if asyncio.get_running_loop().time() >= next_log:
                            self.logger.warning(f"[{tab_label}] [WAITING] 대기 등록 후속 응답 지연, 재저장 없이 계속 대기")
                            next_log += 10
                        await asyncio.sleep(0.05)
                    followup = await self.wait_with_progress(
                        self.read_json_response(responses[0], '대기 등록', self.save_timeout_seconds), hour, '대기 등록 응답 본문'
                    )
                    if followup.get('returnCode') != 'SUCCESS':
                        raise RuntimeError(f"대기 등록 실패: {followup.get('returnMessage', '')}")
                status = 'WAIT'
            # 정상 안내 문구만 닫고, 새 서버 조회로 예약번호와 업체를 대조한다.
            await page.wait_for_function("""() => {
                const el=document.querySelector('#lyNoti');
                return el && el.getClientRects().length && (el.textContent.includes('등록') || el.textContent.includes('확정'));
            }""", timeout=self.site_timeout_ms)
            notice_text = await page.locator('#lyNoti').text_content()
            self.logger.info(f"[{tab_label}] 저장 완료 안내: {notice_text.strip()}")
            await self.save_stage_screenshot(page, hour, 8, 'save_notice')
            expected = '입고 예약이 확정' if status == 'CONFIRMED' else '입고예약 대기'
            if expected not in notice_text or f'[{hour:02d}:00]' not in notice_text:
                raise RuntimeError(f'예상하지 않은 저장 알림: {notice_text}')
            await page.locator('#lyNoti .pop_btnclose').click(timeout=self.site_timeout_ms)
            active_tab = await page.locator('.tabWrap ul li.active a').get_attribute('id')
            if active_tab != ('atab1' if status == 'CONFIRMED' else 'atab2'):
                raise RuntimeError('저장 후 확정/대기 목록 탭이 예상과 다릅니다.')
            data = await self.refresh_reservation_list(page, hour)
            owner = intent['owner'] or parse_qs(response.request.post_data or '').get('colink', [''])[0]
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
            alerts = self.browser_alerts.get(hour, [])
            rejection = next((message for message in alerts
                              if '품목 수 제한' in message and ('초과' in message or '미달' in message)), None)
            if rejection and not save_requested:
                result.update(status='FAILED', detail=f'{rejection} / 저장 요청 미전송')
            else:
                result['detail'] = (f"브라우저 경고: {' / '.join(alerts)} / " if alerts else '') + str(error)
            # 저장 클릭 뒤에는 저장 응답을 먼저 기다린다. 응답이 없거나 오류일 때만
            # 서버 내역을 재조회해 실제 저장 여부를 확인한다.
            intent['retryable_save'] = save_requested and not (rejection and not save_requested)
            intent['retryable_http'] = save_triggered and not save_requested
            self.state.save_intent(key, intent)
            self.logger.error(f"[{tab_label}] [{result['status']}] {result['detail']}. 서버 결과를 재조회합니다.")
            failure = RuntimeError(result['detail']).with_traceback(error.__traceback__)
            await self.capture_failure_screenshot(page, failure, '예약_저장', hour)
            return result
        finally:
            page.remove_listener('response', collect)
            page.remove_listener('request', track_request)
            page.remove_listener('dialog', detect_rejection)
            rejection_signal.cancel()
            await self.save_stage_screenshot(page, hour, 9, 'reservation_result')


async def execute_automation(config: dict, logger: logging.Logger):
    """
    Playwright 초고속 멀티탭 병렬 예약 오케스트레이션
    - 리소스 차단(폰트/미디어)으로 3개 탭 기동 가속
    - 1회 로그인 후 13시, 14시, 15시 3개 탭 생성
    - 서버 시계 목표 시각에 각 시간대 예약을 병렬 트리거 (asyncio.gather)
    - 시간대별 최종 화면 저장
    """
    from playwright.async_api import async_playwright

    automation = CosmaxAutomation(config, logger)
    target_hours = config.get("target_hours", [13, 14, 15])

    async with async_playwright() as p:
        browser = None
        context = None
        tabs = []  # [(hour, page), ...]
        record_video = config.get('record_video', False) and not config.get('headless', False)

        try:
            # 1. 브라우저 및 컨텍스트 생성 (세션 쿠키 공유)
            browser = await automation.launch_browser(p)
            vp_w = config.get("viewport_width", 2200)
            vp_h = config.get("viewport_height", 1080)
            context_options = dict(
                viewport={"width": vp_w, "height": vp_h} if config.get("headless", False) else None,
                no_viewport=not config.get("headless", False),
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            if record_video:
                # 종료 시 각 탭의 파일을 해당 시간대 폴더로 옮긴다.
                context_options.update(record_video_dir=automation.get_tab_output_dir(target_hours[0]),
                                       record_video_size={"width": 1920, "height": 1080})
                logger.info("동영상 녹화 활성화: 사이트 화면을 시간대별로 기록합니다.")
            elif config.get('record_video'):
                logger.info("headless=true이므로 동영상 녹화를 생략합니다.")
            context = await browser.new_context(**context_options)
            context.set_default_timeout(automation.site_timeout_ms)
            context.set_default_navigation_timeout(automation.site_timeout_ms)

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
            await automation.calibrate_server_time(main_page)

            # 3. 추가 시간대(14시, 15시 등)를 위한 병렬 탭 동시 생성 (동일 context 내 세션 공유)
            for hr in target_hours[1:]:
                tab_page = await context.new_page()
                tabs.append((hr, tab_page))
                await automation.set_maximized(context, tab_page)

            # 시간대별로 준비 → 목표 시각 대기 → 예약 → 결과 기록을 독립 수행한다.
            logger.info(f"[Step 5] 시간대 {target_hours} 독립 실행 시작")
            ready_hours = set()
            prep_errors = []
            session_recovery_lock = asyncio.Lock()

            async def run_tab(hour, page):
                h, m, sec = map(int, config.get('target_time', '10:00:01').split(':'))
                current = now_kst() + timedelta(seconds=automation.server_offset_seconds)
                target = current.replace(hour=h, minute=m, second=sec, microsecond=0)
                retry_window = config.get('reservation_retry_window_seconds', 0)
                retry_deadline = asyncio.get_running_loop().time() + max(
                    0, (target - current).total_seconds()) + retry_window
                attempt = 0
                unavailable_attempts = 0
                blank_notice_attempts = 0
                needs_navigation = True
                factory_active = False
                target_waited = False
                while True:
                    blank_notice = False
                    staggered_recovery = False
                    try:
                        if needs_navigation:
                            phase = '사전_준비'
                            await automation.prepare_reservation_tab(page, hour, activate_factory=False)
                            ready_hours.add(hour)
                            needs_navigation = False
                        phase = '목표_시각_대기'
                        if not config.get('dry_run') and not target_waited:
                            logger.info(f"[{hour}시 탭] [Step 6] 목표 시각 {config.get('target_time')} 대기")
                            await automation.wait_until_target_time(page)
                            target_waited = True
                        if not factory_active:
                            phase = '예약_목록_활성화'
                            await automation.activate_reservation_factory(page, hour)
                            factory_active = True
                        elif attempt:
                            phase = '현재_탭_복구'
                            await automation.dismiss_retry_notice(page, hour)
                            await automation.refresh_reservation_list(page, hour)
                        phase = '예약_처리'
                        logger.info(f"[{hour}시 탭] [Step 7] 현재 시간대 예약 처리 시작")
                        result = await automation.reserve_single_slot(page, hour)
                    except Exception as error:
                        if phase == '사전_준비':
                            prep_errors.append(error)
                        await automation.capture_failure_screenshot(page, error, phase, hour)
                        detail = str(error)
                        unavailable = ('대상 시간대 체크박스가 없습니다.' in detail
                                       or '대상 시간대 체크박스가 활성화되지 않았습니다.' in detail)
                        blank_notice = '내용 없는 알림' in detail
                        staggered_recovery = (blank_notice
                                              or '예약 목록 조회 요청 실패' in detail)
                        terminal_layout = ('청북2층 예약 행이 여러 개' in detail
                                           or '청북2층 일반품목 예약 행이 없습니다.' in detail)
                        if unavailable:
                            unavailable_attempts += 1
                        if blank_notice:
                            blank_notice_attempts += 1
                        result = dict(hour=hour,
                                      status='UNKNOWN' if hour in automation.submitted_hours else 'FAILED',
                                      detail=detail)
                        if unavailable:
                            result['retryable'] = unavailable_attempts < 2
                        if blank_notice:
                            result['retryable'] = blank_notice_attempts < 2
                        if terminal_layout or '자급자재 조회 화면 반영 지연' in detail:
                            result['retryable'] = False
                    if (config.get('dry_run') or result.get('retryable') is False
                            or result['status'] not in ('FAILED', 'UNKNOWN', 'SUBMITTING')
                            or asyncio.get_running_loop().time() >= retry_deadline):
                        break
                    attempt += 1
                    if blank_notice:
                        await automation.dismiss_retry_notice(page, hour)
                    if "loginForm.do" in page.url or await page.locator("#passwd").is_visible():
                        try:
                            async with session_recovery_lock:
                                if "loginForm.do" in page.url or await page.locator("#passwd").is_visible():
                                    logger.warning(f"[{hour}시 탭] 세션 만료 확인: 다시 로그인합니다")
                                    await automation.perform_login(page)
                                    await automation.verify_session(context, page)
                                    needs_navigation = True
                                    factory_active = False
                        except Exception as error:
                            logger.warning(f"[{hour}시 탭] 재로그인 실패: {error}")
                    if staggered_recovery:
                        delay = automation.list_recovery_delay(hour)
                    else:
                        retry_base, retry_max = ((0.5, 1) if phase == '예약_목록_활성화' else (1, 15))
                        delay = retry_delay(attempt, retry_base, retry_max)
                    delay = min(delay, max(0, retry_deadline - asyncio.get_running_loop().time()))
                    if delay <= 0:
                        break
                    logger.warning(
                        f"[{hour}시 탭] [RETRY] {result['status']} 복구: {delay:.1f}초 후 "
                        f"해당 시간대만 다시 시도 ({result.get('detail', '')})")
                    await asyncio.sleep(delay)
                # 다른 탭의 대기/실패와 관계없이 해당 탭 결과를 즉시 기록한다.
                logger.info(f"[{hour}시 탭] [RESULT] {result}")
                await automation.save_final_screenshot(page, hour)
                return result

            results = await asyncio.gather(*(run_tab(hour, page) for hour, page in tabs), return_exceptions=True)
            outcomes = []
            for (hour, _), result in zip(tabs, results):
                if isinstance(result, Exception):
                    logger.error(f"[{hour}시 탭] 결과 기록 실패: {result}")
                    result = dict(hour=hour, status='UNKNOWN' if hour in automation.submitted_hours else 'FAILED',
                                  detail=str(result))
                outcomes.append(result)
            if not ready_hours and prep_errors:
                raise RuntimeError(f"모든 시간대({target_hours}) 사전 준비 실패: {prep_errors}") from prep_errors[0]
            return outcomes

        except Exception as exc:
            if not automation.has_captured_screenshot:
                fallback_page = tabs[0][1] if tabs else None
                await automation.capture_failure_screenshot(fallback_page, exc)
            if automation.submitted_hours:
                return [dict(hour=hr, status="UNKNOWN", detail=str(exc)) for hr in target_hours]
            raise
        finally:
            if context:
                try:
                    # 녹화 파일은 context.close()를 기다려야 완성된다.
                    await context.close()
                    if record_video:
                        await automation.save_recorded_videos(tabs)
                except Exception as error:
                    logger.warning(f"브라우저 컨텍스트 종료/녹화 마무리 실패: {error}")
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
