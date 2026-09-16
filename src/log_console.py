"""Windows 콘솔별 로그 표시. 예약은 원래 프로세스에서만 실행한다."""
import codecs
import ctypes
from ctypes import wintypes
import logging
import os
import subprocess
import sys
import time

from src.logger import TabLogFilter, disable_windows_quick_edit


def set_console_title(hour):
    ctypes.windll.kernel32.SetConsoleTitleW(f"COSMAX - {hour}:00")


def start_tab_consoles(logger):
    """기존 콘솔은 첫 시간대, 나머지는 해당 실행의 로그 파일만 읽는다."""
    if sys.platform != 'win32':
        logger.warning('시간대별 콘솔은 Windows에서만 지원합니다. 현재 콘솔에서 계속 실행합니다.')
        return
    hours = list(logger.tab_log_paths)
    readers = []
    try:
        for hour in hours[1:]:
            readers.append(subprocess.Popen(
                [sys.executable, '-u', '-m', 'src.log_console', str(hour),
                 logger.tab_log_paths[hour], str(os.getpid())],
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                creationflags=0x00000010,  # CREATE_NEW_CONSOLE
            ))
        set_console_title(hours[0])
    except OSError as error:
        for reader in readers:
            reader.terminate()
            reader.wait()
        logger.warning(f'별도 콘솔 생성 실패. 현재 콘솔에서 전체 로그를 표시합니다: {error}')
        return
    for handler in logger.output_handlers:
        if type(handler) is logging.StreamHandler:
            handler.addFilter(TabLogFilter(hours[0]))
    logger.info(f'[CONSOLES] 시간대 {hours} 로그 분리. 로그인과 예약 프로세스는 1개입니다.')


def follow_log(path, output, parent_running):
    """실행 종료 시 마지막 기록까지 출력한다. 쓰기 도중의 UTF-8 문자도 보존한다."""
    decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
    with open(path, 'rb') as source:
        while True:
            running = parent_running()
            output.write(decoder.decode(source.read(), final=not running))
            output.flush()
            if not running:
                return
            time.sleep(0.2)


def main():
    hour, path, parent_pid = sys.argv[1:]
    sys.stdout.reconfigure(encoding='utf-8', errors='replace', newline='')
    disable_windows_quick_edit()
    set_console_title(hour)
    # 원래 프로세스가 비정상 종료해도 표시용 콘솔이 남지 않도록 핸들로 감시한다.
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x00100000, False, int(parent_pid))  # SYNCHRONIZE
    try:
        follow_log(path, sys.stdout, lambda: bool(handle) and kernel32.WaitForSingleObject(handle, 0) == 258)
    finally:
        if handle:
            kernel32.CloseHandle(handle)


if __name__ == '__main__':
    main()
