#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
설정 파일 로드 및 관리 모듈
"""

import os
import json
import logging
import math
import re
from datetime import date

logger = logging.getLogger("CosmaxAutoLogin")

DEFAULT_CONFIG = {
    "url": "https://ebiz.cosmax.com/login/loginForm.do",
    "reservation_url": "https://ebiz.cosmax.com/inreservationReg/inreservationRegListNew.do?gblCompid=1200&TMENU=M00003&LMENU=M00084",
    "user_id": "S102190",
    "user_pw": "90801277**//123",
    "target_time": "10:00:00",
    "keep_alive_interval_seconds": 30,
    "log_dir": "log",
    "headless": False,
    "record_video": False,
    "viewport_width": 2200,
    "viewport_height": 1080,
    "grid_wait_timeout_seconds": 5.0,
    "target_hours": [13, 14, 15],
    "skip_weekends": True,
    "skip_holidays": True,
    "custom_holidays": [],
    "max_pre_target_retries": 5,
    "pre_target_retry_delay_seconds": 5,
    "clean_daily_logs": False,
    "keep_alive_timeout_seconds": 3,
    "dry_run": False
}


def validate_config(config: dict) -> dict:
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d", str(config.get("target_time", ""))):
        raise ValueError("target_time은 HH:MM:SS 형식이어야 합니다.")
    hours = config.get("target_hours")
    if (not isinstance(hours, list) or not hours or
            any(type(h) is not int or h not in (8, 9, 10, 11, 13, 14, 15) for h in hours) or
            len(set(hours)) != len(hours)):
        raise ValueError("target_hours는 중복 없는 시간대 목록이어야 합니다: 8,9,10,11,13,14,15")
    for key in ("keep_alive_interval_seconds", "keep_alive_timeout_seconds", "grid_wait_timeout_seconds",
                "pre_target_retry_delay_seconds", "viewport_width", "viewport_height"):
        value = config[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key}는 유한한 양수여야 합니다.")
    for key in ("viewport_width", "viewport_height", "max_pre_target_retries"):
        if type(config[key]) is not int or config[key] < 0:
            raise ValueError(f"{key}는 음수가 아닌 정수여야 합니다.")
    for key in ("headless", "record_video", "dry_run", "skip_weekends", "skip_holidays", "clean_daily_logs"):
        if type(config[key]) is not bool:
            raise ValueError(f"{key}는 true 또는 false여야 합니다.")
    for key in ("url", "reservation_url", "log_dir"):
        if not isinstance(config[key], str) or not config[key].strip():
            raise ValueError(f"{key}는 비어 있을 수 없습니다.")
    if not isinstance(config["custom_holidays"], list):
        raise ValueError("custom_holidays는 YYYY-MM-DD 목록이어야 합니다.")
    for day in config["custom_holidays"]:
        if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError("custom_holidays는 YYYY-MM-DD 목록이어야 합니다.")
        date.fromisoformat(day)
    return config


def load_config(config_path="config.json") -> dict:
    """기본값과 JSON을 병합한다. 존재하는 파일이 손상되면 실행을 중단한다."""
    config = DEFAULT_CONFIG.copy()
    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as f:
            user_config = json.load(f)
        if not isinstance(user_config, dict):
            raise ValueError("설정 파일의 최상위 값은 JSON 객체여야 합니다.")
        config.update(user_config)
    return validate_config(config)
