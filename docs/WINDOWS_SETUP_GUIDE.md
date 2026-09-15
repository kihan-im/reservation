# Windows 설치와 스케줄러

## 1. 준비

Python 3.13과 인터넷 연결이 필요합니다. Python 설치 시 PATH 추가를 선택합니다. 프로젝트를 실행 계정이 읽고 쓸 수 있는 폴더에 두고, 명령 프롬프트에서 해당 폴더로 이동합니다.

```bat
python --version
run_automation.bat --install-only
setup_account.bat
run_automation.bat --check-config
```

환경 설치는 가상환경 생성, 고정 버전 패키지 설치, `pip check`, Chromium 설치 순서입니다. 한 단계라도 실패하면 종료 코드 1을 반환합니다. 설치 완료 표시(`venv/requirements.installed.txt`)는 모든 단계가 성공한 후 생성합니다. `--install-only`는 예약을 실행하지 않습니다.

수동 설치를 할 경우에도 배치 실행 전 `run_automation.bat --install-only`를 한 번 실행하여 설치 상태를 맞추세요. 요구 패키지나 브라우저가 변경되거나 손상되었을 때 같은 명령으로 복구합니다.

## 2. 저장 없이 점검

```bat
run_automation.bat --headful --force --dry-run
```

조회와 폼 입력까지 확인하고 저장 전 중단합니다. 예약 시간대가 활성화되지 않았으면 점검 실패가 정상일 수 있습니다. `--force`는 휴일만 무시하며 단독 사용 시 실제 저장이 가능합니다.

## 3. 정기 실행 등록

`register_scheduler.bat`을 실행합니다. 권한 오류가 발생하면 같은 실행 계정으로 관리자 권한 콘솔에서 재시도하세요. PowerShell이 설정과 등록된 작업 명령을 검사한 후 성공을 표시합니다. 기존 작업을 먼저 삭제하지 않고 갱신합니다.

- 작업 이름: `CosmaxAutoReservation`
- 실행: 평일 09:50, `run_automation.bat --headless --no-pause`
- 현재 Windows 사용자가 로그인한 상태에서 실행
- Windows 시간대는 한국(UTC+09:00)으로 설정
- 절전 해제를 요청하지만 PC 전원/하드웨어 설정에 따라 달라짐
- 중복 실행 무시, 실행 시간 제한 30분
- 놓친 작업의 뒤늦은 자동 실행 및 전체 작업 재시작은 사용하지 않음

`--no-pause`는 성공과 실패 모두 입력 대기 없이 종료합니다. 환경이나 설정이 없으면 무인 상태에서 설치 마법사를 열지 않고 오류로 종료합니다. 설치와 계정 설정을 먼저 끝내세요.

## 4. 운영 확인

작업 스케줄러에서 동작 경로와 트리거를 확인합니다. **작업의 수동 실행 버튼은 실제 예약을 수행합니다.** 최초 확인은 위 `--dry-run` 명령을 사용하세요.

정상 실행 결과는 [운영 가이드](OPERATIONS_GUIDE.md)의 `result.json`과 서버 예약 내역으로 판단합니다. 스케줄러 종료 코드만으로 확정 여부를 판단하지 않습니다. 등록 해제는 `unregister_scheduler.bat`을 사용합니다.

이 변경의 Windows 네이티브 동작은 macOS 로컬 테스트로 검증할 수 없으므로 대상 PC에서 설치·점검 모드·작업 등록을 확인해야 합니다.
