#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
설정 파일 로드 및 관리 모듈
"""

import os
import json
import logging

logger = logging.getLogger("CosmaxAutoLogin")

DEFAULT_CONFIG = {
    "url": "https://ebiz.cosmax.com/login/loginForm.do",
    "reservation_url": "https://ebiz.cosmax.com/inreservationReg/inreservationRegListNew.do?gblCompid=1200&TMENU=M00003&LMENU=M00084",
    "user_id": "S102190",
    "user_pw": "90801277**//123",
    "target_time": "10:00:00",
    "keep_alive_interval_seconds": 30,
    "screenshot_dir": "screenshots",
    "log_dir": "logs",
    "headless": False,
    "skip_weekends": True,
    "skip_holidays": True,
    "custom_holidays": [],
    "max_pre_target_retries": 5,
    "pre_target_retry_delay_seconds": 5
}


def load_config(config_path="config.json") -> dict:
    """JSON 설정 파일을 읽어오거나 기본 설정값을 반환"""
    config = DEFAULT_CONFIG.copy()
    
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
                config.update(user_config)
                logger.info(f"설정 파일({config_path})을 읽어왔습니다.")
        except Exception as e:
            logger.warning(f"설정 파일 읽기 실패. 기본 설정을 사용합니다: {e}")
    else:
        logger.info(f"설정 파일({config_path})이 없어 기본 설정을 적용합니다.")
        
    return config
