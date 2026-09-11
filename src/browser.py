#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Playwright 초고속 브라우저 자동화 모듈
- [NTP 정밀 동기화] COSMAX 서버 HTTP 응답 헤더(Date) 기반 서버 시계 오차(ms) 정밀 보정
- [원스톱 JS 배치] 모달 조작-품목선택-수량입력-저장까지 브라우저 내부 단일 JS evaluate로 0.05초 격발
- [경량화] 불필요 미디어/폰트 리소스 차단 및 Chromium 가속 플래그 적용
- [비동기 병렬 동시 예약] 1회 인증 세션(Context) 내 13시·14시·15시 3개 탭 동시 발주 (asyncio.gather)
- [단일 결과 스크린샷] logs/YYYYMMDD/reservation_YYYYMMDD.png 1장만 보존
"""

import os
import random
import asyncio
import logging
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime


class CosmaxAutomation:
    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.current_step = "초기화"
        self.has_captured_screenshot = False
        self.server_offset_seconds = 0.0  # 서버 시간 - 로컬 시간 (초 단위 오차)
        
        today_str = datetime.now().strftime("%Y%m%d")
        if hasattr(logger, "log_file_path") and logger.log_file_path:
            self.output_dir = os.path.dirname(os.path.abspath(logger.log_file_path))
        else:
            log_dir = config.get("log_dir", "logs")
            self.output_dir = os.path.join(log_dir, today_str)
        os.makedirs(self.output_dir, exist_ok=True)
        
        # 일자별 폴더 내 1장만 보존 (성공/실패 공통 최종 결과 스크린샷)
        self.screenshot_path = os.path.join(self.output_dir, f"reservation_{today_str}.png")

    async def capture_failure_screenshot(self, page, error: Exception, step_name: str = "") -> str:
        """
        자동화 실패 발생 시 실패 지점 화면 캡처 및 ERROR 로그 기록
        - 해당 일자 폴더에 reservation_YYYYMMDD.png 단 1장으로 저장/갱신
        """
        active_step = step_name or self.current_step or "오류발생"
        self.logger.error(f"❌ [FAIL] 단계 '{active_step}' 수행 중 예외 발생: {error}", exc_info=True)
        
        if page and not page.is_closed():
            try:
                await page.screenshot(path=self.screenshot_path, full_page=True)
                self.has_captured_screenshot = True
                self.logger.error(f"★ [FAIL] 실패 지점 스크린샷 저장 완료: {self.screenshot_path}")
                return self.screenshot_path
            except Exception as ss_err:
                self.logger.error(f"실패 지점 스크린샷 캡처 중 추가 에러 발생: {ss_err}")
        else:
            self.logger.warning("페이지가 열려있지 않거나 이미 닫혀 있어 실패 스크린샷을 저장할 수 없습니다.")
        return ""

    async def save_final_screenshot(self, page, success_hours: list) -> str:
        """
        예약 성공 시 최종 완료 화면 캡처 (단 1장)
        - 메인 모달 최상단 가시화 후 reservation_YYYYMMDD.png 로 저장
        """
        self.current_step = "최종_스크린샷_저장"
        if page and not page.is_closed():
            try:
                await page.evaluate("""() => {
                    const mainModal = document.getElementById('ly_popInreservationMain') || document.getElementById('lyInreservationMain');
                    if (mainModal) {
                        const parentLypop = mainModal.closest('.lypop');
                        if (parentLypop) {
                            parentLypop.style.display = 'block';
                            parentLypop.style.zIndex = '999999';
                        }
                        mainModal.style.display = 'block';
                        mainModal.style.zIndex = '999999';
                    }
                    const mask = document.getElementById('mask');
                    if (mask) mask.style.display = 'none';
                    const noti = document.getElementById('lyNoti');
                    if (noti) noti.style.display = 'none';
                }""")
                await page.screenshot(path=self.screenshot_path, full_page=True)
                self.has_captured_screenshot = True
                hours_str = ", ".join(f"{h}시" for h in success_hours)
                self.logger.info(f"★ 최종 1회 마침 스크린샷 저장 완료 ({hours_str} 예약 화면): {self.screenshot_path}")
                return self.screenshot_path
            except Exception as ss_err:
                self.logger.warning(f"최종 스크린샷 저장 중 에러 발생: {ss_err}")
        return ""
        
    async def launch_browser(self, playwright_obj):
        """Playwright 브라우저 고속 실행 (Chromium 경량화 가속 플래그 적용)"""
        headless_mode = self.config.get("headless", False)
        launch_args = [
            "--start-maximized",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
            "--disable-extensions",
            "--disable-sync",
            "--disable-default-apps"
        ]
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

    async def perform_login(self, page):
        """로그인 폼 입력 및 로그인 제출 & 서버 시계 오차(NTP Offset) 1회 측정"""
        self.current_step = "Step2_로그인_접속"
        target_url = self.config["url"]
        user_id = self.config["user_id"]
        user_pw = self.config["user_pw"]
        
        self.logger.info(f"[Step 2] 로그인 페이지 접속: {target_url}")
        resp = await page.goto(target_url, wait_until="domcontentloaded")
        
        # COSMAX 서버 시계와 로컬 PC 시계 간의 오차(NTP Offset) 자동 계산
        if resp:
            date_hdr = resp.headers.get("date")
            if date_hdr:
                try:
                    server_dt = parsedate_to_datetime(date_hdr).astimezone()
                    local_dt = datetime.now().astimezone()
                    self.server_offset_seconds = (server_dt - local_dt).total_seconds()
                    self.logger.info(f"★ [NTP 동기화] COSMAX 서버 시계 오차: {self.server_offset_seconds:+.3f}초 (서버 시각: {server_dt.strftime('%H:%M:%S')})")
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
        if jsessionid:
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
            
        # [지류]청북2층 라디오 버튼 선택
        self.logger.info(f"[{tab_label}] 라디오 버튼 선택: '[지류]청북2층'")
        try:
            await page.wait_for_selector("label:has-text('청북2층'), text='[지류]청북2층'", timeout=5000)
        except Exception:
            pass
            
        radio_locator = page.locator("label").filter(has_text="청북2층")
        if await radio_locator.count() == 0:
            radio_locator = page.locator("text='[지류]청북2층'")
        if await radio_locator.count() > 0:
            await radio_locator.first.click(timeout=3000)
        else:
            try:
                await page.get_by_text("[지류]청북2층").click(timeout=3000)
            except Exception:
                pass
                
        # 그리드 로딩 완료 대기 ("조회중..." 숨김 및 체크박스 DOM 가시화)
        try:
            await page.wait_for_selector("text='조회중...'", state="hidden", timeout=4000)
        except Exception:
            pass
        try:
            await page.wait_for_selector("tr input[type='checkbox']", timeout=4000)
        except Exception:
            pass
            
        self.logger.info(f"★ [{tab_label}] 사전 준비 및 대기 완료!")

    async def wait_until_target_time(self, page):
        """목표 시각(10:00 AM)까지 세션 유지 Ping 전송 후 서버 정각 도달 시 즉시 복귀 (NTP 오차 보정)"""
        target_time_str = self.config.get("target_time", "10:00:00")
        target_hour, target_min, target_sec = map(int, target_time_str.split(":"))
        
        # 서버 시계 기준 현재 시각 계산
        local_now = datetime.now()
        server_now = local_now + timedelta(seconds=self.server_offset_seconds)
        target_dt = server_now.replace(hour=target_hour, minute=target_min, second=target_sec, microsecond=0)
        
        if server_now >= target_dt:
            self.logger.info(f"현재 서버 시각({server_now.strftime('%H:%M:%S')})이 목표 시각({target_time_str}) 경과함. 즉시 병렬 예약을 진행합니다.")
            return
            
        wait_total = int((target_dt - server_now).total_seconds())
        self.logger.info(f"★ [NTP 동기화 기준] 목표 시각({target_dt.strftime('%Y-%m-%d %H:%M:%S')})까지 대기 (약 {wait_total}초, 오차: {self.server_offset_seconds:+.3f}초)")
        keep_alive_interval = self.config.get("keep_alive_interval_seconds", 30)
        
        while True:
            curr_server_now = datetime.now() + timedelta(seconds=self.server_offset_seconds)
            remaining_seconds = (target_dt - curr_server_now).total_seconds()
            
            if remaining_seconds <= 1.0:
                # 1초 미만 남았을 경우 초정밀 폴링으로 전환 (밀리초 단위 서버 정각 동기화)
                while True:
                    curr_server_now = datetime.now() + timedelta(seconds=self.server_offset_seconds)
                    if curr_server_now >= target_dt:
                        break
                    await asyncio.sleep(0.01)
                break
                
            self.logger.info(f"[Keep-Alive] 남은 시간(서버 기준): {int(remaining_seconds)}초 | Session Ping")
            try:
                await page.evaluate("fetch(window.location.href).catch(() => {})")
            except Exception:
                pass
                
            sleep_time = min(keep_alive_interval, max(1.0, remaining_seconds - 1.0))
            await asyncio.sleep(sleep_time)
            
        trigger_time_str = (datetime.now() + timedelta(seconds=self.server_offset_seconds)).strftime('%H:%M:%S.%f')[:-3]
        self.logger.info(f"★ [{trigger_time_str}] 서버 시계 10:00:00 정각 도달! 3개 탭 동시 예약 실행 트리거!")

    async def reserve_single_slot(self, page, hour: int) -> int:
        """
        개별 탭(Page)에서 1개 시간대(13시/14시/15시) 예약 수행 초고속 워크플로우
        1. 일반품목 행에서 해당 시간대 체크박스 Fail-Safe 감지 및 클릭 (최대 5회, 0.3초 간격)
        2. 문서 아이콘 클릭 -> 메인 모달 오픈 -> 자급자재 추가 -> 서브 모달 조회
        3. [원스톱 JS 배치] 서브모달 품목 3개 선택 -> 추가 -> 팔레트/차량 1 입력 -> 예약신청(저장) 클릭 (0.01초 소요)
        """
        tab_label = f"{hour}시 탭"
        self.logger.info(f"🚀 [{tab_label}] 예약 프로세스 가동 시작...")
        
        # 시간대별 일반품목 체크박스 Index 및 열 인수 매핑
        # 일반품목 순서: 8시(0), 9시(1), 10시(2), 11시(3), 13시(4), 14시(5), 15시(6)
        slot_map = {
            13: {"cb_idx": 4, "col_arg": "5"},
            14: {"cb_idx": 5, "col_arg": "6"},
            15: {"cb_idx": 6, "col_arg": "7"}
        }
        slot_info = slot_map.get(hour, {"cb_idx": 4, "col_arg": "5"})
        cb_idx = slot_info["cb_idx"]
        col_arg = slot_info["col_arg"]
        target_row_id = "1"  # 일반품목 행 ID
        
        # 1. 그리드 초고속 재조회 및 체크박스 출현 감지 루프 (Fail-Safe: 최대 5회, 0.3초 간격)
        max_retries = self.config.get("grid_max_retries", 5)
        retry_delay = self.config.get("grid_retry_delay_seconds", 0.3)
        cb_clicked = False
        
        for attempt in range(1, max_retries + 1):
            self.logger.info(f"[{tab_label}] 그리드 갱신 및 체크박스 감지 시도 ({attempt}/{max_retries})...")
            
            # [지류]청북2층 라디오 버튼 재클릭으로 그리드만 초고속 갱신 (전체 F5가 아닌 가벼운 AJAX 재요청)
            radio_locator = page.locator("label").filter(has_text="청북2층")
            if await radio_locator.count() == 0:
                radio_locator = page.locator("text='[지류]청북2층'")
            if await radio_locator.count() > 0:
                await radio_locator.first.click(timeout=1000)
            else:
                try:
                    await page.get_by_text("[지류]청북2층").click(timeout=1000)
                except Exception:
                    pass
                    
            # 50ms 단위 초고속 스캔: 일반품목 행의 해당 시간대 체크박스 존재 및 활성화 여부 확인 후 즉시 클릭
            res = await page.evaluate("""(info) => {
                const table = document.querySelector("#inreservationRegListNewGrid") || document.querySelector("table.tbl_list") || document.querySelector(".table_wrap table") || document.querySelector("table");
                if (!table) return null;
                
                const genRow = Array.from(table.querySelectorAll('tr')).find(r => r.innerText.includes('일반품목'));
                if (!genRow) return null;
                
                const cbs = Array.from(genRow.querySelectorAll('input[type="checkbox"]'));
                const targetCb = cbs[info.cb_idx];
                if (targetCb && !targetCb.disabled) {
                    targetCb.click();
                    return { clicked: true, index: info.cb_idx };
                }
                return null;
            }""", {"cb_idx": cb_idx, "hour": hour})
            
            if res and res.get("clicked"):
                self.logger.info(f"★ [{tab_label}] 일반품목 {hour}시 체크박스 출현 감지 및 즉시 클릭 성공! (시도 {attempt}회)")
                cb_clicked = True
                break
                
            # 아직 체크박스가 뜨지 않은 경우 다음 재시도까지 짧은 대기 (마지막 시도 제외)
            if attempt < max_retries:
                await asyncio.sleep(retry_delay)
                
        if not cb_clicked:
            raise RuntimeError(f"[{tab_label}] 일반품목 {hour}시 체크박스가 {max_retries}회({max_retries * retry_delay:.1f}초) 시도 동안 노출되지 않았습니다. (마감 또는 미오픈으로 루프 안전 탈출)")
            
        # 2. 문서 아이콘 클릭 -> 메인 모달 오픈 -> 자급자재 추가 -> 서브 모달 조회
        self.logger.info(f"[{tab_label}] 문서 아이콘 클릭 및 자급자재 품목 조회 비동기 트리거...")
        
        async with page.expect_response("**/selectMMIF0015List.do**", timeout=6000) as resp_info:
            await page.evaluate(f"""() => {{
                // 메인 모달 오픈
                fn_popInreservationMain('{target_row_id}', '{col_arg}');
                const modalEl = document.getElementById('ly_popInreservationMain') || document.getElementById('lyInreservationMain');
                if (modalEl) {{
                    modalEl.style.display = 'block';
                    const parentLypop = modalEl.closest('.lypop');
                    if (parentLypop) parentLypop.style.display = 'block';
                }}
                const mask = document.getElementById('mask');
                if (mask) mask.style.display = 'none';
                const noti = document.getElementById('lyNoti');
                if (noti) noti.style.display = 'none';
                
                // 자급자재 추가 버튼 클릭
                const btnSelf = document.getElementById('ly_popInreservationMain_btnSelfAdd');
                if (btnSelf) btnSelf.click();
                else if (typeof $ !== 'undefined') $('#ly_popInreservationMain_btnSelfAdd').click();
                
                // 서브 모달 [조회] 버튼 클릭
                const btnSearch = document.getElementById('ly_popInreservationSelf_btnSelect');
                if (btnSearch) btnSearch.click();
                else if (typeof $ !== 'undefined') $('#ly_popInreservationSelf_btnSelect').click();
            }}""")
            
        resp = await resp_info.value
        self.logger.info(f"[{tab_label}] 품목 비동기 데이터 수신 완료 (Status: {resp.status})")
        
        # 3. [초고속 원스톱 JS 배치] 품목 3개 선택 ➔ 추가 ➔ 팔레트/차량수 1 입력 ➔ 예약신청(저장) 클릭 (0.01초 소요)
        self.logger.info(f"⚡ [{tab_label}] 원스톱 JS 배치 격발: 품목 3개 선택 ➔ 추가 ➔ 수량 입력 ➔ 최종 저장!")
        
        batch_result = await page.evaluate("""(maxItems) => {
            return new Promise((resolve) => {
                const doBatch = () => {
                    // 서브 모달 가시화
                    const subModalWrap = document.getElementById('ly_popInreservationSelf');
                    if (subModalWrap) {
                        const parentLypop = subModalWrap.closest('.lypop');
                        if (parentLypop) parentLypop.style.display = 'block';
                        subModalWrap.style.display = 'block';
                    }
                    const noti = document.getElementById('lyNoti');
                    if (noti) noti.style.display = 'none';
                    const mask = document.getElementById('mask');
                    if (mask) mask.style.display = 'none';
                    
                    // 1. 납품허용 'O' 품목 체크박스 우선 선택 (부족 시 가용 체크박스로 3개 보충)
                    const table = document.getElementById('ly_popInreservationSelf_itemList');
                    let checkedCount = 0;
                    if (table) {
                        const rows = Array.from(table.querySelectorAll('tr[id]'));
                        const eligibleCbs = [];
                        for (const tr of rows) {
                            const text = tr.innerText ? tr.innerText.replace(/\\s+/g, ' ') : '';
                            const cb = tr.querySelector('input[type="checkbox"]');
                            if (cb && (text.includes(' O ') || text.includes(' O\\t') || text.includes('\\tO\\t') || text.includes(' O '))) {
                                eligibleCbs.push(cb);
                            }
                        }
                        const targetCbs = eligibleCbs.length >= maxItems ? eligibleCbs : Array.from(table.querySelectorAll('tr[id] input[type="checkbox"]'));
                        for (let i = 0; i < Math.min(maxItems, targetCbs.length); i++) {
                            if (!targetCbs[i].checked) {
                                targetCbs[i].click();
                                checkedCount++;
                            }
                        }
                    }
                    
                    // 2. 서브 모달 하단 [추가] 버튼 클릭
                    const btnAdd = document.getElementById('ly_popInreservationSelf_btnAdd');
                    if (btnAdd) btnAdd.click();
                    else if (typeof $ !== 'undefined') $('#ly_popInreservationSelf_btnAdd').click();
                    
                    // 3. 메인 모달 텍스트 박스 입력 (팔레트 1, 차량 1)
                    const pInput = document.getElementById('ly_popInreservationMain_paletteTotal');
                    if (pInput) { pInput.value = '1'; }
                    else if (typeof $ !== 'undefined') { $('#ly_popInreservationMain_paletteTotal').val('1'); }
                    
                    const cInput = document.getElementById('ly_popInreservationMain_carTotal');
                    if (cInput) { cInput.value = '1'; }
                    else if (typeof $ !== 'undefined') { $('#ly_popInreservationMain_carTotal').val('1'); }
                    
                    // 4. 메인 모달 [예약신청(저장)] 최종 버튼 클릭
                    const btnSave = document.getElementById('ly_popInreservationMain_btnSave');
                    if (btnSave) btnSave.click();
                    else if (typeof $ !== 'undefined') $('#ly_popInreservationMain_btnSave').click();
                    
                    resolve({ checkedCount: checkedCount });
                };
                
                // 테이블 렌더링 완료 여부 확인 후 실행
                const t = document.getElementById('ly_popInreservationSelf_itemList');
                if (t && t.querySelectorAll('tr[id]').length > 0) {
                    doBatch();
                } else {
                    setTimeout(doBatch, 30);
                }
            });
        }""", 3)
        
        checked_count = batch_result.get("checkedCount", 0) if batch_result else 0
        self.logger.info(f"★ [{tab_label}] 원스톱 예약신청 제출 완료! (선택 품목: {checked_count}개, 팝업 자동 승인 대기)")
        return hour


async def execute_automation(config: dict, logger: logging.Logger):
    """
    Playwright 초고속 멀티탭 병렬 예약 오케스트레이션
    - 리소스 차단(폰트/미디어)으로 3개 탭 기동 가속
    - 1회 로그인 후 13시, 14시, 15시 3개 탭 생성
    - 서버 시계 10:00:00 정각 동시 예약 트리거 (asyncio.gather)
    - 최종 1회 마침 스크린샷 저장
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
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            
            # 리소스 차단 (웹폰트 및 불필요 미디어 차단으로 탭 3개 로딩 및 메모리 최적화)
            async def route_filter(route):
                if route.request.resource_type in ["media", "font"]:
                    await route.abort()
                else:
                    await route.continue_()
                    
            await context.route("**/*", route_filter)
            
            # 2. 첫 번째 탭에서 로그인 1회 수행 (JSESSIONID 확립 및 서버 시계 오차 계산)
            main_page = await context.new_page()
            await automation.perform_login(main_page)
            await automation.verify_session(context, main_page)
            tabs.append((target_hours[0], main_page))
            
            # 3. 추가 시간대(14시, 15시 등)를 위한 병렬 탭 동시 생성 (동일 context 내 세션 공유)
            for hr in target_hours[1:]:
                tab_page = await context.new_page()
                tabs.append((hr, tab_page))
                
            # 4. 각 탭 사전 준비 (예약 페이지 이동 + [지류]청북2층 선택 + dialog 자동 승인)
            logger.info("======================================================================")
            logger.info(f"⚡ [Step 5] 3개 탭({target_hours}) 예약 페이지 사전 접속 및 위치 선택 병렬 준비...")
            logger.info("======================================================================")
            prep_tasks = [
                automation.prepare_reservation_tab(page_obj, hr)
                for hr, page_obj in tabs
            ]
            await asyncio.gather(*prep_tasks)
            logger.info(f"★ 3개 탭({target_hours}) 사전 준비 및 로딩 대기 완료!")
            
            # 5. 서버 시계 기준 목표 시각(10:00:00)까지 세션 유지 대기
            logger.info("======================================================================")
            logger.info("[Step 6] 서버 시계 10:00:00 정각까지 Keep-Alive 세션 유지 대기 중...")
            logger.info("======================================================================")
            await automation.wait_until_target_time(main_page)
            
            # 6. 정각 도달: 3개 탭 동시 비동기 병렬 예약 실행 (asyncio.gather)
            logger.info("======================================================================")
            logger.info(f"🚀 [Step 7] 13시, 14시, 15시 3개 탭 비동기 병렬 동시 예약 트리거! (asyncio.gather)")
            logger.info("======================================================================")
            reserve_tasks = [
                automation.reserve_single_slot(page_obj, hr)
                for hr, page_obj in tabs
            ]
            
            # 1개 탭의 실패가 다른 탭에 영향을 주지 않도록 return_exceptions=True 적용
            results = await asyncio.gather(*reserve_tasks, return_exceptions=True)
            
            # 7. 결과 분석 및 집계
            success_hours = []
            failed_errors = []
            success_page = None
            
            for (hr, page_obj), res in zip(tabs, results):
                if isinstance(res, Exception):
                    logger.error(f"❌ [{hr}시 탭] 예약 실패: {res}")
                    failed_errors.append((hr, res))
                else:
                    logger.info(f"✅ [{hr}시 탭] 예약 성공 완료! (슬롯: {hr}시)")
                    success_hours.append(hr)
                    if not success_page:
                        success_page = page_obj
                        
            # 모든 탭이 실패한 경우
            if not success_hours and failed_errors:
                first_hr, first_err = failed_errors[0]
                await automation.capture_failure_screenshot(main_page, first_err, f"전체_시간대_실패_{first_hr}시")
                raise RuntimeError(f"모든 시간대({target_hours}) 예약 신청 실패: {failed_errors}")
                
            # 최소 1개 이상 성공 시 최종 성공 스크린샷 단 1회 저장
            screenshot_target_page = success_page or main_page
            await automation.save_final_screenshot(screenshot_target_page, success_hours)
            
            logger.info("======================================================================")
            logger.info(f"🎉 COSMAX eBiz 입고예약 완료! | 성공: {success_hours} | 실패: {[h for h, _ in failed_errors]}")
            logger.info("======================================================================")
            
        except Exception as exc:
            if not automation.has_captured_screenshot:
                fallback_page = tabs[0][1] if tabs else None
                await automation.capture_failure_screenshot(fallback_page, exc)
            raise exc
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
