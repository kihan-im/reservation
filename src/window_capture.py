"""Windows 기본 기능으로 브라우저 창과 네이티브 팝업을 함께 캡처한다."""
import asyncio
import base64
import os
from pathlib import Path


WINDOW_CAPTURE_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class CaptureWindow {
    [StructLayout(LayoutKind.Sequential)]
    public struct Rect { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hwnd, out Rect rect);
    [DllImport("dwmapi.dll")] public static extern int DwmFlush();
}
"@
[CaptureWindow]::SetProcessDPIAware() | Out-Null
[CaptureWindow]::DwmFlush() | Out-Null
$windowHandle = [CaptureWindow]::GetForegroundWindow()
[uint32]$windowProcessId = 0
[CaptureWindow]::GetWindowThreadProcessId($windowHandle, [ref]$windowProcessId) | Out-Null
if ($windowProcessId -ne [uint32]$env:CIP_CAPTURE_BROWSER_PID) {
    throw 'The automation browser is not in the foreground.'
}
$rect = New-Object CaptureWindow+Rect
if (-not [CaptureWindow]::GetWindowRect($windowHandle, [ref]$rect)) { throw 'Cannot read browser bounds.' }
$bitmap = New-Object System.Drawing.Bitmap(($rect.Right - $rect.Left), ($rect.Bottom - $rect.Top))
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
try {
    $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bitmap.Size)
    $bitmap.Save($env:CIP_CAPTURE_IMAGE_PATH, [System.Drawing.Imaging.ImageFormat]::Png)
} finally {
    $graphics.Dispose()
    $bitmap.Dispose()
}
'''


async def capture_browser_window(page, image_path):
    """호출 측의 시간 제한·잠금 안에서 실행한다. 페이지 JavaScript는 사용하지 않는다."""
    session = await page.context.browser.new_browser_cdp_session()
    try:
        info = await session.send('SystemInfo.getProcessInfo')
        browser_pid = next(p['id'] for p in info['processInfo'] if p['type'] == 'browser')
    finally:
        await session.detach()
    await page.bring_to_front()
    env = dict(os.environ, CIP_CAPTURE_BROWSER_PID=str(int(browser_pid)),
               CIP_CAPTURE_IMAGE_PATH=os.path.abspath(image_path))
    command = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'),
                           'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
    process = await asyncio.create_subprocess_exec(
        command, '-NoProfile', '-NonInteractive', '-EncodedCommand',
        base64.b64encode(WINDOW_CAPTURE_SCRIPT.encode('utf-16-le')).decode('ascii'),
        env=env, creationflags=0x08000000,  # CREATE_NO_WINDOW: 콘솔이 브라우저를 가리지 않도록 한다.
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, error = await process.communicate()
    except BaseException:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.wait()
        raise
    if process.returncode:
        raise RuntimeError(f'Windows 팝업 캡처 실패: {error.decode(errors="replace").strip()}')
    if not Path(image_path).is_file():
        raise RuntimeError('Windows 팝업 캡처 파일이 생성되지 않았습니다.')
