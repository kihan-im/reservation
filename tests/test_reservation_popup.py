"""로컬 페이지로 자급자재 팝업 흐름을 검증한다. 외부 사이트에는 접속하지 않는다.

실행: venv/bin/python -m unittest discover -s tests -v
"""
import asyncio
import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from playwright.async_api import async_playwright
from src.browser import CosmaxAutomation
from src.logger import setup_logger, flush_logger_to_disk, generate_html_log
from src.window_capture import capture_browser_window


PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
#lyNoti { display:none; position:fixed; inset:20px; z-index:90; background:white; }
#ly_popInreservationSelf { display:none; position:absolute; inset:20px; z-index:80; background:white; }
#load_ly_popInreservationSelf_itemList {display:none}
</style></head><body>
<div class="tabWrap"><ul><li class="active"><a id="atab1">예약목록</a></li></ul></div>
<input id="srchReservDay" value="20990101">
<button id="btnSelect">목록 조회</button>
<table id="list"><tr id="1"><td aria-describedby="list_checkYn5"><input type="checkbox"></td>
<td aria-describedby="list_facgubn">1</td><td aria-describedby="list_seq5"></td>
<td aria-describedby="list_cobut5"><a href="#" id="openMain">등록</a></td></tr></table>
<div id="ly_popInreservationMain" style="display:none">
<input id="ly_popInreservationMain_srchReservDay" value="20990101">
<input id="ly_popInreservationMain_srchReservTime" value="5">
<input id="ly_popInreservationMain_srchFacgubn" value="1">
<input id="ly_popInreservationMain_srchComptype" value="C2">
<button id="ly_popInreservationMain_btnSelfAdd">자급자재 추가</button>
<button id="ly_popInreservationMain_btnSelect">기존 품목 조회</button>
<table id="ly_popInreservationMain_itemList"></table>
<input id="ly_popInreservationMain_itemcntLimit" value="8">
<input id="ly_popInreservationMain_itemcntTotal" value="0">
<input id="ly_popInreservationMain_itemcntLimitC3" value="2">
<input id="ly_popInreservationMain_paletteTotal"><input id="ly_popInreservationMain_carTotal">
<button id="ly_popInreservationMain_btnSave">저장</button></div>
<div id="ly_popInreservationSelf">
<button id="ly_popInreservationSelf_btnSelect">조회</button>
<div id="load_ly_popInreservationSelf_itemList">조회중...</div>
<table id="ly_popInreservationSelf_itemList"></table>
<button id="ly_popInreservationSelf_btnAdd">추가</button></div>
<div id="lyNoti"><p></p><button class="pop_btnclose" onclick="this.parentElement.style.display='none'">닫기</button></div>
<script>
window.events = []; window.saved = false; window.added = false;
const main = document.getElementById('ly_popInreservationMain');
const sub = document.getElementById('ly_popInreservationSelf');
const grid = document.getElementById('ly_popInreservationSelf_itemList');
const loading = document.getElementById('load_ly_popInreservationSelf_itemList');
function notice(text) { document.querySelector('#lyNoti p').textContent = text; document.getElementById('lyNoti').style.display='block'; }
function record(e, name) { events.push({name, trusted:e.isTrusted}); }
document.getElementById('openMain').onclick = e => { e.preventDefault(); main.style.display='block'; };
document.getElementById('ly_popInreservationMain_btnSelect').onclick = async () => {
 const seq = document.querySelector('[aria-describedby="list_seq5"]').textContent;
 const response = await fetch('/selectInReservationItemListNew.do', {method:'POST',body:'srchSeq='+seq});
 const data = await response.json();
 document.getElementById('ly_popInreservationMain_itemList').innerHTML=(data.rows || []).map((r,i)=>`<tr id="existing${i}"><td>O</td></tr>`).join('');
 document.getElementById('ly_popInreservationMain_itemcntTotal').value=data.itemCount ?? (data.rows || []).length;
};
document.getElementById('ly_popInreservationMain_btnSelfAdd').onclick = e => {
 record(e,'open'); if (!e.isTrusted) return;
 setTimeout(() => { sub.style.display='block'; grid.innerHTML=''; }, 80);
};
document.getElementById('ly_popInreservationSelf_btnSelect').onclick = async e => {
 record(e,'query'); if (!e.isTrusted) return;
 loading.style.display='block';
 const response = await fetch('/selectMMIF0015List.do', {method:'POST'});
 let data; try { data = await response.json(); } catch { return; }
 setTimeout(() => {
  if (data.popup !== undefined) notice(data.popup);
  grid.innerHTML=(data.rows || []).map((r,i) => `<tr id="row${i}" data-existing="${!!r.checked}"><td aria-describedby="ly_popInreservationSelf_itemList_grctrl">${r.allowed}</td><td><input type="checkbox" ${r.checked?'checked':''} ${r.allowed==='O' && !r.disabled?'':'disabled'}></td></tr>`).join('');
  loading.style.display='none';
 }, 180);
};
document.getElementById('ly_popInreservationSelf_btnAdd').onclick = e => {
 record(e,'add'); if (!e.isTrusted) return;
 if (window.rejectAdd) { notice('자재 추가 오류'); return; }
 // 실제 사이트처럼 기존 메인 품목은 유지하고, 기존 체크와 중복되지 않는 신규 품목만 병합한다.
 const selected=Array.from(grid.querySelectorAll('tr')).filter(r=>r.querySelector('input').checked && r.dataset.existing !== 'true');
 document.getElementById('ly_popInreservationMain_itemList').insertAdjacentHTML('beforeend', selected.map((r,i)=>`<tr id="main${i}"><td>${r.textContent}</td></tr>`).join(''));
 document.getElementById('ly_popInreservationMain_itemcntTotal').value=document.querySelectorAll('#ly_popInreservationMain_itemList tr[id]').length;
 sub.style.display='none'; window.added=true;
};
document.getElementById('ly_popInreservationMain_btnSave').onclick = async e => {
 record(e,'save'); window.saved=true;
 const response = await fetch('/saveInReservationItemListNew.do', {method:'POST',body:'colink=102190'});
 const data = await response.json();
 if(data.returnCode === 'SUCCESS') notice('[13:00]시 입고 예약이 확정 되었습니다.');
 if(data.returnCode === 'WAIT') {
   document.querySelector('.tabWrap a').id='atab2';
   const next = await fetch('/saveInReservationWait.do', {method:'POST'});
   if((await next.json()).returnCode === 'SUCCESS') notice('[13:00]시 입고예약 대기로 등록 되었습니다.');
 }
};
document.getElementById('btnSelect').onclick = async () => {
 await fetch('/selectInreservationListNew.do', {method:'POST'});
};
</script></body></html>"""


class ReservationPopupTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cip-popup-test-")
        self.addCleanup(self.tmp.cleanup)
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        self.browser = await self.pw.chromium.launch(headless=True)
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page()
        self.data = {"returnCode": "SUCCESS", "rows": [{"allowed": "O"}] * 3}
        self.status = 200
        self.raw_body = None
        self.save_status = 200
        self.save_data = {"returnCode":"SUCCESS"}
        self.wait_data = {"returnCode":"SUCCESS"}
        self.list_data = {"rows":[{"facgubn":"1", "comptype":"C2", "colink5":"102190", "seq5":"12345"}]}
        self.existing_data = {"rows":[{}, {}, {}]}
        self.requests = []
        self.query_statuses = []
        self.query_delays = []
        self.save_delay = 0
        await self.page.route("**/*", self.route)
        await self.page.goto("https://cip.test/")
        self.automation = CosmaxAutomation(
            {"log_dir": self.tmp.name, 'site_timeout_seconds': 1, 'save_timeout_seconds': 1},
            logging.getLogger("popup-test")
        )

    async def route(self, route):
        path = route.request.url.split("cip.test", 1)[-1]
        self.requests.append(path)
        if path == "/":
            await route.fulfill(content_type="text/html", body=PAGE)
        elif path == "/selectMMIF0015List.do":
            await asyncio.sleep(0.05)
            await route.fulfill(status=self.status, content_type="application/json",
                                body=self.raw_body if self.raw_body is not None else json.dumps(self.data))
        elif path == "/saveInReservationItemListNew.do":
            await asyncio.sleep(self.save_delay)
            await route.fulfill(content_type="application/json", status=self.save_status, body=json.dumps(self.save_data))
        elif path == "/saveInReservationWait.do":
            await route.fulfill(content_type="application/json", body=json.dumps(self.wait_data))
        elif path == "/selectInreservationListNew.do":
            await asyncio.sleep(self.query_delays.pop(0) if self.query_delays else 0)
            await route.fulfill(status=self.query_statuses.pop(0) if self.query_statuses else 200,
                                content_type="application/json", body=json.dumps(self.list_data))
        elif path == "/selectInReservationItemListNew.do":
            await route.fulfill(content_type="application/json", body=json.dumps(self.existing_data))
        else:
            await route.abort()

    async def assert_stops_before_save(self, message):
        with self.assertRaisesRegex(RuntimeError, message):
            await self.automation.reserve_single_slot(self.page, 13)
        self.assertFalse(await self.page.evaluate("window.saved"))
        self.assertNotIn("/saveInReservationItemListNew.do", self.requests)

    async def test_native_dialog_is_captured_before_accept_and_failures_do_not_block(self):
        for mode in ('capture', 'failure', 'headless'):
            with self.subTest(mode=mode):
                self.automation.config['headless'] = mode == 'headless'
                sequence = []

                async def capture(page, path):
                    sequence.append('capture')
                    if mode == 'failure':
                        raise TimeoutError('capture timeout')
                    self.assertIn('_13_browser_dialog_', path)
                    Path(path).write_bytes(b'PNG stub')
                    process = SimpleNamespace(returncode=0, communicate=AsyncMock(return_value=(b'', b'')))
                    with patch('src.window_capture.asyncio.create_subprocess_exec', return_value=process):
                        await capture_browser_window(page, path)

                async def handle(dialog):
                    sequence.append(dialog.message)
                    await self.automation.handle_browser_dialog(self.page, 13, dialog)
                    sequence.append('accepted')

                self.page.on('dialog', handle)
                try:
                    with patch('src.browser.sys.platform', 'win32'), \
                         patch('src.browser.capture_browser_window', side_effect=capture):
                        result = await self.page.evaluate("confirm('예약신청 확인')")
                        self.assertTrue(result)
                finally:
                    self.page.remove_listener('dialog', handle)
                expected = ['예약신청 확인', 'accepted'] if mode == 'headless' else ['예약신청 확인', 'capture', 'accepted']
                self.assertEqual(sequence, expected)

    async def test_artifacts_stay_in_date_hour_folders_across_retries(self):
        root = Path(self.tmp.name) / 'log'
        logger = setup_logger(str(root), [13, 14, 15])
        config = dict(log_dir=str(root), state_dir=str(Path(self.tmp.name) / '.state'))
        try:
            first = CosmaxAutomation(config, logger)
            paths = []
            for hour in (13, 14, 15):
                paths.append(Path(await first.save_stage_screenshot(self.page, hour, 1, 'opened')))
                await first.save_final_screenshot(self.page, hour)
            retry = CosmaxAutomation(dict(config, attempt=2), logger)
            second = Path(await retry.save_stage_screenshot(self.page, 13, 1, 'opened'))
            self.assertNotEqual(paths[0], second)
            self.assertTrue(paths[0].exists())
            self.assertEqual(paths[0].parent, second.parent)
            await retry.capture_failure_screenshot(self.page, RuntimeError('common failure'))
        finally:
            flush_logger_to_disk(logger)
        for hour, path in logger.tab_log_paths.items():
            log = Path(path)
            report = Path(generate_html_log(path)).read_text()
            self.assertIn(f'src="{paths[hour - 13].name}"', report)
            self.assertEqual(log.parent.name, str(hour))
            self.assertEqual(log.parent.parent.parent, root)
            self.assertIn('common failure', report)
            self.assertEqual(len(list(log.parent.glob('*failure.png'))), 1)
        self.assertEqual({p.suffix for p in root.rglob('*') if p.is_file()}, {'.png', '.log', '.html'})
        self.assertEqual(len(list(root.glob('*/*'))), 3)

    async def reserve_and_check_notice_capture(self, expected_text):
        await self.page.evaluate("""() => {
            const show = window.notice;
            window.notice = text => setTimeout(() => show(text), 150);
        }""")
        original_screenshot = self.page.screenshot
        captured = []

        async def screenshot(**kwargs):
            is_notice = kwargs['path'].endswith('_08_save_notice.png')
            if is_notice:
                self.assertTrue(await self.page.locator('#lyNoti').is_visible())
                self.assertIn(expected_text, await self.page.locator('#lyNoti').inner_text())
                self.assertFalse(kwargs['full_page'])
            data = await original_screenshot(**kwargs)
            if is_notice:
                captured.append(Path(kwargs['path']))
            return data

        with patch.object(self.page, 'screenshot', side_effect=screenshot):
            result = await self.automation.reserve_single_slot(self.page, 13)
        self.assertEqual(len(captured), 1)
        self.assertTrue(captured[0].read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertFalse(await self.page.locator('#lyNoti').is_visible())
        return result

    async def test_normal_flow_waits_for_modal_and_grid_and_uses_real_clicks(self):
        result = await self.reserve_and_check_notice_capture('입고 예약이 확정')
        self.assertEqual(result["status"], "CONFIRMED")
        events = await self.page.evaluate("window.events")
        self.assertEqual([e['name'] for e in events], ['open', 'query', 'add', 'save'])
        self.assertTrue(all(e['trusted'] for e in events))
        self.assertEqual(await self.page.locator('#ly_popInreservationMain_itemList tr').count(), 3)
        self.assertFalse(await self.page.locator('#lyNoti').is_visible())
        self.assertTrue(list(Path(self.tmp.name).rglob('*04_self_materials_loaded.png')))

    async def test_screenshots_do_not_trigger_site_resize_and_cover_self_modal(self):
        # 실제 사이트처럼 화면보다 문서가 길고 resize 때 첫 번째 팝업이 앞으로 올라온다.
        await self.page.set_viewport_size({'width':2200, 'height':1080})
        await self.page.add_style_tag(content='''
            body { min-height:1135px; }
            #ly_popInreservationMain { position:fixed; inset:20px; z-index:70; background:white; }
        ''')
        await self.page.evaluate('''async () => {
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            window.popupResizeEvents = 0;
            window.addEventListener('resize', () => {
                if (!main.getClientRects().length) return;
                window.popupResizeEvents++;
                main.style.zIndex = '100';
            });
        }''')
        result = await self.automation.reserve_single_slot(self.page, 13)
        self.assertEqual(result['status'], 'CONFIRMED')
        self.assertEqual(await self.page.evaluate('window.popupResizeEvents'), 0)
        self.assertTrue(all(e['trusted'] for e in await self.page.evaluate('window.events')))

    async def test_blank_notice_is_preserved_and_stops_before_add_or_save(self):
        self.data['popup'] = ''
        await self.assert_stops_before_save('내용 없는 알림')
        self.assertTrue(await self.page.locator('#lyNoti').is_visible())
        self.assertFalse(await self.page.evaluate('window.added'))

    async def test_message_notice_is_reported(self):
        self.data['popup'] = '조회 권한을 확인하세요'
        await self.assert_stops_before_save('조회 권한을 확인하세요')
        self.assertFalse(await self.page.evaluate('window.added'))

    async def test_http_error_stops_before_save(self):
        self.status = 503
        with self.assertLogs('popup-test', level='ERROR') as logs:
            await self.assert_stops_before_save('HTTP 오류: 503')
        self.assertTrue(any('/selectMMIF0015List.do' in message for message in logs.output))

    async def test_invalid_json_stops_before_save(self):
        self.raw_body = '<html>error</html>'
        await self.assert_stops_before_save('JSON이 아닙니다')

    async def test_business_failure_without_rows_preserves_reason(self):
        self.data = {'returnCode':'FAIL', 'returnMessage':'조회 실패 원인'}
        await self.assert_stops_before_save('조회 실패 원인')

    async def test_no_materials_stops_before_save(self):
        self.data['rows'] = []
        await self.assert_stops_before_save('조회된 자급자재가 없습니다')

    async def test_ineligible_material_is_not_selected(self):
        self.data['rows'] = [{'allowed':'X'}, {'allowed':'O'}, {'allowed':'O'}]
        await self.assert_stops_before_save('일반품목 최소 수량 미달')
        self.assertEqual(await self.page.locator('#ly_popInreservationSelf_itemList input:checked').count(), 0)

    async def test_existing_checks_are_kept_and_only_eligible_rows_fill_capacity(self):
        await self.page.locator('#ly_popInreservationMain_itemList').evaluate(
            "el=>el.innerHTML=Array.from({length:3},(_,i)=>`<tr id='existing${i}'><td>기존</td></tr>`).join('')"
        )
        self.data['rows'] = [
            {'allowed':'X'},
            {'allowed':'O', 'checked':True},
            {'allowed':'O', 'checked':True, 'disabled':True},
            {'allowed':'O', 'checked':True},
            {'allowed':'X'},
            {'allowed':'O'},
            {'allowed':'O', 'disabled':True},
            {'allowed':'O'},
            {'allowed':'O'},
            {'allowed':'O'},
        ]
        result = await self.automation.reserve_single_slot(self.page, 13)
        self.assertEqual(result['status'], 'CONFIRMED')
        selected = await self.page.locator('#ly_popInreservationSelf_itemList tr:has(input:checked)').evaluate_all(
            'rows=>rows.map(row=>row.id)'
        )
        self.assertEqual(selected, ['row1','row2','row3','row5','row7','row8'])
        self.assertEqual(await self.page.locator('#ly_popInreservationMain_itemList tr').count(), 6)

    async def test_two_remaining_eligible_rows_are_added_to_existing_materials(self):
        await self.page.locator('[aria-describedby="list_seq5"]').evaluate("el=>el.textContent='12345'")
        self.data['rows'] = [{'allowed':'O', 'checked':True}] * 3 + [{'allowed':'O'}] * 2
        result = await self.automation.reserve_single_slot(self.page, 13)
        self.assertEqual(result['status'], 'CONFIRMED')
        selected = await self.page.locator('#ly_popInreservationSelf_itemList tr:has(input:checked)').evaluate_all(
            'rows=>rows.map(row=>row.id)'
        )
        self.assertEqual(selected, ['row0','row1','row2','row3','row4'])
        self.assertEqual(await self.page.locator('#ly_popInreservationMain_itemList tr').count(), 5)

    async def test_add_notice_stops_before_save(self):
        await self.page.evaluate('window.rejectAdd=true')
        await self.assert_stops_before_save('자재 추가 오류')
        self.assertTrue(await self.page.locator('#lyNoti').is_visible())

    async def test_dry_run_never_saves_or_creates_claim(self):
        self.automation.config['dry_run'] = True
        result = await self.automation.reserve_single_slot(self.page, 13)
        self.assertEqual(result['status'], 'DRY_RUN')
        self.assertFalse(await self.page.evaluate('window.saved'))
        key = self.automation.state.key('', '20990101', 13)
        self.assertIsNone(self.automation.state.get(key))

    async def test_wait_requires_followup_and_stays_wait(self):
        self.save_data = {'returnCode':'WAIT', 'returnCosmaxData':{'seq':'123', 'waitSeq':'0'}}
        result = await self.reserve_and_check_notice_capture('입고예약 대기')
        self.assertEqual(result['status'], 'WAIT')
        self.assertIn('/saveInReservationWait.do', self.requests)

    async def test_failed_wait_followup_is_unknown(self):
        self.save_data = {'returnCode':'WAIT'}
        self.wait_data = {'returnCode':'FAIL', 'returnMessage':'대기 저장 실패'}
        result = await self.automation.reserve_single_slot(self.page, 13)
        self.assertEqual(result['status'], 'UNKNOWN')

    async def test_unknown_existing_mismatch_is_not_blindly_resubmitted(self):
        self.list_data['rows'][0]['colink5'] = 'another-vendor'
        result = await self.automation.reserve_single_slot(self.page, 13)
        self.assertEqual(result['status'], 'UNKNOWN')
        before = self.requests.count('/saveInReservationItemListNew.do')
        self.automation.config.update(recovery_timeout_seconds=.01,
                                      retry_base_seconds=.001, retry_max_seconds=.001)
        self.list_data['rows'][0]['colink5'] = '102190'
        await self.page.reload()
        again = await self.automation.reserve_single_slot(self.page, 13)
        self.assertEqual(again['status'], 'UNKNOWN')
        self.assertEqual(before, self.requests.count('/saveInReservationItemListNew.do'))

    async def test_non_http_unknown_retries_without_recovery_delay(self):
        key = self.automation.state.key('', '20990101', 13)
        self.automation.state.finish(key, 'UNKNOWN', '저장 후 목록 확인 실패')
        self.automation.state.save_intent(key, {'retryable_save':False, 'save_attempt':1})
        with patch.object(self.automation, 'recover_unknown', AsyncMock()) as recover, \
             patch.object(self.automation, 'reserve_with_recovery', AsyncMock(return_value={'hour':13, 'day':'20990101', 'status':'CONFIRMED'})) as reserve:
            result = await self.automation.reserve_single_slot(self.page, 13)
        self.assertEqual(result['status'], 'CONFIRMED')
        recover.assert_not_awaited()
        reserve.assert_awaited_once()

    async def test_submitting_record_still_blocks_parallel_save(self):
        key = self.automation.state.key('', '20990101', 13)
        self.automation.state.claim(key)
        result = await self.automation.reserve_single_slot(self.page, 13)
        self.assertEqual(result['status'], 'SUBMITTING')
        self.assertFalse(await self.page.locator('[aria-describedby="list_checkYn5"] input').is_checked())
        self.assertNotIn('/saveInReservationItemListNew.do', self.requests)

    async def test_save_http_error_cannot_be_confirmed(self):
        self.save_status = 503
        self.automation.config.update(recovery_timeout_seconds=.01, retry_base_seconds=.001,
                                      retry_max_seconds=.001)
        result = await self.automation.reserve_single_slot(self.page, 13)
        self.assertEqual(result['status'], 'UNKNOWN')
        key = self.automation.state.key('', '20990101', 13)
        self.assertTrue(self.automation.state.get_intent(key)['retryable_save'])

    async def test_slow_save_keeps_original_request_after_two_absent_server_checks(self):
        absent = {'hour':13, 'day':'20990101', 'status':'ABSENT'}
        confirmed = {'hour':13, 'day':'20990101', 'status':'CONFIRMED'}
        self.automation.config.update(save_probe_after_seconds=.001, retry_base_seconds=.001,
                                      retry_max_seconds=.001, save_retry_absence_checks=2)
        with patch.object(self.automation, 'inspect_saved_reservation', AsyncMock(side_effect=[absent, absent, confirmed])) as inspect, \
             patch('src.recovery.asyncio.sleep', AsyncMock()):
            result = await self.automation.observe_slow_save(self.page, 13, '20990101', {'owner':'102190'})
        self.assertEqual(result, confirmed)
        self.assertEqual(inspect.await_count, 3)

    async def test_retry_ready_restarts_reservation_without_waiting_for_other_slots(self):
        retry = {'hour':13, 'day':'20990101', 'status':'RETRY_READY', 'detail':'저장 결과 없음 재조회 2회 확인'}
        confirmed = {'hour':13, 'day':'20990101', 'status':'CONFIRMED', 'detail':'예약번호 12345'}
        with patch.object(self.automation, 'reserve_open_slot', AsyncMock(side_effect=[retry, confirmed])) as reserve, \
             patch.object(self.automation, 'prepare_reservation_tab', AsyncMock()) as prepare, \
             patch.object(self.automation, 'dismiss_retry_notice', AsyncMock()) as dismiss:
            result = await self.automation.reserve_with_recovery(self.page, 13, '20990101', 'slot')
        self.assertEqual(result, confirmed)
        self.assertEqual(reserve.await_count, 2)
        prepare.assert_awaited_once()
        dismiss.assert_awaited_once()

    async def test_retry_closes_visible_site_notice(self):
        await self.page.evaluate("notice('예상치 못한 502 오류')")
        await self.automation.dismiss_retry_notice(self.page, 13)
        self.assertFalse(await self.page.locator('#lyNoti').is_visible())

    async def test_business_save_failure(self):
        self.save_data = {'returnCode':'FAIL', 'returnMessage':'마감'}
        result = await self.automation.reserve_single_slot(self.page, 13)
        self.assertEqual(result['status'], 'FAILED')

    async def test_enabled_existing_reservation_loads_items_and_adds_three(self):
        await self.page.locator('[aria-describedby="list_seq5"]').evaluate("el=>el.textContent='12345'")
        self.data['rows'] = [{'allowed':'O', 'checked':True}] * 3 + [{'allowed':'O'}] * 3
        await self.page.locator('#ly_popInreservationMain_paletteTotal').evaluate("el=>el.value='30'")
        await self.page.locator('#ly_popInreservationMain_carTotal').evaluate("el=>el.value='2'")
        result = await self.automation.reserve_single_slot(self.page, 13)
        self.assertEqual(result['status'], 'CONFIRMED')
        self.assertLess(self.requests.index('/selectInReservationItemListNew.do'), self.requests.index('/selectMMIF0015List.do'))
        self.assertEqual(await self.page.locator('#ly_popInreservationMain_itemList tr').count(), 6)
        self.assertEqual(await self.page.locator('#ly_popInreservationMain_paletteTotal').input_value(), '30')
        self.assertEqual(await self.page.locator('#ly_popInreservationMain_carTotal').input_value(), '2')
        # 이전 성공 기록이 있어도 현재 서버 품목 수를 조회하고 한도에 도달했으면 저장하지 않는다.
        before = self.requests.count('/saveInReservationItemListNew.do')
        self.existing_data = {'rows': [{}] * 8}
        again = await self.automation.reserve_single_slot(self.page, 13)
        self.assertEqual(again['status'], 'EXISTING_CONFIRMED')
        self.assertEqual(before, self.requests.count('/saveInReservationItemListNew.do'))

    async def test_completed_records_do_not_block_enabled_slot_with_capacity(self):
        key = self.automation.state.key('', '20990101', 13)
        for status in ('CONFIRMED', 'WAIT'):
            with self.subTest(previous=status):
                await self.page.reload()
                self.automation.state.finish(key, status, '이전 예약번호 12345')
                await self.page.locator('[aria-describedby="list_seq5"]').evaluate("el=>el.textContent='12345'")
                self.existing_data = {'rows': [{}] * 6}
                self.data['rows'] = [{'allowed':'O', 'checked':True}] * 6 + [{'allowed':'O'}] * 3
                before = self.requests.count('/saveInReservationItemListNew.do')
                result = await self.automation.reserve_single_slot(self.page, 13)
                self.assertEqual(result['status'], 'CONFIRMED')
                self.assertEqual(await self.page.locator('#ly_popInreservationMain_itemList tr[id]').count(), 8)
                self.assertEqual(self.requests.count('/saveInReservationItemListNew.do'), before + 1)

    async def test_pre_save_failure_releases_claim_and_preserves_previous_record(self):
        key = self.automation.state.key('', '20990101', 13)
        self.automation.state.finish(key, 'WAIT', '기존 대기 예약')
        self.data['rows'] = []
        await self.assert_stops_before_save('조회된 자급자재가 없습니다')
        self.assertEqual(self.automation.state.get(key), {'status':'WAIT', 'detail':'기존 대기 예약'})

    async def test_existing_items_query_failure_stops_before_add(self):
        await self.page.locator('[aria-describedby="list_seq5"]').evaluate("el=>el.textContent='12345'")
        self.existing_data = {'returnCode':'FAIL', 'returnMessage':'기존 품목 조회 거절'}
        await self.assert_stops_before_save('기존 품목 조회 거절')
        self.assertNotIn('/selectMMIF0015List.do', self.requests)

    async def test_eight_existing_items_skip_add_and_save(self):
        await self.page.locator('[aria-describedby="list_seq5"]').evaluate("el=>el.textContent='12345'")
        self.existing_data = {'rows':[{}] * 8}
        # 조회 기간에 포함된 기존 품목은 하나뿐이어도 메인에는 기존 8개가 남아 있다.
        self.data['rows'] = [{'allowed':'O', 'checked':True}] + [{'allowed':'O'}] * 3
        result = await self.automation.reserve_single_slot(self.page, 13)
        self.assertEqual(result['status'], 'EXISTING_CONFIRMED')
        self.assertNotIn('/saveInReservationItemListNew.do', self.requests)
        self.assertEqual(await self.page.locator('#ly_popInreservationMain_itemList tr[id^="existing"]').count(), 8)
        self.assertNotIn('/selectMMIF0015List.do', self.requests)

    async def test_nine_rows_with_eight_displayed_items_skip_without_false_limit_error(self):
        await self.page.locator('[aria-describedby="list_seq5"]').evaluate("el=>el.textContent='12345'")
        self.existing_data = {'rows': [{}] * 9, 'itemCount': 8}
        result = await self.automation.reserve_single_slot(self.page, 13)
        self.assertEqual(result['status'], 'EXISTING_CONFIRMED')
        self.assertNotIn('/saveInReservationItemListNew.do', self.requests)

    async def test_remaining_capacity_controls_selection_for_empty_six_and_seven_items(self):
        for existing, added in ((0, 3), (6, 2), (7, 1)):
            with self.subTest(existing=existing):
                await self.page.reload()
                self.automation.config['dry_run'] = True
                if existing:
                    await self.page.locator('[aria-describedby="list_seq5"]').evaluate("el=>el.textContent='12345'")
                self.existing_data = {'rows': [{}] * existing}
                # 메인 전체 수와 팝업에 조회되는 기존 체크 수가 달라도 용량은 메인 기준이다.
                self.data['rows'] = [{'allowed':'O', 'checked':True}] + [{'allowed':'O'}] * 10
                result = await self.automation.reserve_single_slot(self.page, 13)
                self.assertEqual(result['status'], 'DRY_RUN')
                self.assertEqual(await self.page.locator('#ly_popInreservationMain_itemList tr[id]').count(), existing + added)
                self.assertEqual(await self.page.locator('#ly_popInreservationSelf_itemList input:checked').count(), added + 1)
        self.assertNotIn('/saveInReservationItemListNew.do', self.requests)

    async def test_exact_limit_saves_and_late_limit_change_stops_before_save(self):
        # 현재 설정된 한도를 사용하며, 품목 추가 후 바뀐 한도도 저장 직전에 다시 확인한다.
        await self.page.locator('#ly_popInreservationMain_itemcntLimit').evaluate("el => el.value = '3'")
        result = await self.automation.reserve_single_slot(self.page, 13)
        self.assertEqual(result['status'], 'CONFIRMED')
        await self.page.reload()
        self.automation.config['dry_run'] = True
        await self.page.evaluate("""() => {
            const button = document.getElementById('ly_popInreservationSelf_btnAdd');
            const add = button.onclick;
            button.onclick = e => {
                add(e);
                document.getElementById('ly_popInreservationMain_itemcntLimit').value = '2';
            };
        }""")
        self.requests.clear()
        await self.assert_stops_before_save('품목 수 제한.*현재 종목 3개 / 허용 2개')

    async def test_limit_alert_without_save_request_is_failed_and_preserved(self):
        message = '13:00 시간의 품목 수 제한을 초과 했습니다.'
        async def handle(dialog):
            await self.automation.handle_browser_dialog(self.page, 13, dialog)
        self.page.on('dialog', handle)
        await self.page.evaluate("""message => {
            document.getElementById('ly_popInreservationMain_btnSave').onclick = () => alert(message);
        }""", message)
        with self.assertLogs('popup-test', level='ERROR') as logs:
            result = await self.automation.reserve_single_slot(self.page, 13)
        self.assertEqual(result['status'], 'FAILED')
        self.assertIn(message, result['detail'])
        self.assertIn('저장 요청 미전송', result['detail'])
        self.assertNotIn('/saveInReservationItemListNew.do', self.requests)
        self.assertIn(message, '\n'.join(logs.output))
        key = self.automation.state.key('', '20990101', 13)
        self.assertEqual(self.automation.state.get(key)['detail'], result['detail'])

    async def test_missing_limit_stops_without_guessing_or_saving(self):
        await self.page.locator('#ly_popInreservationMain_itemcntLimit').evaluate('el => el.remove()')
        await self.assert_stops_before_save('품목 수 허용 한도를 확인하지 못했습니다')
        self.assertNotIn('/selectMMIF0015List.do', self.requests)

    async def test_alert_after_save_request_keeps_unknown_with_original_reason(self):
        message = '13:00 시간의 품목 수 제한을 초과 했습니다.'
        async def handle(dialog):
            await self.automation.handle_browser_dialog(self.page, 13, dialog)
        self.page.on('dialog', handle)
        await self.page.evaluate("""message => {
            document.getElementById('ly_popInreservationMain_btnSave').onclick = async () => {
                await fetch('/saveInReservationItemListNew.do', {method:'POST'});
                alert(message);
            };
        }""", message)
        result = await self.automation.reserve_single_slot(self.page, 13)
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertIn(message, result['detail'])
        self.assertIn('/saveInReservationItemListNew.do', self.requests)

    async def test_disabled_existing_reservation_still_stops(self):
        await self.page.locator('[aria-describedby="list_seq5"]').evaluate("el=>el.textContent='12345'")
        await self.page.locator('#list input[type="checkbox"]').evaluate('el=>el.disabled=true')
        self.automation.config['grid_wait_timeout_seconds'] = 0.5
        # 조회 지연은 별도 테스트에서 검사한다. 여기서는 조회 후에도 비활성인 슬롯만 검증한다.
        with patch.object(self.automation, 'refresh_reservation_list', AsyncMock(return_value=self.list_data)) as refresh:
            await self.assert_stops_before_save('체크박스가 활성화되지 않았습니다')
        refresh.assert_awaited_once()

    async def test_wrong_warehouse_stops_before_save(self):
        await self.page.locator('#ly_popInreservationMain_srchFacgubn').evaluate("el=>el.value='2'")
        await self.assert_stops_before_save('예약 정보 불일치')

    async def test_grid_timeout_bounds_slow_reload(self):
        self.automation.config['grid_wait_timeout_seconds'] = 0.1
        await self.page.locator('#list input[type="checkbox"]').evaluate('el=>el.disabled=true')
        self.query_delays = [0.5]
        start = asyncio.get_running_loop().time()
        await self.assert_stops_before_save('예약 목록 조회 지연.*마감 여부 미확인')
        self.assertLess(asyncio.get_running_loop().time()-start, 1)

    async def test_list_waits_for_late_slot_masking_before_using_checkbox(self):
        await self.page.evaluate("""() => {
            window.jQuery = {active: 1};
            setTimeout(() => {
                document.querySelector('#list input').disabled = true;
                document.getElementById('openMain').remove();
                window.jQuery.active = 0;
            }, 250);
        }""")
        await self.automation.refresh_reservation_list(self.page, 13)
        self.assertFalse(await self.page.locator('#list input').is_enabled())
        self.assertEqual(await self.page.locator('#openMain').count(), 0)

    async def test_slow_query_over_old_six_second_limit_is_not_reissued(self):
        self.automation.site_timeout_ms = 10000
        self.query_delays = [6.5]
        data = await self.automation.refresh_reservation_list(self.page, 13)
        self.assertEqual(data, self.list_data)
        self.assertEqual(self.requests.count('/selectInreservationListNew.do'), 1)

    async def test_read_only_query_retries_temporary_overload_and_timeout(self):
        for failure in ('overload', 'timeout'):
            with self.subTest(failure=failure):
                self.requests.clear()
                if failure == 'overload':
                    self.automation.site_timeout_ms = 1000
                    self.query_statuses = [503, 200]
                else:
                    self.automation.site_timeout_ms = 150
                    self.query_delays = [0.4, 0]
                with self.assertLogs('popup-test', level='WARNING') as logs:
                    await self.automation.refresh_reservation_list(self.page, 13)
                self.assertIn('[RETRY]', '\n'.join(logs.output))
                self.assertEqual(self.requests.count('/selectInreservationListNew.do'), 2)

    async def test_slow_save_over_old_twelve_second_limit_waits_without_resubmission(self):
        self.automation.save_timeout_seconds = 20
        self.save_delay = 12.5
        with self.assertLogs('popup-test', level='WARNING') as logs:
            result = await self.automation.reserve_single_slot(self.page, 13)
        self.assertEqual(result['status'], 'CONFIRMED')
        self.assertEqual(self.requests.count('/saveInReservationItemListNew.do'), 1)
        self.assertIn('[WAITING]', '\n'.join(logs.output))

    async def test_save_deadline_keeps_unknown_and_never_retries_write(self):
        self.automation.save_timeout_seconds = 0.15
        self.save_delay = 0.5
        result = await self.automation.reserve_single_slot(self.page, 13)
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertEqual(self.requests.count('/saveInReservationItemListNew.do'), 1)
        key = self.automation.state.key('', '20990101', 13)
        self.assertTrue(self.automation.state.get_intent(key)['retryable_save'])


if __name__ == '__main__':
    unittest.main()
