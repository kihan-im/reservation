#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
COSMAX eBiz 자동 로그인 및 세션 유지 프로그램 진입점 (main.py)
"""

import os
import sys
import asyncio
import argparse
from datetime import date

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

from datetime import datetime
from src.config import load_config
from src.logger import setup_logger, flush_logger_to_disk, generate_html_log
from src.holiday import check_is_weekend_or_holiday
from src.browser import execute_automation


def main():
    start_time = datetime.now()
    
    parser = argparse.ArgumentParser(description="COSMAX eBiz Auto Login & Reservation Page Session Keeper")
    parser.add_argument("--config", default="config.json", help="설정 파일 경로 (기본값: config.json)")
    parser.add_argument("--headless", action="store_true", help="브라우저 화면을 띄우지 않고 백그라운드 실행")
    parser.add_argument("--headful", action="store_true", help="브라우저 화면을 띄워서 실행")
    parser.add_argument("--force", action="store_true", help="주말 및 공휴일 체크를 무시하고 강제 실행")
    parser.add_argument("--no-pause", action="store_true", help="배치 파일/스케줄러 무인 실행 플래그")
    args = parser.parse_args()
    
    # 1. 설정 로드
    config = load_config(args.config)
    if args.headless:
        config["headless"] = True
    elif args.headful:
        config["headless"] = False
        
    # 2. 로거 생성
    logger = setup_logger(config.get("log_dir", "logs"))
    log_file_path = getattr(logger, "log_file_path", None)
    
    mode_text = "Headless(백그라운드)" if config.get("headless", False) else "화면 표시(Headful)"
    logger.info("======================================================================")
    logger.info("🚀 [START] COSMAX eBiz 입고예약 자동화 시작")
    logger.info(f"📅 시작 일시: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"⚙️ 실행 모드: {mode_text} | 목표 시각: {config.get('target_time', '10:00:00')}")
    logger.info("======================================================================")
    
    exit_code = 0
    fail_reason = ""
    try:
        # 3. 주말 / 공휴일 예외 검사
        today = date.today()
        is_off, reason = check_is_weekend_or_holiday(today, config, logger, force=args.force)
        
        if is_off:
            logger.info("======================================================================")
            logger.info(f"[SKIP] 오늘은 {reason} 입니다. 스크립트를 정상 종료합니다.")
            logger.info("======================================================================")
            return
            
        # 4. 자동화 워크플로우 실행 (10시 정각 이전 오류 감지 시 자동 복구/재시도 루프)
        target_time_str = config.get("target_time", "10:00:00")
        try:
            target_time_parts = [int(p) for p in target_time_str.split(":")]
            target_dt = datetime.combine(today, datetime.min.time()).replace(
                hour=target_time_parts[0],
                minute=target_time_parts[1],
                second=target_time_parts[2]
            )
        except Exception:
            target_dt = datetime.combine(today, datetime.min.time()).replace(hour=10, minute=0, second=0)

        max_pre_target_retries = config.get("max_pre_target_retries", 5)
        retry_delay_sec = config.get("pre_target_retry_delay_seconds", 5)
        attempt = 0

        while True:
            attempt += 1
            try:
                asyncio.run(execute_automation(config, logger))
                break  # 정상 완료 시 루프 탈출
            except Exception as err:
                curr_now = datetime.now()
                remaining_sec = (target_dt - curr_now).total_seconds()
                
                # 목표 시각(10:00:00) 이전이고 최소 15초 이상 여유가 있으며 재시도 한도 내인 경우 자동 부활
                if curr_now < target_dt and remaining_sec > 15 and attempt <= max_pre_target_retries:
                    logger.warning("======================================================================")
                    logger.warning(f"⚠️ [AUTO-HEAL] 목표 시각({target_time_str}) 이전 세션 오류 감지: {err}")
                    logger.warning(f"🔄 남은 시간: {int(remaining_sec)}초 | {retry_delay_sec}초 후 브라우저 및 세션 자동 복구 ({attempt}/{max_pre_target_retries})...")
                    logger.warning("======================================================================")
                    import time
                    time.sleep(retry_delay_sec)
                    continue
                else:
                    # 목표 시각 이후이거나 시간이 촉박한 경우 예외 전파
                    raise err

    except Exception as err:
        exit_code = 1
        fail_reason = str(err)
        logger.error(f"[FAILURE] 예약 자동화 작업 실패: {err}")

    finally:
        end_time = datetime.now()
        elapsed_sec = (end_time - start_time).total_seconds()
        
        # 5. 메모리 버퍼 로그 디스크 플러시 및 정제된 HTML 디버깅 보고서 자동 생성
        flush_logger_to_disk(logger)
        html_report_path = ""
        if log_file_path:
            html_report_path = generate_html_log(log_file_path)
            
        status_text = "✅ 성공" if exit_code == 0 else f"❌ 실패 ({fail_reason})"
        logger.info("======================================================================")
        logger.info(f"🏁 [COMPLETE] COSMAX eBiz 자동화 실행 완료 - {status_text}")
        logger.info(f"📅 시작 일시: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"🏁 종료 일시: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"⏱️ 총 소요 시간: {elapsed_sec:.2f}초 ({int(elapsed_sec // 60)}분 {int(elapsed_sec % 60)}초)")
        if html_report_path:
            logger.info(f"📊 디버깅 리포트: {html_report_path}")
        logger.info("======================================================================")

    if exit_code != 0:
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
