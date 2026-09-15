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
    def test_invalid_config_fails_closed(self):
        for key, value in [('target_time','25:00:00'), ('target_hours',[]), ('target_hours',[13,13]),
                           ('target_hours',[12]), ('grid_wait_timeout_seconds',-1),
                           ('keep_alive_timeout_seconds',float('nan')), ('headless','false'),
                           ('max_pre_target_retries',1.5), ('custom_holidays',['2026-02-30'])]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_config(dict(DEFAULT_CONFIG, **{key:value}))
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder)/'config.json'
            file.write_text('{broken')
            with self.assertRaises(ValueError):
                load_config(file)

    def test_atomic_claim_and_uncertain_result_cannot_repeat(self):
        with tempfile.TemporaryDirectory() as folder:
            first, second = ReservationState(folder), ReservationState(folder)
            key = first.key('account','20990101',13)
            first.claim(key)
            with self.assertRaises(RuntimeError):
                second.claim(key, retry_unknown=True)
            first.finish(key, 'UNKNOWN')
            with self.assertRaises(RuntimeError):
                second.claim(key)
            second.claim(key, retry_unknown=True)
            second.finish(key, 'CONFIRMED', '예약번호 123')
            with self.assertRaises(RuntimeError):
                first.claim(key, retry_unknown=True)

    def test_outcome_codes_preserve_partial_wait_and_unknown(self):
        for statuses, expected in [(['CONFIRMED']*3,0), (['CONFIRMED','FAILED'],2),
                                   (['WAIT'],2), (['UNKNOWN'],2), (['EXISTING'],2), (['FAILED'],1), ([],1)]:
            self.assertEqual(outcome_exit_code([dict(status=s) for s in statuses]), expected)
        self.assertEqual(outcome_exit_code([dict(status='DRY_RUN')], True),0)

    def test_logs_survive_rerun_and_include_completion_in_html(self):
        with tempfile.TemporaryDirectory() as folder:
            log = setup_logger(folder, [13, 14, 15])
            first_paths = dict(log.tab_log_paths)
            log.info('common login failure context')
            log.info('[13시 탭] only thirteen')
            log.info('[14시 탭] only fourteen')
            log.info(r'[13시 탭] 스크린샷 저장: C:\Users\Test User\log\20260915\13\capture.png')
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
            first = Path(first_paths[13])
            next_log = setup_logger(folder, [13], clean_existing=True)
            flush_logger_to_disk(next_log)
            self.assertNotEqual(first, Path(next_log.tab_log_paths[13]))
            self.assertTrue(first.exists())
            self.assertEqual({p.suffix for p in Path(folder).rglob('*') if p.is_file()}, {'.log', '.html'})

    def test_old_reservation_records_survive_log_layout_change(self):
        with tempfile.TemporaryDirectory() as folder:
            old = ReservationState(Path(folder) / 'logs')
            confirmed = old.key('account', '20990101', 13)
            pending = old.key('account', '20990101', 14)
            old.finish(confirmed, 'CONFIRMED', 'existing reservation')
            old.claim(pending)
            new_dir = Path(folder) / '.reservation_state'
            current = ReservationState(new_dir, legacy_paths=[old.path])
            self.assertEqual(current.get(confirmed), old.get(confirmed))
            with self.assertRaises(RuntimeError):
                current.claim(confirmed)
            with self.assertRaises(RuntimeError):
                current.claim(pending, retry_unknown=True)
            current.finish(pending, 'CONFIRMED', 'verified later')
            again = ReservationState(new_dir, legacy_paths=[old.path])
            self.assertEqual(again.get(pending)['detail'], 'verified later')
            self.assertTrue(old.path.exists())

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
