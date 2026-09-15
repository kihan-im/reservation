#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
날짜·시간대별 큐 기반 파일 로깅 및 HTML 보고서 생성 모듈
"""

import os
import sys
import re
import html
import logging
from datetime import datetime


class TabLogFilter(logging.Filter):
    """공통 로그와 해당 시간대의 로그만 통과시킨다."""
    def __init__(self, hour: int):
        super().__init__()
        self.tab_marker = f"[{hour}시 탭]"

    def filter(self, record):
        message = record.getMessage()
        return not re.search(r"\[\d+시 탭\]", message) or self.tab_marker in message


import queue
from logging.handlers import QueueHandler, QueueListener


def disable_windows_quick_edit():
    """
    Windows 콘솔의 빠른 편집 모드(QuickEdit) 비활성화
    - 사용자가 콘솔 창을 마우스로 클릭했을 때 콘솔이 일시정지(Freeze)되는 치명적 현상을 원천 방지
    """
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            h_stdin = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE = -10
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(h_stdin, ctypes.byref(mode)):
                ENABLE_QUICK_EDIT_MODE = 0x0040
                ENABLE_EXTENDED_FLAGS = 0x0080
                new_mode = (mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS
                kernel32.SetConsoleMode(h_stdin, new_mode)
        except Exception:
            pass


def setup_logger(log_dir="log", target_hours=None, clean_existing=False) -> logging.Logger:
    """날짜·시간대 폴더에 실행별 파일 로그를 지속 기록한다. 기존 기록은 삭제하지 않는다."""
    disable_windows_quick_edit()
    now = datetime.now()
    run_dir = os.path.abspath(os.path.join(log_dir, now.strftime("%Y%m%d")))
    run_id = now.strftime("%Y%m%d_%H%M%S_%f")
    os.makedirs(run_dir, exist_ok=True)
    logger = logging.getLogger("CosmaxAutoLogin")
    flush_logger_to_disk(logger)
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handlers = [logging.StreamHandler(sys.stdout)]
    tab_log_paths = {}
    for hour in dict.fromkeys(target_hours if target_hours is not None else [13, 14, 15]):
        tab_dir = os.path.join(run_dir, str(hour))
        os.makedirs(tab_dir, exist_ok=True)
        tab_log_paths[hour] = os.path.join(tab_dir, f"automation_{run_id}.log")
        handler = logging.FileHandler(tab_log_paths[hour], encoding="utf-8")
        handler.addFilter(TabLogFilter(hour))
        handlers.append(handler)
    for handler in handlers:
        handler.setFormatter(formatter)
    log_queue = queue.Queue()
    logger.addHandler(QueueHandler(log_queue))
    logger.queue_listener = QueueListener(log_queue, *handlers, respect_handler_level=True)
    logger.output_handlers = handlers
    logger.tab_log_paths = tab_log_paths
    logger.run_dir = run_dir
    logger.run_id = run_id
    logger.queue_listener.start()
    if clean_existing:
        logger.warning("clean_daily_logs는 폐기되었습니다. 실행별 기록을 보존합니다.")
    for hour, path in tab_log_paths.items():
        logger.info(f"[{hour}시 탭] 실행 로그: {path}")
    return logger


def flush_logger_to_disk(logger: logging.Logger):
    """완료 요약 기록 후 호출하여 큐를 비우고 파일을 닫는다. 반복 호출 가능."""
    listener = getattr(logger, "queue_listener", None)
    if listener is not None:
        listener.stop()
        logger.queue_listener = None
    for handler in getattr(logger, "output_handlers", []):
        handler.flush()
        handler.close()
    logger.output_handlers = []


def generate_html_log(log_file_path: str, html_file_path: str = None) -> str:
    """
    .log 파일 내용을 파싱하여 반응형 필터링, 실시간 검색, 스크린샷 썸네일 미리보기가 지원되는 HTML 디버깅 보고서 생성
    """
    if not os.path.exists(log_file_path):
        return ""

    if not html_file_path:
        html_file_path = os.path.splitext(log_file_path)[0] + ".html"

    with open(log_file_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    parsed_entries = []
    log_pattern = re.compile(r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2},\d{3})\s+\[([A-Z]+)\]\s+(.*)$")

    total_count = 0
    info_count = 0
    warning_count = 0
    error_count = 0
    step_count = 0

    for idx, line in enumerate(lines, 1):
        line_str = line.strip()
        if not line_str:
            continue

        match = log_pattern.match(line_str)
        if match:
            timestamp, level, message = match.groups()
        else:
            timestamp = ""
            level = "INFO"
            message = line_str

        total_count += 1
        if level == "INFO":
            info_count += 1
        elif level == "WARNING":
            warning_count += 1
        elif level == "ERROR":
            error_count += 1

        is_step = "[Step" in message or "★" in message
        if is_step:
            step_count += 1

        # 스크린샷 파일 경로 감지 (.png 파일 매칭)
        img_path = None
        img_match = re.search(r"(?:[A-Za-z]:[\\/]|/)[^\r\n]*?\.png", message)
        if img_match:
            # 시간대 HTML과 이미지는 같은 폴더에 있다. Windows 경로와 공백도 지원한다.
            img_path = img_match.group(0).replace("\\", "/").rsplit("/", 1)[-1]

        parsed_entries.append({
            "idx": idx,
            "timestamp": timestamp,
            "level": level,
            "message": message,
            "is_step": is_step,
            "img_path": img_path
        })

    today_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>COSMAX eBiz 자동화 실행 & 디버깅 로그 리포트</title>
    <style>
        :root {{
            --bg-color: #f4f6f9;
            --text-color: #333333;
            --card-bg: #ffffff;
            --border-color: #e1e4e8;
            --info-color: #0d6efd;
            --warning-color: #fd7e14;
            --error-color: #dc3545;
            --step-color: #198754;
            --header-bg: #1e293b;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            margin: 0;
            padding: 24px;
        }}
        .container {{
            max-width: 1380px;
            margin: 0 auto;
        }}
        .header {{
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            color: #ffffff;
            padding: 24px 32px;
            border-radius: 14px;
            margin-bottom: 24px;
            box-shadow: 0 10px 25px -5px rgba(0,0,0,0.1);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .header h1 {{
            margin: 0;
            font-size: 24px;
            font-weight: 700;
            letter-spacing: -0.5px;
        }}
        .header .subtitle {{
            font-size: 13px;
            color: #94a3b8;
            margin-top: 6px;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .stat-card {{
            background: var(--card-bg);
            padding: 18px 20px;
            border-radius: 12px;
            border: 1px solid var(--border-color);
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);
            text-align: center;
        }}
        .stat-card .label {{
            font-size: 13px;
            color: #64748b;
            font-weight: 600;
        }}
        .stat-card .number {{
            font-size: 28px;
            font-weight: 700;
            margin-top: 6px;
        }}
        .stat-card.total .number {{ color: #0f172a; }}
        .stat-card.info .number {{ color: var(--info-color); }}
        .stat-card.warning .number {{ color: var(--warning-color); }}
        .stat-card.error .number {{ color: var(--error-color); }}
        .stat-card.step .number {{ color: var(--step-color); }}

        .controls {{
            background: var(--card-bg);
            padding: 18px 24px;
            border-radius: 12px;
            border: 1px solid var(--border-color);
            margin-bottom: 24px;
            display: flex;
            flex-wrap: wrap;
            gap: 16px;
            align-items: center;
            justify-content: space-between;
        }}
        .filter-buttons {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }}
        .btn {{
            padding: 9px 18px;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            background: #f8fafc;
            color: #475569;
            cursor: pointer;
            font-weight: 600;
            font-size: 13px;
            transition: all 0.2s ease;
        }}
        .btn:hover {{
            background: #f1f5f9;
            color: #0f172a;
        }}
        .btn.active {{
            background: #0f172a;
            color: #ffffff;
            border-color: #0f172a;
        }}
        .search-box {{
            flex: 1;
            min-width: 280px;
            max-width: 420px;
        }}
        .search-box input {{
            width: 100%;
            padding: 10px 16px;
            border-radius: 8px;
            border: 1px solid var(--border-color);
            font-size: 14px;
            box-sizing: border-box;
            outline: none;
            transition: border-color 0.2s ease;
        }}
        .search-box input:focus {{
            border-color: #3b82f6;
        }}

        .log-table-wrapper {{
            background: var(--card-bg);
            border-radius: 12px;
            border: 1px solid var(--border-color);
            overflow: hidden;
            box-shadow: 0 4px 12px rgba(0,0,0,0.03);
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }}
        th, td {{
            padding: 12px 18px;
            text-align: left;
            border-bottom: 1px solid var(--border-color);
        }}
        th {{
            background-color: #f8fafc;
            font-weight: 700;
            color: #475569;
        }}
        tr:hover {{
            background-color: #f8fafc;
        }}
        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
        }}
        .badge-info {{ background: #dbeafe; color: #1e40af; }}
        .badge-warning {{ background: #fef3c7; color: #92400e; }}
        .badge-error {{ background: #fee2e2; color: #991b1b; }}
        .badge-step {{ background: #d1fae5; color: #065f46; }}

        .msg-text {{
            word-break: break-all;
            line-height: 1.6;
        }}
        .msg-text.highlight {{
            font-weight: 600;
            color: #0369a1;
        }}

        .img-preview-box {{
            margin-top: 10px;
        }}
        .img-thumb {{
            max-width: 360px;
            max-height: 220px;
            border-radius: 8px;
            border: 1px solid var(--border-color);
            cursor: pointer;
            transition: transform 0.2s ease, box-shadow 0.2s ease;
            box-shadow: 0 4px 10px rgba(0,0,0,0.08);
        }}
        .img-thumb:hover {{
            transform: scale(1.02);
            box-shadow: 0 8px 20px rgba(0,0,0,0.15);
        }}

        .modal {{
            display: none;
            position: fixed;
            z-index: 99999;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(15, 23, 42, 0.9);
            justify-content: center;
            align-items: center;
            backdrop-filter: blur(4px);
        }}
        .modal-content {{
            max-width: 92%;
            max-height: 92%;
            border-radius: 10px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        }}
        .modal-close {{
            position: absolute;
            top: 24px;
            right: 32px;
            color: #ffffff;
            font-size: 36px;
            font-weight: bold;
            cursor: pointer;
        }}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <div>
            <h1>COSMAX eBiz 자동화 디버깅 로그 리포트</h1>
            <div class="subtitle">리포트 생성 일시: {today_str} | 원본 로그 파일: {os.path.basename(log_file_path)}</div>
        </div>
        <div>
            <span class="badge badge-step" style="font-size: 13px; padding: 8px 16px;">실행 리포트</span>
        </div>
    </div>

    <div class="stats-grid">
        <div class="stat-card total">
            <div class="label">전체 로그 항목</div>
            <div class="number">{total_count}</div>
        </div>
        <div class="stat-card info">
            <div class="label">INFO 로그</div>
            <div class="number">{info_count}</div>
        </div>
        <div class="stat-card warning">
            <div class="label">WARNING 경고</div>
            <div class="number">{warning_count}</div>
        </div>
        <div class="stat-card error">
            <div class="label">ERROR 오류</div>
            <div class="number">{error_count}</div>
        </div>
        <div class="stat-card step">
            <div class="label">주요 단계 / 캡처</div>
            <div class="number">{step_count}</div>
        </div>
    </div>

    <div class="controls">
        <div class="filter-buttons">
            <button class="btn active" onclick="filterLevel('ALL', this)">전체 ({total_count})</button>
            <button class="btn" onclick="filterLevel('INFO', this)">INFO ({info_count})</button>
            <button class="btn" onclick="filterLevel('WARNING', this)">WARNING ({warning_count})</button>
            <button class="btn" onclick="filterLevel('ERROR', this)">ERROR ({error_count})</button>
            <button class="btn" onclick="filterLevel('STEP', this)">주요단계/캡처 ({step_count})</button>
        </div>
        <div class="search-box">
            <input type="text" id="searchInput" onkeyup="applyFilters()" placeholder="로그 검색 (예: 스크린샷, Step, 모달, 클릭)...">
        </div>
    </div>

    <div class="log-table-wrapper">
        <table id="logTable">
            <thead>
                <tr>
                    <th style="width: 50px;">#</th>
                    <th style="width: 175px;">시각</th>
                    <th style="width: 100px;">레벨</th>
                    <th>상세 로그 내용 및 캡처 스크린샷</th>
                </tr>
            </thead>
            <tbody>
"""

    for entry in parsed_entries:
        lvl_class = f"badge-{entry['level'].lower()}"
        if entry['is_step']:
            lvl_class += " badge-step"
            msg_class = "msg-text highlight"
        else:
            msg_class = "msg-text"

        escaped_msg = html.escape(entry['message'])

        img_html = ""
        if entry['img_path']:
            escaped_img_path = html.escape(entry['img_path'])
            img_html = f"""
            <div class="img-preview-box">
                <a href="{escaped_img_path}" target="_blank">
                    <img src="{escaped_img_path}" class="img-thumb" alt="캡처 스크린샷 미리보기" onclick="openModal('{escaped_img_path}'); return false;">
                </a>
                <div style="font-size: 11px; color: #64748b; margin-top: 5px;">📷 클릭하여 확대보기 ({escaped_img_path})</div>
            </div>
            """

        html_content += f"""
                <tr data-level="{entry['level']}" data-step="{str(entry['is_step']).lower()}">
                    <td>{entry['idx']}</td>
                    <td style="color: #64748b; font-family: monospace;">{entry['timestamp']}</td>
                    <td><span class="badge {lvl_class}">{entry['level']}</span></td>
                    <td>
                        <div class="{msg_class}">{escaped_msg}</div>
                        {img_html}
                    </td>
                </tr>
"""

    html_content += """
            </tbody>
        </table>
    </div>
</div>

<div id="imgModal" class="modal" onclick="closeModal()">
    <span class="modal-close" onclick="closeModal()">&times;</span>
    <img class="modal-content" id="modalImg">
</div>

<script>
    let currentLevel = 'ALL';

    function filterLevel(level, btn) {
        currentLevel = level;
        document.querySelectorAll('.filter-buttons .btn').forEach(b => b.classList.remove('active'));
        if (btn) btn.classList.add('active');
        applyFilters();
    }

    function applyFilters() {
        const query = document.getElementById('searchInput').value.toLowerCase();
        const rows = document.querySelectorAll('#logTable tbody tr');

        rows.forEach(row => {
            const level = row.getAttribute('data-level');
            const isStep = row.getAttribute('data-step') === 'true';
            const text = row.innerText.toLowerCase();

            let matchLevel = false;
            if (currentLevel === 'ALL') {
                matchLevel = true;
            } else if (currentLevel === 'STEP') {
                matchLevel = isStep;
            } else {
                matchLevel = (level === currentLevel);
            }

            let matchSearch = !query || text.includes(query);

            if (matchLevel && matchSearch) {
                row.style.display = '';
            } else {
                row.style.display = 'none';
            }
        });
    }

    function openModal(src) {
        const modal = document.getElementById('imgModal');
        const modalImg = document.getElementById('modalImg');
        modal.style.display = 'flex';
        modalImg.src = src;
    }

    function closeModal() {
        document.getElementById('imgModal').style.display = 'none';
    }
</script>
</body>
</html>
"""

    os.makedirs(os.path.dirname(os.path.abspath(html_file_path)), exist_ok=True)
    with open(html_file_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    return html_file_path
