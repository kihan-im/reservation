#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
COSMAX eBiz 자동 로그인 및 세션 유지 프로그램 진입점 (main.py)
"""

import os
import sys
import asyncio
import argparse

# 현재 디렉토리를 모듈 검색 경로 최상단에 추가
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# Playwright 미설치 환경(시스템 python 직접 실행 등) 시 venv 자동 감지 및 재실행
try:
    import playwright
except ImportError:
    venv_candidates = [
        os.path.join(BASE_DIR, "venv", "bin", "python"),
        os.path.join(BASE_DIR, ".venv", "bin", "python"),
        "/tmp/cip_venv/bin/python",
        os.path.join(BASE_DIR, "venv", "Scripts", "python.exe"),
    ]
    for cand in venv_candidates:
        if os.path.exists(cand) and sys.executable != cand:
            os.execv(cand, [cand] + sys.argv)

import json
import time
from src.config import load_config, validate_config
from src.logger import setup_logger, flush_logger_to_disk, generate_html_log
from src.log_console import start_tab_consoles
from src.holiday import check_is_weekend_or_holiday
from src.browser import execute_automation
from src.reservation_state import now_kst, outcome_exit_code


def main():
    parser = argparse.ArgumentParser(description="COSMAX eBiz 입고예약 자동화")
    parser.add_argument("--config", default=os.path.join(BASE_DIR, "config.json"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--headless", action="store_true")
    mode.add_argument("--headful", action="store_true")
    parser.add_argument("--record-video", action=argparse.BooleanOptionalAction, default=None,
                        help="화면 표시 모드에서 영상 녹화. headless에서는 항상 생략")
    parser.add_argument("--force", action="store_true", help="주말/공휴일 검사만 생략")
    parser.add_argument("--no-pause", action="store_true", help="Windows 배치 무인 실행")
    parser.add_argument("--split-consoles", action=argparse.BooleanOptionalAction, default=None,
                        help="Windows 시간대별 로그 콘솔 (headless에서 기본 사용)")
    parser.add_argument("--dry-run", action="store_true", help="목표 시각 대기 및 최종 저장 없이 준비 과정 점검")
    parser.add_argument("--check-config", action="store_true", help="브라우저 없이 설정 유효성 점검")
    parser.add_argument("--hours", nargs="+", type=int, help="이번 실행에서 처리할 시간대")
    parser.add_argument("--retry-unknown", action="store_true", help="호환용 옵션: 이전 UNKNOWN 기록은 기본적으로 재시도합니다")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.headless or args.headful:
            config["headless"] = args.headless
        if args.record_video is not None:
            config["record_video"] = args.record_video
        if args.hours is not None:
            config["target_hours"] = args.hours
        config["dry_run"] = args.dry_run or config["dry_run"]
        validate_config(config)
        if not os.path.isabs(config["log_dir"]):
            config["log_dir"] = os.path.join(os.path.dirname(os.path.abspath(args.config)), config["log_dir"])
    except (ValueError, OSError, TypeError) as error:
        print(f"[CONFIG ERROR] {error}", file=sys.stderr)
        return 1
    if args.check_config:
        print("[CONFIG OK] 설정 검사 완료 (브라우저 실행/예약 없음)")
        return 0

    start = now_kst()
    logger = setup_logger(config["log_dir"], config["target_hours"], config.get("clean_daily_logs", False))
    split_consoles = args.split_consoles if args.split_consoles is not None else (
        sys.platform == 'win32' and config['headless'])
    if split_consoles:
        start_tab_consoles(logger)
    status, exit_code, results = "FAILED", 1, []
    logger.info(f"[START] {start.isoformat()} / 목표 {config['target_time']} KST / dry_run={config['dry_run']}")
    try:
        is_off, reason = check_is_weekend_or_holiday(start.date(), config, logger, force=args.force)
        if is_off:
            status, exit_code = "SKIPPED", 0
            logger.info(f"[SKIP] {reason}")
        else:
            hour, minute, second = map(int, config['target_time'].split(':'))
            target = start.replace(hour=hour, minute=minute, second=second, microsecond=0)
            for attempt in range(config['max_pre_target_retries'] + 1):
                try:
                    config["attempt"] = attempt + 1
                    results = asyncio.run(execute_automation(config, logger))
                    break
                except Exception as error:
                    # execute_automation은 저장 시작 후 오류를 결과로 반환한다. 사전 준비만 재시도한다.
                    remaining = (target - now_kst()).total_seconds()
                    delay = config['pre_target_retry_delay_seconds']
                    if config['dry_run'] or remaining <= delay + 15 or attempt >= config['max_pre_target_retries']:
                        raise
                    logger.warning(f"[AUTO-HEAL] 사전 준비 실패: {error}. {delay}초 후 재시도 {attempt+1}")
                    time.sleep(delay)
            exit_code = outcome_exit_code(results, config['dry_run'])
            status = ("DRY_RUN" if config['dry_run'] else "CONFIRMED") if exit_code == 0 else (
                "PARTIAL_OR_REVIEW" if exit_code == 2 else "FAILED")
    except Exception as error:
        logger.exception(f"[FAILURE] {error}")
    finally:
        end = now_kst()
        by_hour = {result['hour']: result for result in results}
        for hour in config['target_hours']:
            result = by_hour.get(hour, dict(hour=hour, status='SKIPPED' if status == 'SKIPPED' else 'FAILED',
                                           detail='공통 실행 로그 확인 필요'))
            logger.info(f"[{hour}시 탭] [RESULT] {json.dumps(result, ensure_ascii=False)}")
            report_path = os.path.splitext(logger.tab_log_paths[hour])[0] + ".html"
            logger.info(f"[{hour}시 탭] 보고서: {report_path}")
        logger.info(f"[COMPLETE] {status} / 종료 코드 {exit_code} / 소요 {(end-start).total_seconds():.2f}초")
        flush_logger_to_disk(logger)
        for log_path in logger.tab_log_paths.values():
            try:
                generate_html_log(log_path)
            except OSError as error:
                print(f"HTML 보고서 생성 실패: {error}", file=sys.stderr)
                exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
