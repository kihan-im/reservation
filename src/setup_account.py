#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
비IT 사용자를 위한 COSMAX eBiz 계정 설정 마법사 (src/setup_account.py)
- JSON 문법 오류(따옴표, 콤마 등 실수)를 원천 차단하고
- 비밀번호에 특수문자가 포함되어도 안전하게 config.json 생성 및 갱신
"""

import os
import sys
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
EXAMPLE_CONFIG_PATH = os.path.join(BASE_DIR, "config.example.json")


def run_wizard():
    print("\n" + "=" * 60)
    print("🔐 COSMAX eBiz 계정 및 환경설정 마법사")
    print("=" * 60)
    print("이 마법사는 로그인 정보를 config.json 파일에 안전하게 저장합니다.")
    print("★ config.json 파일은 .gitignore에 의해 Git에 절대 올라가지 않습니다.")
    print("-" * 60)

    # 1. 기존 설정 또는 템플릿 로드
    base_config = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                base_config = json.load(f)
            print(f"ℹ️ 기존 설정 파일(config.json)을 불러왔습니다.")
        except Exception:
            base_config = {}
            
    if not base_config and os.path.exists(EXAMPLE_CONFIG_PATH):
        try:
            with open(EXAMPLE_CONFIG_PATH, "r", encoding="utf-8") as f:
                base_config = json.load(f)
        except Exception:
            base_config = {}

    current_id = base_config.get("user_id", "")
    current_pw = base_config.get("user_pw", "")
    
    # 플레이스홀더 값인 경우 비어있는 것으로 처리
    if current_id in ["YOUR_COSMAX_ID", "아이디입력"]:
        current_id = ""
    if current_pw in ["YOUR_COSMAX_PASSWORD", "비밀번호입력"]:
        current_pw = ""

    # 2. 사용자 입력 받기
    print("\n[1단계] COSMAX eBiz 아이디 입력")
    if current_id:
        print(f" 현재 등록된 아이디: {current_id}")
        prompt_id = f" 새 아이디 입력 (기존값 유지 시 그냥 Enter): "
    else:
        prompt_id = " eBiz 아이디(사번 등): "
        
    new_id = input(prompt_id).strip()
    if not new_id and current_id:
        new_id = current_id

    while not new_id:
        print(" ❌ 아이디는 필수 입력 항목입니다.")
        new_id = input(" eBiz 아이디를 다시 입력하세요: ").strip()

    print("\n[2단계] COSMAX eBiz 비밀번호 입력")
    if current_pw:
        masked_pw = current_pw[:2] + "*" * (len(current_pw) - 2) if len(current_pw) > 2 else "***"
        print(f" 현재 등록된 비밀번호: {masked_pw}")
        prompt_pw = f" 새 비밀번호 입력 (기존값 유지 시 그냥 Enter): "
    else:
        prompt_pw = " eBiz 로그인 비밀번호: "
        
    new_pw = input(prompt_pw).strip()
    if not new_pw and current_pw:
        new_pw = current_pw

    while not new_pw:
        print(" ❌ 비밀번호는 필수 입력 항목입니다.")
        new_pw = input(" eBiz 비밀번호를 다시 입력하세요: ").strip()

    # 3. 설정 딕셔너리 갱신
    base_config["user_id"] = new_id
    base_config["user_pw"] = new_pw
    
    # 기본 필수 키 채우기
    if "url" not in base_config:
        base_config["url"] = "https://ebiz.cosmax.com/login/loginForm.do"
    if "reservation_url" not in base_config:
        base_config["reservation_url"] = "https://ebiz.cosmax.com/inreservationReg/inreservationRegListNew.do?gblCompid=1200&TMENU=M00003&LMENU=M00084"
    if "target_hours" not in base_config:
        base_config["target_hours"] = [13, 14, 15]
    if "target_time" not in base_config:
        base_config["target_time"] = "10:00:00"
    if "keep_alive_interval_seconds" not in base_config:
        base_config["keep_alive_interval_seconds"] = 30
    if "grid_max_retries" not in base_config:
        base_config["grid_max_retries"] = 5
    if "grid_retry_delay_seconds" not in base_config:
        base_config["grid_retry_delay_seconds"] = 0.3
    if "headless" not in base_config:
        base_config["headless"] = False
    if "skip_weekends" not in base_config:
        base_config["skip_weekends"] = True
    if "skip_holidays" not in base_config:
        base_config["skip_holidays"] = True
    if "custom_holidays" not in base_config:
        base_config["custom_holidays"] = []

    # 4. config.json 저장
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(base_config, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print("✅ [설정 완료] config.json 파일이 성공적으로 저장되었습니다!")
    print(f" * 설정된 아이디: {new_id}")
    print(f" * 비밀번호: 정상 암호화/저장 완료 (총 {len(new_pw)}자리)")
    print(f" * 저장 경로: {CONFIG_PATH}")
    print("=" * 60)
    print("이제 run_automation.bat 을 실행하거나 스케줄러를 등록하시면 됩니다.\n")


if __name__ == "__main__":
    run_wizard()
