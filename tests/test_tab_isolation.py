"""다른 시간대의 준비/예약이 끝나지 않아도 열린 탭의 결과를 즉시 기록한다."""
import asyncio
import logging
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from src.browser import CosmaxAutomation, execute_automation


class TabIsolationTest(unittest.IsolatedAsyncioTestCase):
    async def test_factory_activation_starts_only_after_target_wait(self):
        events = []

        async def login(page):
            await page.set_content('<p>Local test</p>')

        async def prepare(page, hour, *, activate_factory=True):
            self.assertFalse(activate_factory)
            events.append('page')

        async def wait(page):
            events.append('target')

        async def activate(page, hour):
            events.append('factory')

        async def reserve(page, hour):
            events.append('reserve')
            return dict(hour=hour, status='CONFIRMED')

        with tempfile.TemporaryDirectory() as folder:
            config = dict(log_dir=folder, target_hours=[13], target_time='00:00:00',
                          headless=True, dry_run=False, reservation_retry_window_seconds=1)
            with patch.object(CosmaxAutomation, 'perform_login', side_effect=login), \
                 patch.object(CosmaxAutomation, 'verify_session', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'calibrate_server_time', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'prepare_reservation_tab', side_effect=prepare), \
                 patch.object(CosmaxAutomation, 'wait_until_target_time', side_effect=wait), \
                 patch.object(CosmaxAutomation, 'activate_reservation_factory', side_effect=activate), \
                 patch.object(CosmaxAutomation, 'reserve_single_slot', side_effect=reserve), \
                 patch.object(CosmaxAutomation, 'save_final_screenshot', AsyncMock()):
                results = await execute_automation(config, logging.getLogger('factory-timing'))
        self.assertEqual(results[0]['status'], 'CONFIRMED')
        self.assertEqual(events, ['page', 'target', 'factory', 'reserve'])

    async def test_ready_tab_finishes_before_other_tabs_prepare_or_reserve_fail(self):
        completed14 = asyncio.Event()
        events = []

        async def login(page):
            await page.set_content('<p>Local test</p>')

        async def prepare(page, hour, **_):
            if hour == 13:
                await completed14.wait()
                events.append('13 preparation failed')
                raise RuntimeError('13시 목록 조회 실패')

        async def reserve(page, hour):
            if hour == 15:
                await completed14.wait()
                events.append('15 slot closed')
                raise RuntimeError('15시 체크박스 비활성')
            return dict(hour=hour, status='CONFIRMED')

        async def final_screen(page, hour):
            if hour == 14:
                events.append('14 result recorded')
                completed14.set()

        with tempfile.TemporaryDirectory() as folder:
            config = dict(log_dir=folder, target_hours=[13,14,15], headless=True, dry_run=False)
            with patch.object(CosmaxAutomation, 'perform_login', side_effect=login), \
                 patch.object(CosmaxAutomation, 'verify_session', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'prepare_reservation_tab', side_effect=prepare), \
                 patch.object(CosmaxAutomation, 'activate_reservation_factory', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'wait_until_target_time', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'reserve_single_slot', side_effect=reserve), \
                 patch.object(CosmaxAutomation, 'save_final_screenshot', side_effect=final_screen), \
                 patch.object(CosmaxAutomation, 'capture_failure_screenshot', AsyncMock()), \
                 self.assertLogs('tab-isolation', level='INFO') as logs:
                results = await asyncio.wait_for(execute_automation(config, logging.getLogger('tab-isolation')), 5)
        self.assertEqual({result['hour']:result['status'] for result in results},
                         {13:'FAILED', 14:'CONFIRMED', 15:'FAILED'})
        self.assertEqual(events[0], '14 result recorded')
        results_log = [message for message in logs.output if '[RESULT]' in message]
        self.assertIn('[14시 탭]', results_log[0])

    async def test_blank_notice_retries_once_without_repeating_confirmed_slots(self):
        attempts = {13: 0, 14: 0}

        async def login(page):
            await page.set_content('<p>Local test</p>')

        async def reserve(page, hour):
            attempts[hour] += 1
            if hour == 13:
                raise RuntimeError(
                    f'[{hour}시 탭] 예약 목록 조회: 사이트 알림 - '
                    '내용 없는 알림 (통신 오류 또는 서버 응답 확인 필요)')
            return dict(hour=hour, status='CONFIRMED')

        with tempfile.TemporaryDirectory() as folder:
            config = dict(log_dir=folder, target_hours=[13,14], target_time='00:00:00',
                          headless=True, dry_run=False, reservation_retry_window_seconds=5)
            with patch.object(CosmaxAutomation, 'perform_login', side_effect=login), \
                 patch.object(CosmaxAutomation, 'verify_session', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'calibrate_server_time', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'prepare_reservation_tab', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'activate_reservation_factory', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'refresh_reservation_list', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'dismiss_retry_notice', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'wait_until_target_time', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'reserve_single_slot', side_effect=reserve), \
                 patch.object(CosmaxAutomation, 'save_final_screenshot', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'capture_failure_screenshot', AsyncMock()):
                results = await asyncio.wait_for(
                    execute_automation(config, logging.getLogger('tab-retry')), 5)
        self.assertEqual({result['hour']:result['status'] for result in results},
                         {13:'FAILED', 14:'CONFIRMED'})
        self.assertEqual(attempts, {13:2, 14:1})

    async def test_terminal_layout_error_is_not_retried(self):
        attempts = 0

        async def login(page):
            await page.set_content('<p>Local test</p>')

        async def reserve(page, hour):
            nonlocal attempts
            attempts += 1
            raise RuntimeError(f'[{hour}시 탭] 청북2층 예약 행이 여러 개여서 처리할 수 없습니다.')

        with tempfile.TemporaryDirectory() as folder:
            config = dict(log_dir=folder, target_hours=[13], target_time='00:00:00',
                          headless=True, dry_run=False, reservation_retry_window_seconds=1)
            with patch.object(CosmaxAutomation, 'perform_login', side_effect=login), \
                 patch.object(CosmaxAutomation, 'verify_session', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'calibrate_server_time', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'prepare_reservation_tab', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'activate_reservation_factory', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'refresh_reservation_list', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'wait_until_target_time', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'reserve_single_slot', side_effect=reserve), \
                 patch.object(CosmaxAutomation, 'save_final_screenshot', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'capture_failure_screenshot', AsyncMock()):
                results = await asyncio.wait_for(
                    execute_automation(config, logging.getLogger('tab-terminal')), 5)
        self.assertEqual(results[0]['status'], 'FAILED')
        self.assertEqual(attempts, 1)

    async def test_missing_checkbox_retries_once_then_stops(self):
        attempts = 0

        async def login(page):
            await page.set_content('<p>Local test</p>')

        async def reserve(page, hour):
            nonlocal attempts
            attempts += 1
            raise RuntimeError(f'[{hour}시 탭] 대상 시간대 체크박스가 없습니다. (청북2층 예약 행 미표시)')

        with tempfile.TemporaryDirectory() as folder:
            config = dict(log_dir=folder, target_hours=[13], target_time='00:00:00',
                          headless=True, dry_run=False, reservation_retry_window_seconds=1)
            with patch.object(CosmaxAutomation, 'perform_login', side_effect=login), \
                 patch.object(CosmaxAutomation, 'verify_session', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'calibrate_server_time', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'prepare_reservation_tab', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'activate_reservation_factory', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'refresh_reservation_list', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'wait_until_target_time', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'reserve_single_slot', side_effect=reserve), \
                 patch.object(CosmaxAutomation, 'save_final_screenshot', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'capture_failure_screenshot', AsyncMock()), \
                 patch('src.browser.retry_delay', return_value=.001):
                results = await asyncio.wait_for(
                    execute_automation(config, logging.getLogger('tab-missing-checkbox')), 5)
        self.assertEqual(results[0]['status'], 'FAILED')
        self.assertFalse(results[0]['retryable'])
        self.assertEqual(attempts, 2)

    async def test_material_grid_timeout_does_not_reprepare_or_navigate(self):
        attempts = 0

        async def login(page):
            await page.set_content('<p>Local test</p>')

        async def reserve(page, hour):
            nonlocal attempts
            attempts += 1
            raise RuntimeError(f'[{hour}시 탭] 자급자재 조회 화면 반영 지연: 동일 탭 조회 2회 후 체크박스가 나타나지 않았습니다.')

        with tempfile.TemporaryDirectory() as folder:
            config = dict(log_dir=folder, target_hours=[13], target_time='00:00:00',
                          headless=True, dry_run=False, reservation_retry_window_seconds=1)
            with patch.object(CosmaxAutomation, 'perform_login', side_effect=login), \
                 patch.object(CosmaxAutomation, 'verify_session', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'calibrate_server_time', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'prepare_reservation_tab', AsyncMock()) as prepare, \
                 patch.object(CosmaxAutomation, 'activate_reservation_factory', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'wait_until_target_time', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'reserve_single_slot', side_effect=reserve), \
                 patch.object(CosmaxAutomation, 'save_final_screenshot', AsyncMock()), \
                 patch.object(CosmaxAutomation, 'capture_failure_screenshot', AsyncMock()):
                results = await asyncio.wait_for(
                    execute_automation(config, logging.getLogger('tab-grid-timeout')), 5)
        self.assertEqual(results[0]['status'], 'FAILED')
        self.assertEqual(attempts, 1)
        prepare.assert_awaited_once()
