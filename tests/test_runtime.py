"""설정, 중복 저장, 종료 코드, 로그와 목표 시각 대기의 회귀 검사."""
import asyncio
import json
import logging
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.browser import CosmaxAutomation
from src.config import DEFAULT_CONFIG, load_config, validate_config
from src.holiday import check_is_weekend_or_holiday
from src.logger import setup_logger, flush_logger_to_disk, generate_html_log
from src.reservation_state import KST, ReservationState, outcome_exit_code


class RuntimeTest(unittest.TestCase):
    def test_legacy_log_directory_uses_single_canonical_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            for old in ('logs', './logs', 'logs/', 'log'):
                path.write_text(json.dumps({'log_dir': old}))
                self.assertEqual(load_config(path)['log_dir'], 'log')
            path.write_text(json.dumps({'log_dir': 'custom-output'}))
            self.assertEqual(load_config(path)['log_dir'], 'custom-output')

    def test_legacy_five_second_grid_wait_is_effectively_migrated(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text(json.dumps({'grid_wait_timeout_seconds': 5}))
            self.assertEqual(load_config(path)['grid_wait_timeout_seconds'], 60.0)
            self.assertEqual(json.loads(path.read_text())['grid_wait_timeout_seconds'], 5)

    def test_legacy_exact_ten_oclock_start_is_delayed_one_second_without_rewriting_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text(json.dumps({'target_time': '10:00:00'}))
            self.assertEqual(load_config(path)['target_time'], '10:00:01')
            self.assertEqual(json.loads(path.read_text())['target_time'], '10:00:00')

    def test_invalid_config_fails_closed(self):
        for key, value in [('target_time','25:00:00'), ('target_hours',[]), ('target_hours',[13,13]),
                           ('target_hours',[12]), ('grid_wait_timeout_seconds',-1),
                           ('keep_alive_timeout_seconds',float('nan')), ('headless','false'), ('record_video','true'),
                           ('site_timeout_seconds',0), ('save_timeout_seconds',float('inf')),
                           ('max_pre_target_retries',1.5), ('custom_holidays',['2026-02-30']),
                           ('reservation_date','20260230')]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_config(dict(DEFAULT_CONFIG, **{key:value}))
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder)/'config.json'
            file.write_text('{broken')
            with self.assertRaises(ValueError):
                load_config(file)

    def test_unknown_can_retry_but_active_or_confirmed_claims_cannot_repeat(self):
        with tempfile.TemporaryDirectory() as folder:
            state = ReservationState(folder)
            key = state.key('account','20990101',13)
            state.claim(key)
            with self.assertRaises(RuntimeError):
                state.claim(key)
            state.finish(key, 'UNKNOWN')
            state.claim(key)
            with self.assertRaises(RuntimeError):
                state.claim(key)
            state.finish(key, 'CONFIRMED', '예약번호 123')
            with self.assertRaises(RuntimeError):
                state.claim(key)

    def test_outcome_codes_preserve_partial_wait_and_unknown(self):
        for statuses, expected in [(['CONFIRMED']*3,0), (['CONFIRMED','FAILED'],2),
                                   (['EXISTING_CONFIRMED'],0), (['WAIT'],2), (['UNKNOWN'],2),
                                   (['EXISTING'],2), (['NO_CHANGE'],2), (['FAILED'],1), ([],1)]:
            self.assertEqual(outcome_exit_code([dict(status=s) for s in statuses]), expected)
        self.assertEqual(outcome_exit_code([dict(status='DRY_RUN')], True),0)

    def test_completed_recheck_locks_only_its_slot_and_restores_previous_state(self):
        with tempfile.TemporaryDirectory() as folder:
            state = ReservationState(folder)
            key14 = state.key('account', '20990101', 14)
            key15 = state.key('account', '20990101', 15)
            state.finish(key14, 'CONFIRMED', 'previous')
            previous = state.claim(key14, allow_completed=True)
            with self.assertRaises(RuntimeError):
                state.claim(key14, allow_completed=True)
            other = state.claim(key15, allow_completed=True)
            state.release(key14, previous)
            state.release(key15, other)
            self.assertEqual(state.get(key14), {'status':'CONFIRMED', 'detail':'previous'})
            self.assertIsNone(state.get(key15))

    def test_logs_survive_rerun_and_include_completion_in_html(self):
        with tempfile.TemporaryDirectory() as folder:
            log = setup_logger(folder, [13, 14, 15])
            first_paths = dict(log.tab_log_paths)
            log.info('common login failure context')
            log.info('[13시 탭] only thirteen')
            log.info('[14시 탭] only fourteen')
            log.info(r'[13시 탭] 스크린샷 저장: C:\Users\Test User\log\20260915\13\capture.png')
            log.info(r'[13시 탭] 동영상 저장: C:\Users\Test User\log\20260915\13\video test.webm')
            log.info('[COMPLETE] PARTIAL_OR_REVIEW')
            flush_logger_to_disk(log)
            for hour, path in first_paths.items():
                path = Path(path)
                self.assertEqual(path.parent.name, str(hour))
                self.assertEqual(path.parent.parent.parent, Path(folder))
                report = Path(generate_html_log(str(path))).read_text()
                self.assertIn('[COMPLETE]', report)
                self.assertIn('common login failure context', report)
                self.assertEqual('only thirteen' in report, hour == 13)
                self.assertEqual('only fourteen' in report, hour == 14)
                if hour == 13:
                    self.assertIn('src="capture.png"', report)
                    self.assertIn('<video controls preload="none" src="video test.webm"', report)
                else:
                    self.assertNotIn('<video ', report)
            first = Path(first_paths[13])
            next_log = setup_logger(folder, [13], clean_existing=True)
            flush_logger_to_disk(next_log)
            self.assertNotEqual(first, Path(next_log.tab_log_paths[13]))
            self.assertTrue(first.exists())
            self.assertEqual({p.suffix for p in Path(folder).rglob('*') if p.is_file()}, {'.log', '.html'})

    def test_reservation_state_is_memory_only(self):
        with tempfile.TemporaryDirectory() as folder:
            first = ReservationState(folder)
            key = first.key('account', '20990101', 13)
            first.finish(key, 'CONFIRMED', 'existing reservation')
            self.assertIsNone(ReservationState(folder).get(key))
            self.assertFalse(list(Path(folder).rglob('*.sqlite3')))

    def test_missing_holiday_dependency_is_not_silently_ignored(self):
        with patch('src.holiday.HAS_HOLIDAYS_PKG',False), self.assertRaisesRegex(RuntimeError,'holidays'):
            check_is_weekend_or_holiday(datetime(2026,9,15).date(),DEFAULT_CONFIG,logging.getLogger('test'))


class TimingAndLoginTest(unittest.IsolatedAsyncioTestCase):
    async def test_slow_ping_does_not_add_stale_remaining_sleep(self):
        with tempfile.TemporaryDirectory() as folder:
            bot = CosmaxAutomation(dict(log_dir=folder,target_time='10:00:00'), logging.getLogger('timing'))
            elapsed = [0.0]
            async def sleep(seconds):
                elapsed[0] += seconds
            async def get(url, timeout):
                self.assertLessEqual(timeout,3000)
                elapsed[0] += 3.0
                return SimpleNamespace(ok=True, status=200, url=url)
            page = SimpleNamespace(url='https://cip.test/reservation', request=SimpleNamespace(get=AsyncMock(side_effect=get)))
            loop = SimpleNamespace(time=lambda:elapsed[0])
            with patch('src.browser.now_kst',return_value=datetime(2026,9,15,9,59,54,tzinfo=KST)), \
                 patch('src.browser.asyncio.get_running_loop',return_value=loop), patch('src.browser.asyncio.sleep',side_effect=sleep):
                await bot.wait_until_target_time(page)
            self.assertAlmostEqual(elapsed[0],6,places=5)
            self.assertEqual(page.request.get.await_count,1)

    async def test_ping_failure_is_a_preparation_error(self):
        with tempfile.TemporaryDirectory() as folder:
            bot=CosmaxAutomation(dict(log_dir=folder,target_time='10:00:00'),logging.getLogger('timing'))
            page=SimpleNamespace(url='https://cip.test/',request=SimpleNamespace(get=AsyncMock(side_effect=TimeoutError)))
            with patch('src.browser.now_kst',return_value=datetime(2026,9,15,9,59,40,tzinfo=KST)), self.assertRaisesRegex(RuntimeError,'세션 유지 실패'):
                await bot.wait_until_target_time(page)

    async def test_cookie_on_login_page_is_not_authenticated(self):
        with tempfile.TemporaryDirectory() as folder:
            bot=CosmaxAutomation(dict(log_dir=folder),logging.getLogger('login'))
            context=SimpleNamespace(cookies=AsyncMock(return_value=[{'name':'JSESSIONID','value':'test'}]))
            page=SimpleNamespace(url='https://cip.test/loginForm.do')
            with self.assertRaisesRegex(RuntimeError,'로그인 완료'):
                await bot.verify_session(context,page)

class MainResultTest(unittest.TestCase):
    def test_partial_skip_and_failure_are_persisted_before_html(self):
        import main as entry
        for mode, expected_code, expected_status in [('partial',2,'PARTIAL_OR_REVIEW'),('skip',0,'SKIPPED'),('error',1,'FAILED')]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                config=Path(folder)/'config.json'
                config.write_text(json.dumps({'log_dir':'logs', 'max_pre_target_retries':0}))
                run=AsyncMock(return_value=[{'hour':13,'status':'CONFIRMED'}, {'hour':14,'status':'FAILED'}])
                if mode == 'error':
                    run.side_effect=RuntimeError('preparation failed')
                with patch('sys.argv',['main.py','--config',str(config)]), \
                     patch.object(entry,'execute_automation',run), \
                     patch.object(entry,'check_is_weekend_or_holiday',return_value=(mode == 'skip','test holiday')):
                    code=entry.main()
                self.assertEqual(code,expected_code)
                log_root = Path(folder) / 'log'
                self.assertFalse(list(log_root.rglob('*.json')))
                self.assertEqual(len(list(log_root.glob('*/13/*.html'))), 1)
                for report in log_root.rglob('*.html'):
                    text = report.read_text()
                    self.assertIn(f'[COMPLETE] {expected_status}', text)
                    self.assertIn('[RESULT]', text)
                self.assertEqual({p.suffix for p in log_root.rglob('*') if p.is_file()}, {'.log', '.html'})
                if mode == 'skip':
                    run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
