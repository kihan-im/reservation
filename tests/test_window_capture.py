"""Windows 캡처 명령 전달과 시간 초과 시 자식 프로세스 정리를 검사한다."""
import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from src.window_capture import capture_browser_window


class WindowCaptureTest(unittest.IsolatedAsyncioTestCase):
    async def test_capture_targets_browser_process_and_cleans_up_on_cancel(self):
        session = SimpleNamespace(
            send=AsyncMock(return_value={'processInfo': [{'type': 'browser', 'id': 1234}]}),
            detach=AsyncMock(),
        )
        page = SimpleNamespace(
            context=SimpleNamespace(browser=SimpleNamespace(new_browser_cdp_session=AsyncMock(return_value=session))),
            bring_to_front=AsyncMock(),
        )
        with tempfile.TemporaryDirectory(prefix='cip capture ') as folder:
            path = Path(folder) / "popup's image.png"
            process = SimpleNamespace(returncode=0, communicate=AsyncMock(return_value=(b'', b'')))

            async def start(*args, **kwargs):
                self.assertEqual(kwargs['env']['CIP_CAPTURE_BROWSER_PID'], '1234')
                self.assertEqual(kwargs['env']['CIP_CAPTURE_IMAGE_PATH'], str(path))
                self.assertNotIn(str(path), args)
                self.assertEqual(kwargs['creationflags'], 0x08000000)
                path.write_bytes(b'PNG stub')
                return process

            with patch('src.window_capture.asyncio.create_subprocess_exec', side_effect=start):
                await capture_browser_window(page, str(path))
                session.detach.assert_awaited_once()
                page.bring_to_front.assert_awaited_once()
                process.returncode = None
                process.communicate.side_effect = asyncio.CancelledError()
                process.kill = Mock()
                process.wait = AsyncMock()
                with self.assertRaises(asyncio.CancelledError):
                    await capture_browser_window(page, str(path))
                process.kill.assert_called_once()
                process.wait.assert_awaited_once()
