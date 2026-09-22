# COSMAX eBiz 입고예약 자동화

COSMAX eBiz에 로그인하고 한국 시각 기준 목표 시각에 **청북2층·일반품목·13/14/15시**를 병렬로 처리합니다. 기존 체크를 유지하고, 미선택 항목 중 납품허용(`O`)이며 선택 가능한 자급자재를 위에서부터 최대 3개를 추가 선택합니다. 남은 허용 수량이 1~2개면 그만큼만 선택하고, 이미 한도에 도달했으면 추가·저장을 생략합니다. 신규 예약은 일반품목 최소 수량도 충족해야 하며, 신규 예약의 파렛트/차량 수는 각각 1로 입력합니다. 수정 가능한 기존 예약은 품목을 먼저 조회하고 기존 파렛트/차량 수를 유지합니다. 예약일은 사이트가 제공하는 선택값을 사용하며 실행일과 다를 수 있습니다.

저장 HTTP/JSON 응답과 새로 조회한 예약 목록의 업체·시간대·창고·예약번호를 확인합니다. `WAIT`는 확정과 구분하며, 별도 대기 저장 응답까지 확인합니다. 네트워크와 사이트 처리 속도에 따라 소요 시간이 달라집니다. 0.1초 완료나 예약 확보를 보장하지 않습니다.

## 시작하기

Python 3.13에서 로컬 검증했습니다. 처음 설치할 때는 아래 순서대로 진행하세요.

### Windows

Python 3.13 설치 시 **Add Python to PATH**를 선택하고 프로젝트 폴더를 준비합니다. PowerShell에서 실행할 때는 명령 앞에 `.\`를 붙입니다.

윈도우 실행 파일은 다음 **2개**를 함께 유지합니다.

| 파일 | 역할 |
|---|---|
| `run_automation.bat` | 설치·계정 설정·점검·실제 예약·스케줄러 관리의 공통 실행 파일 |
| `register_scheduler.ps1` | BAT에서 호출하는 스케줄러 등록·해제 처리 |

BAT 안내 문구는 Windows 인코딩 호환성을 위해 영문으로 표시하며, 아래 표의 메뉴 번호를 그대로 사용합니다.

**더블클릭 실행:** `run_automation.bat`을 열고 번호를 선택합니다. 작업이 끝나면 결과를 확인하고 아무 키나 눌러 닫습니다. 다음 단계는 다시 열어 선택합니다. 메뉴 5번은 실제 예약을 저장합니다.

**명령으로 실행:** 프로젝트 폴더의 명령 프롬프트에서 아래 순서로 실행합니다.

| 순서 | 메뉴 | 명령 | 수행 내용 |
|---|---|---|---|
| 1 | 1번 | `run_automation.bat --install-only` | 가상환경·패키지·Chromium 설치 또는 복구 |
| 2 | 2번 | `run_automation.bat --setup-account` | 계정과 환경 설정을 `config.json`에 저장 |
| 3 | 3번 | `run_automation.bat --check-config` | 브라우저 없이 설정 검사 |
| 4 | 4번 | `run_automation.bat --headful --force --dry-run` | 최대화된 창으로 로그인·조회·폼 입력 점검, 최종 저장 생략 |
| 5 | 5번 | `run_automation.bat --headful` | 실제 예약 실행. 설정된 목표 시각까지 대기 후 저장 |
| 6 | 6번 | `run_automation.bat --register-scheduler` | 평일 자동 실행 등록 또는 갱신 |

5번은 수동 예약이 필요할 때, 6번은 정기 실행을 사용할 때 선택합니다. 정기 실행만 사용할 경우 4번 점검 후 6번으로 진행하면 됩니다. 목표 시각이 이미 지났다면 실제 실행은 대기 없이 진행합니다.

특정 시간만 점검하려면 `run_automation.bat --headful --force --dry-run --hours 13`을 사용합니다. 사이트에서 해당 슬롯을 닫아 두었으면 점검도 중단될 수 있습니다. `--force`는 휴일 검사만 생략하며, 저장을 막는 옵션은 `--dry-run`입니다.

스케줄러는 **평일 09:50**에 `run_automation.bat --headless --no-pause`를 실행하며, 기본 예약 목표 시각은 **10:00 한국 시각**입니다. Windows 로그인 상태와 한국 시간대 설정이 필요합니다. `--no-pause`는 종료 시 키 입력을 기다리지 않고, 환경이나 설정이 없으면 오류로 종료합니다.

Windows의 headless 실행은 기본적으로 **시간대별 콘솔 3개**를 표시합니다. 기존 콘솔에는 13시 로그를, 추가 콘솔에는 14·15시 로그를 표시하며 공통 로그인·오류 로그는 각 콘솔에 함께 표시합니다. 로그인과 예약 실행은 여전히 하나의 프로세스에서 수행합니다. 기존 스케줄러도 코드 업데이트 후 자동 적용되므로 다시 등록할 필요가 없습니다. `--no-split-consoles`를 붙이면 기존 단일 콘솔로 실행하고, 화면 표시 모드에서도 분리하려면 `--split-consoles`를 사용합니다. `--hours`를 지정하면 해당 시간대만 표시합니다.

14·15시 표시용 콘솔을 닫아도 예약은 계속되지만, 원래 실행 콘솔(기본 13시)을 닫으면 전체 실행이 중단될 수 있습니다. 추가 콘솔은 예약 프로세스 종료 시 자동으로 닫히며, 결과는 `log/날짜/시간대/`에 남습니다. 콘솔 생성 실패 시 원래 콘솔에 전체 로그를 표시하며 계속 실행합니다.

자동 실행을 중지하려면 메뉴 **7번** 또는 `run_automation.bat --unregister-scheduler`를 실행합니다. 메뉴 **0번**은 종료입니다. 프로젝트 폴더를 옮기면 새 위치에서 스케줄러를 다시 등록하세요. 이전 개별 BAT 3개의 기능은 공통 BAT에 통합했습니다.

### macOS / Linux

프로젝트 폴더의 터미널에서 순서대로 실행합니다.

```bash
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
venv/bin/python -m playwright install chromium
venv/bin/python src/setup_account.py
venv/bin/python main.py --check-config
./run_automation.sh --headful --force --dry-run
```

점검 후 실제 예약 실행은 `./run_automation.sh --headful`입니다. 화면 없이 실행하려면 `./run_automation.sh --headless`를 사용합니다. Windows BAT 메뉴와 PowerShell 스케줄러는 이 환경에서 사용하지 않습니다.

## 영상 녹화 (선택)

녹화는 기본으로 꺼져 있습니다. 이번 실행만 녹화하려면 다음 명령을 사용합니다.

```bat
run_automation.bat --headful --record-video
```

저장 없는 13시 점검은 `run_automation.bat --headful --record-video --force --dry-run --hours 13`입니다. macOS/Linux에서는 `./run_automation.sh --headful --record-video`를 사용합니다.

메뉴 4·5번에서도 녹화하려면 `config.json`에 `"record_video": true`를 설정합니다. **`headless=false`일 때만 녹화하며, `headless=true`에서는 옵션이 켜져 있어도 녹화하지 않습니다.** 메뉴 6번의 자동 실행도 headless이므로 녹화하지 않습니다. `--no-record-video`로 이번 실행만 끌 수 있습니다.

영상은 각 탭을 연 시점부터 브라우저 종료까지(로그인·목표 시각 대기 포함) 무음 WebM으로 기록합니다. 종료 후 `log/날짜/13/video_실행시각_attempt1_13.webm`처럼 시간대별 폴더에 저장하며, 같은 폴더의 HTML에서 재생하거나 내려받을 수 있습니다. [Playwright 영상 녹화](https://playwright.dev/python/docs/videos)를 사용하므로 별도 패키지는 필요하지 않습니다.

영상에는 사이트 화면이 담기며, 브라우저 주소 표시줄·탭·기본 `alert/confirm` 팝업은 포함되지 않습니다. 기본 팝업은 기존 Windows PNG 캡처와 문구 로그로 확인합니다. 사이트 내부 안내창은 영상에 포함됩니다. 브라우저를 정상 종료해야 파일이 완성되며, 강제 종료 시 불완전한 영상이나 임시 이름의 파일이 남을 수 있습니다.

## 실행과 결과

1. 설정과 휴일을 검사하고 한 번 로그인한 세션으로 시간대별 탭을 준비합니다.
2. 창고 선택과 예약 목록 조회를 확인합니다. HTTP `Date` 헤더는 시각 참고값이며 NTP 정밀 동기화가 아닙니다. 한국 시각 목표까지 대기하며 마지막 5초에는 세션 유지 요청을 보내지 않습니다.
3. 예약일·시간·창고·일반품목을 검증하고 자급자재를 조회합니다. 사이트 오류 알림은 숨기지 않고 중단합니다.
4. 저장 직전 현재 프로세스의 중복 방지 상태를 남기고, 저장 및 재조회 결과를 분류합니다.

| 상태 | 의미 |
|---|---|
| `CONFIRMED` | 이번 실행의 저장 성공 및 예약번호 재조회 확인 |
| `WAIT` | 대기 접수 확인. 납품 가능한 확정 상태와 다름 |
| `FAILED` | 준비 실패 또는 명시적인 저장 거절 |
| `NO_CHANGE` | 이미 품목 수 한도에 도달하여 추가·저장 생략. 이번 실행의 예약 성공을 뜻하지 않음 |
| `EXISTING_CONFIRMED` | 기존 서버 예약번호와 목표 품목 수를 확인해 추가 저장이 필요 없음 |
| `UNKNOWN` | 저장 시도 이후 응답/후속 저장/재조회 검증이 끝나지 않음 |
| `SUBMITTING` | 현재 프로세스에서 같은 시간대의 저장을 처리 중 |
| `EXISTING` | 이전 버전에서 기존 예약번호 때문에 중단한 결과. 현재는 체크박스가 활성화되어 있으면 기존 품목 조회 후 추가 진행 |
| `DRY_RUN` | 저장 전까지 점검 완료 |
| `SKIPPED` | 휴일로 실행 생략 |

종료 코드: **0** 전체 확정·점검 완료·휴일 생략, **1** 실패, **2** 일부 성공 또는 대기/결과 미확인/기존 내역 확인 필요. `0`만으로 실제 예약 실행 여부를 판단하지 말고 각 시간대 로그·HTML의 `[RESULT]`와 `[COMPLETE]`도 확인합니다.

## 기록과 재실행

```text
log/
  YYYYMMDD/
    13/
      automation_YYYYMMDD_HHMMSS_ffffff.log
      automation_YYYYMMDD_HHMMSS_ffffff.html
      reservation_YYYYMMDD_HHMMSS_ffffff_attempt1_13_03_....png
      video_YYYYMMDD_HHMMSS_ffffff_attempt1_13.webm  # 녹화 시에만 생성
    14/                           # 같은 형식
    15/                           # 같은 형식
```

각 시간대 폴더에 로그·HTML·이미지와 선택적으로 녹화한 영상을 저장합니다. 실행 시각과 재시도 번호는 파일명으로 구분하며, 실행별 하위 폴더나 별도 `result.json`은 만들지 않습니다. `[RESULT]`는 해당 시간대 결과, `[COMPLETE]`는 전체 실행 상태와 종료 코드입니다. 공통 로그인·준비 로그는 각 시간대 로그에 함께 들어갑니다.

로그는 실행 중 파일에 지속 기록하고 종료 시 각 HTML을 만듭니다. HTML과 이미지를 같은 폴더에 보관하면 썸네일을 열 수 있습니다. 사이트 내부 완료 안내는 `*_08_save_notice.png`, Windows 화면 표시 모드의 브라우저 기본 팝업은 `*_browser_dialog_*.png`로 남깁니다. headless 및 Windows 외 환경의 브라우저 기본 팝업은 문구만 기록합니다. 기존 파일은 덮어쓰거나 자동 삭제하지 않습니다.

실행 기록은 `log/`에 통일합니다. 시간대별 중복 처리는 현재 프로세스의 메모리에서 막고, 재시작 후 실제 예약 여부는 COSMAX 서버의 예약번호와 품목 수를 다시 조회해 판단합니다. 이전 버전의 `.reservation_state` 파일은 더 이상 읽거나 갱신하지 않습니다.

서버에 예약번호가 있다는 이유만으로 중단하지 않습니다. 해당 시간대 체크박스가 활성화되어 있으면 기존 품목을 불러와 미선택 자재를 최대 3개, 남은 허용 수량과 선택 가능한 품목 수 이내에서 추가합니다. 매 실행마다 현재 체크박스와 서버 품목 수를 다시 확인합니다. 기존 예약번호가 있고 품목 수가 한도에 도달했으면 `EXISTING_CONFIRMED`로 성공 처리하며 저장을 생략합니다. `UNKNOWN`과 `FAILED`는 해당 시간대만 기본 15분 동안 재시도하고, 이미 성공한 시간대는 반복하지 않습니다. `SUBMITTING`은 현재 프로세스에서 같은 시간대의 중복 처리를 막습니다. 각 탭은 사전 준비부터 목표 시각 대기·예약·결과 기록까지 독립 실행하므로 닫힌 시간대의 대기나 실패가 열린 시간대를 막지 않습니다.

같은 계정을 여러 PC에서 동시에 실행해도 각 프로세스는 독립적으로 예약을 시도합니다. 한 PC의 저장이 거절되거나 응답이 유실되어도 동일 날짜·창고·시간·업체의 예약번호가 서버에서 확인되면 다른 PC가 완료한 예약을 `EXISTING_CONFIRMED`로 성공 처리합니다. 한 PC에서는 브라우저 프로세스를 여러 개 띄우기보다 기본 13·14·15시 탭 한 세트만 실행하는 편이 리소스 사용이 적습니다.

미처리 시간만 재실행하려면 `--hours 14 15`처럼 지정합니다. `UNKNOWN`도 `--hours 13 --headful`처럼 일반 실행하면 COSMAX 서버 상태를 다시 확인한 뒤 진행합니다. `--retry-unknown`은 이전 명령과의 호환을 위해 남겨 두었으며 이제 필요하지 않습니다. `SUBMITTING`은 현재 프로세스 안에서 같은 시간대를 중복 처리하지 않도록 보호합니다.

## 설정

설정 파일이 존재하지만 잘못된 JSON이면 기본값으로 진행하지 않고 종료합니다. 설정 파일이 없을 때의 기본값 처리 및 계정 저장 방식은 기존대로입니다. 상대 `log_dir`은 설정 파일이 있는 폴더를 기준으로 해석합니다. 기본값은 `log`이며, 공통 설정 로더가 이전 기본값인 `"logs"`, `"./logs"`, `"logs/"`도 `log`로 통일합니다. 다른 사용자 지정 경로는 유지합니다.

```json
{
  "url": "https://ebiz.cosmax.com/login/loginForm.do",
  "reservation_url": "https://ebiz.cosmax.com/inreservationReg/inreservationRegListNew.do?gblCompid=1200&TMENU=M00003&LMENU=M00084",
  "user_id": "S102190",
  "user_pw": "90801277**//123",
  "target_hours": [
    13,
    14,
    15
  ],
  "target_time": "10:00:00",
  "keep_alive_interval_seconds": 30,
  "headless": false,
  "record_video": false,
  "skip_weekends": true,
  "skip_holidays": true,
  "custom_holidays": [],
  "grid_wait_timeout_seconds": 60,
  "site_timeout_seconds": 60,
  "save_timeout_seconds": 60,
  "reservation_retry_window_seconds": 900,
  "reservation_date": "",
  "keep_alive_timeout_seconds": 3,
  "dry_run": false
}
```

`target_hours`는 중복 없는 8/9/10/11/13/14/15시 목록입니다. 시간은 `HH:MM:SS`, 대기/시간 제한은 양수여야 합니다. 화면 표시 모드는 탭·주소 표시줄이 보이도록 브라우저 창을 최대화하고 실제 창 크기에 맞춥니다. `viewport_width`/`viewport_height`는 백그라운드(headless) 모드에서만 사용하며 기본값은 2200/1080입니다. `max_pre_target_retries` 기본값 5, `pre_target_retry_delay_seconds` 기본값 5입니다.

`site_timeout_seconds`는 조회·화면 로딩의 회당 대기 시간(기본 60초), `save_timeout_seconds`는 저장 응답 대기 상한(기본 60초)입니다. 저장 응답이 지연되면 3초 뒤부터 간격을 늘려 서버 예약 내역을 확인하지만 기존 저장 요청은 유지합니다. 예약이 확인되면 즉시 완료합니다. 저장 요청이 네트워크 오류, HTTP 408·429·5xx, 비정상 응답으로 끝난 경우 서버에 예약이 없는 것을 두 번 확인한 뒤에만 사이트 알림을 닫고 다시 저장합니다. 서버 내역이 불명확하면 재저장하지 않고 `UNKNOWN`으로 남깁니다. 해당 시간대는 `reservation_retry_window_seconds`(기본 900초) 동안 독립 복구하며, 성공한 시간대는 다시 처리하지 않습니다. 시간대 활성화 전체 대기는 `grid_wait_timeout_seconds`(기본 60초)로 제한하며, 예전 설정의 5초 값도 실행 시 60초로 보정합니다. 이 안에서 목록 재조회 간격을 1→2→4초로 늘립니다. `reservation_date`를 지정하면 화면의 예약일과 일치할 때만 진행합니다.

`grid_max_retries`, `grid_retry_delay_seconds`, `screenshot_dir`은 사용하지 않습니다. 기존 `clean_daily_logs=true`도 로그를 삭제하지 않으며 경고를 남깁니다. 공휴일 검사가 켜져 있는데 `holidays`가 없으면 불완전한 달력으로 진행하지 않고 중단합니다.

## 테스트

```bash
venv/bin/python -m unittest discover -s tests -v
venv/bin/python -m pip check
```

브라우저 테스트는 로컬 모의 페이지의 모든 요청을 가로채며 외부 예약을 만들지 않습니다. 실제 사이트의 DOM/응답 변경과 Windows 스케줄러 동작은 운영 환경에서 별도 확인해야 합니다.

- [운영 가이드](docs/OPERATIONS_GUIDE.md)
- [Windows 설치](docs/WINDOWS_SETUP_GUIDE.md)
- [문제 해결](docs/TROUBLESHOOTING.md)
