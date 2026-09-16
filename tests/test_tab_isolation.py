"""다른 시간대의 준비/예약이 끝나지 않아도 열린 탭의 결과를 즉시 기록한다."""
import asyncio
import logging
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from src.browser import CosmaxAutomation, execute_automation


class TabIsolationTest(unittest.IsolatedAsyncioTestCase):
    async def test_ready_tab_finishes_before_other_tabs_prepare_or_reserve_fail(self):
        completed14 = asyncio.Event()
        events = []

        async def login(page):
            await page.set_content('<p>Local test</p>')

        async def prepare(page, hour):
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
