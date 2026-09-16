"""콘솔 분리가 예약 실행이나 파일 기록에 영향을 주지 않는지 확인한다."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from src.log_console import follow_log, start_tab_consoles
from src.logger import flush_logger_to_disk, setup_logger


class LogConsoleTest(unittest.TestCase):
    def test_readers_get_exact_run_paths_and_only_console_output_is_filtered(self):
        with tempfile.TemporaryDirectory(prefix='cip console 한글 & ') as folder:
            output = io.StringIO()
            with patch('sys.stdout', output):
                logger = setup_logger(folder, [13, 14, 15])
            try:
                with patch('src.log_console.sys.platform', 'win32'), \
                     patch('src.log_console.subprocess.Popen') as spawn, \
                     patch('src.log_console.set_console_title') as title:
                    start_tab_consoles(logger)
                self.assertEqual(spawn.call_count, 2)
                title.assert_called_once_with(13)
                for call, hour in zip(spawn.call_args_list, [14, 15]):
                    self.assertEqual(call.args[0][2:6],
                                     ['-m', 'src.log_console', str(hour), logger.tab_log_paths[hour]])
                    self.assertEqual(call.kwargs['creationflags'], 0x10)
                logger.info('common context')
                for hour in [13, 14, 15]:
                    logger.info(f'[{hour}시 탭] unique-{hour}')
            finally:
                flush_logger_to_disk(logger)
            self.assertIn('unique-13', output.getvalue())
            self.assertNotIn('unique-14', output.getvalue())
            self.assertNotIn('unique-15', output.getvalue())
            for hour, path in logger.tab_log_paths.items():
                text = Path(path).read_text(encoding='utf-8')
                self.assertIn('common context', text)
                for other in [13, 14, 15]:
                    self.assertEqual(f'unique-{other}' in text, hour == other)

    def test_spawn_failure_keeps_all_logs_in_original_console(self):
        with tempfile.TemporaryDirectory() as folder:
            output, reader = io.StringIO(), Mock()
            with patch('sys.stdout', output):
                logger = setup_logger(folder, [13, 14, 15])
            try:
                with patch('src.log_console.sys.platform', 'win32'), \
                     patch('src.log_console.subprocess.Popen', side_effect=[reader, OSError('no console')]):
                    start_tab_consoles(logger)
                logger.info('[15시 탭] still visible')
            finally:
                flush_logger_to_disk(logger)
            reader.terminate.assert_called_once()
            reader.wait.assert_called_once()
            self.assertIn('별도 콘솔 생성 실패', output.getvalue())
            self.assertIn('still visible', output.getvalue())

    def test_follow_preserves_split_utf8_and_drains_after_parent_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'run.log'
            encoded = '한글\n'.encode('utf-8')
            path.write_bytes(encoded[:1])
            output = io.StringIO()
            updates = iter([(b'', True), (encoded[1:], True), (b'[COMPLETE]\n', False)])

            def running():
                data, alive = next(updates)
                with path.open('ab') as file:
                    file.write(data)
                return alive

            with patch('src.log_console.time.sleep'):
                follow_log(path, output, running)
            self.assertEqual(output.getvalue(), '한글\n[COMPLETE]\n')

    def test_headless_windows_default_and_explicit_overrides_run_automation_once(self):
        import main as entry
        cases = [('win32', '--headless', [], True),
                 ('win32', '--headless', ['--no-split-consoles'], False),
                 ('win32', '--headful', [], False),
                 ('win32', '--headful', ['--split-consoles'], True),
                 ('darwin', '--headless', [], False)]
        for platform, mode, options, expected in cases:
            with self.subTest(platform=platform, mode=mode, options=options), \
                 tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'config.json'
                path.write_text(json.dumps({'log_dir': 'log'}))
                run = AsyncMock(return_value=[dict(hour=h, status='DRY_RUN') for h in [13,14,15]])
                with patch('sys.argv', ['main.py', '--config', str(path), mode, '--dry-run', '--force', *options]), \
                     patch('sys.platform', platform), \
                     patch.object(entry, 'start_tab_consoles') as consoles, \
                     patch.object(entry, 'execute_automation', run):
                    self.assertEqual(entry.main(), 0)
                self.assertEqual(consoles.called, expected)
                run.assert_awaited_once()
                self.assertEqual(run.call_args.args[0]['target_hours'], [13,14,15])

    @unittest.skipUnless(sys.platform == 'win32', 'Windows console APIs required')
    def test_native_reader_exits_with_parent_and_prints_final_log(self):
        with tempfile.TemporaryDirectory(prefix='cip console 한글 ') as folder:
            path = Path(folder) / 'run.log'
            path.write_text('시작\n', encoding='utf-8')
            parent = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(1)'])
            reader = subprocess.Popen(
                [sys.executable, '-u', '-m', 'src.log_console', '14', str(path), str(parent.pid)],
                cwd=Path(__file__).resolve().parents[1], creationflags=0x10,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            try:
                with path.open('a', encoding='utf-8') as file:
                    file.write('[COMPLETE] 완료\n')
                output, errors = reader.communicate(timeout=10)
                self.assertEqual(reader.returncode, 0, errors.decode('utf-8', errors='replace'))
                self.assertEqual(output.decode('utf-8'), '시작\n[COMPLETE] 완료\n'.replace('\n', os.linesep))
            finally:
                for process in (reader, parent):
                    if process.poll() is None:
                        process.kill()
                    process.wait()
