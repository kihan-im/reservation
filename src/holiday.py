#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
주말 및 대한민국 법정 공휴일 예외 처리 모듈
"""

import logging
from datetime import date

# holidays 외부 패키지 import 시도 (미설치 시 내장 딕셔너리로 대체)
try:
    import holidays
    HAS_HOLIDAYS_PKG = True
except ImportError:
    HAS_HOLIDAYS_PKG = False


def check_is_weekend_or_holiday(today: date, config: dict, logger: logging.Logger, force: bool = False) -> tuple[bool, str]:
    """오늘 날짜가 주말 또는 공휴일인지 검사하여 (건너뛸지 여부, 이유)를 반환"""
    if force:
        logger.info("[강제 실행] --force 옵션이 설정되어 주말/공휴일 검사를 건너뜁니다.")
        return False, ""
        
    date_str = today.strftime("%Y-%m-%d")
    
    # 1. 주말 검사 (토요일=5, 일요일=6)
    if config.get("skip_weekends", True):
        weekday = today.weekday()
        if weekday == 5:
            return True, f"주말 (토요일, {date_str})"
        elif weekday == 6:
            return True, f"주말 (일요일, {date_str})"
            
    # 2. 커스텀 사용자 정의 휴일 검사
    custom_holidays = config.get("custom_holidays", [])
    if date_str in custom_holidays:
        return True, f"사용자 지정 휴일 ({date_str})"
        
    # 3. 법정 공휴일 검사
    if config.get("skip_holidays", True):
        if HAS_HOLIDAYS_PKG:
            kr_holidays = holidays.KR(years=[today.year])
            if today in kr_holidays:
                holiday_name = kr_holidays.get(today)
                return True, f"대한민국 공휴일 ({holiday_name}, {date_str})"
        else:
            raise RuntimeError("공휴일 확인에 필요한 holidays 패키지가 없습니다. requirements.txt를 설치하세요.")

    return False, ""
