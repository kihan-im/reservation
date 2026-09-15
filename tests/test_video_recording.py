"""사이트 접속 없이 실제 Chromium 녹화와 옵션 우선순위를 검증한다."""
import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.browser import CosmaxAutomation, execute_automation


class VideoRecordingTest(unittest.IsolatedAsyncioTestCase):
    async def run_local(self, folder, *, headless, record_video, login_error=False):
        async def launch(bot, playwright):
            # 화면 표시 설정 분기도 CI에서는 실제 headless Chromium으로 검증한다.
            return await playwright.chromium.launch(headless=True)

        async def login(page):
            await page.set_content('<h1>Local video test</h1>')
            await page.wait_for_timeout(300)
            if login_error:
                raise RuntimeError('local login failed')

        async def prepare(page, hour):
            await page.set_content(f'<h1>{hour} reservation</h1>')
            await page.wait_for_timeout(300)

        async def reserve(page, hour):
            return dict(hour=hour, status='DRY_RUN')

        config = dict(log_dir=folder, state_dir=str(Path(folder)/'state'),
                      target_hours=[13,14,15], headless=headless,
                      record_video=record_video, dry_run=True)
        with patch.object(CosmaxAutomation, 'launch_browser', launch), \
             patch.object(CosmaxAutomation, 'set_maximized', AsyncMock()), \
             patch.object(CosmaxAutomation, 'perform_login', side_effect=login), \
             patch.object(CosmaxAutomation, 'verify_session', AsyncMock()), \
             patch.object(CosmaxAutomation, 'prepare_reservation_tab', side_effect=prepare), \
             patch.object(CosmaxAutomation, 'reserve_single_slot', side_effect=reserve):
            return await execute_automation(config, logging.getLogger('local-video'))

    async def test_video_gate_and_per_hour_files(self):
        for headless, enabled in [(False,True),(False,False),(True,True),(True,False)]:
            with self.subTest(headless=headless, enabled=enabled), tempfile.TemporaryDirectory() as folder:
                outcomes = await self.run_local(folder, headless=headless, record_video=enabled)
                self.assertEqual(len(outcomes), 3)
                videos = list(Path(folder).rglob('*.webm'))
                if enabled and not headless:
                    self.assertEqual(len(videos), 3)
                    self.assertEqual({p.parent.name for p in videos}, {'13','14','15'})
                    for video in videos:
                        self.assertTrue(video.name.startswith('video_'))
                        self.assertTrue(video.name.endswith(f'_attempt1_{video.parent.name}.webm'))
                        self.assertGreater(video.stat().st_size, 100)
                        self.assertEqual(video.read_bytes()[:4], b'\x1a\x45\xdf\xa3')
                else:
                    self.assertEqual(videos, [])

    async def test_login_failure_still_finalizes_video(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError, 'local login failed'):
                await self.run_local(folder, headless=False, record_video=True, login_error=True)
            videos = list(Path(folder).rglob('*.webm'))
            self.assertEqual(len(videos), 1)
            self.assertEqual(videos[0].parent.name, '13')
            self.assertTrue(videos[0].name.startswith('video_'))
            self.assertGreater(videos[0].stat().st_size, 100)


class VideoOptionTest(unittest.TestCase):
    def test_cli_overrides_config_and_default_is_off(self):
        import main as entry
        for configured, option, expected in [(None,None,False), (False,'--record-video',True),
                                             (True,'--no-record-video',False), (True,None,True)]:
            with self.subTest(configured=configured, option=option), tempfile.TemporaryDirectory() as folder:
                config = {'log_dir':'log', 'target_hours':[13]}
                if configured is not None:
                    config['record_video'] = configured
                path = Path(folder)/'config.json'
                path.write_text(json.dumps(config))
                args = ['main.py','--config',str(path),'--headful','--dry-run','--force']
                if option:
                    args.append(option)
                run = AsyncMock(return_value=[dict(hour=13,status='DRY_RUN')])
                with patch('sys.argv',args), patch.object(entry,'execute_automation',run):
                    self.assertEqual(entry.main(), 0)
                self.assertEqual(run.call_args.args[0]['record_video'], expected)


if __name__ == '__main__':
    unittest.main()
