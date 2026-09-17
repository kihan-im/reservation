# 문제 해결

## 먼저 볼 기록

`log/YYYYMMDD/13/`에서 최신 `automation_*.html` 또는 `.log`를 열고 `[RESULT]`, `[FAIL]`, `[UNKNOWN]`, 통신 실패, `[COMPLETE]`를 검색합니다. 14·15시도 같은 방식입니다. 스크린샷은 같은 폴더에 있으며 실행 시각·재시도 번호가 파일명에 들어갑니다. 브라우저 기본 팝업은 Windows 화면 표시 모드에서 `*_browser_dialog_*.png`로 저장합니다. `브라우저 알림/팝업` 로그의 문구도 함께 확인하세요. headless 및 Windows 외 환경에서는 팝업 문구만 기록합니다.

| 증상 | 확인 및 대응 |
|---|---|
| 이전 로그 경로나 result.json이 안 보임 | 실행 기록은 log/날짜/시간대에 통일. 상태는 HTML의 [RESULT]·[COMPLETE]와 COSMAX 서버 예약 목록에서 확인 |
| HTML 이미지가 안 열림 | 해당 실행의 HTML과 PNG를 같은 시간대 폴더에 함께 보관했는지 확인 |
| 설정 오류 | `--check-config` 실행. JSON 형식, 중복/빈 시간대, 시간 형식, 양수 시간 제한을 확인 |
| 로그인 완료 확인 실패 | 로그인 화면의 실제 오류와 접속 상태 확인. JSESSIONID 쿠키만으로 로그인 성공을 판단하지 않음 |
| 창고 또는 예약 정보 불일치 | 청북2층·일반품목·대상 시간·사이트 예약일을 확인. 다른 선택값으로 자동 진행하지 않음 |
| 조회 버튼 클릭 시 부모 창이 pointer events를 가로챔 | 전체 페이지 캡처가 resize 이벤트를 발생시켜 부모 팝업을 앞으로 올리는 사이트 동작. 현재 화면 캡처를 사용하는 최신 코드로 새로 실행 |
| 자급자재 알림이 비어 있음 | HTML 알림과 통신 로그의 HTTP 오류/요청 실패 확인. 팝업을 강제로 숨겨 진행하지 않음 |
| 추가 가능한 자급자재 없음 / 일반품목 최소 수량 미달 | 기존 체크를 유지하고 `O`이며 선택 가능한 항목만 최대 3개 선택. 신규 품목이 없거나 추가 후에도 사이트 최소 수량에 못 미치면 저장 생략 |
| 기대 품목 수 불일치 | 팝업 체크 수·목록 행 수·화면 종목 수는 다를 수 있음. 추가 반영은 행 수로, 허용 한도는 화면 종목 수로 검사 |
| 품목 수 제한 초과 | 남은 한도 내에서 최대 3개를 선택. 저장 직전 한도 변경 등으로 초과하면 중단하며 `[RESULT]`에 품목 수·한도 기록 |
| 품목 수 허용 한도 확인 실패 | 사이트의 시간대별 한도 입력란을 읽지 못해 저장을 중단. 화면 로딩·사이트 변경 여부 확인 |
| 화면이 잘리거나 스크린샷에 목록 일부만 나옴 | 화면 확인은 `--headful` 사용. 스크린샷은 팝업 겹침 방지를 위해 보이는 범위만 캡처하며, 전체 목록은 브라우저에서 스크롤해 확인 |
| 시간대 미오픈/마감 | 사이트의 슬롯 상태 확인. 필요하면 `grid_wait_timeout_seconds` 조정. 폐기된 `grid_max_retries`는 효과 없음 |
| Keep-Alive 실패 | 네트워크·로그인 만료 확인. 요청 제한은 `keep_alive_timeout_seconds`, 주기는 `keep_alive_interval_seconds` |
| `WAIT` | 대기 접수 상태. 사이트에서 예약 확정으로 바뀌었는지 확인 |
| `[WAITING]` / `[RETRY]` | 서버 지연 대기 또는 시간대별 복구. 기본 조회·저장 응답은 각각 60초, 전체 시간대 복구는 15분 |
| `EXISTING_CONFIRMED` | 기존 예약번호와 목표 품목 수를 서버에서 확인해 추가 저장이 필요 없는 성공 결과 |
| `NO_CHANGE` | 예약번호 없이 품목 수 한도에 도달해 추가·저장을 생략한 결과 |
| `UNKNOWN` | 저장 응답 유실, 후속 대기 저장 실패, 예약번호 재조회 불일치 등. 다음 실행에서는 이전 기록에 막히지 않고 다시 저장 시도. [RESULT]와 서버 내역으로 결과 확인 |
| `SUBMITTING` | 현재 프로세스에서 같은 슬롯의 조회·예약을 처리 중. 재시작하면 서버 내역을 다시 확인 |
| `UnicodeDecodeError: cp949`로 설치 실패 | 이전 requirements.txt의 UTF-8 한글 주석을 pip 24.2가 CP949로 읽은 오류. 최신 requirements.txt와 run_automation.bat으로 교체한 뒤 `--install-only` 재실행 |
| 메뉴 일부가 깨지고 `not recognized` 발생 | BAT 인코딩·줄바꿈 또는 파일 손상 여부 확인. 현재 BAT는 영문 ASCII 문구를 사용하며 메뉴 번호는 동일함. 최신 파일 전체를 교체 |
| 설치 실패 | `run_automation.bat --install-only`의 첫 실패 명령 확인. 프록시/인터넷/권한 확인 후 재시도 |
| 공휴일 패키지 없음 | 고정된 requirements.txt 설치. 불완전한 고정일 달력으로 진행하지 않음 |
| BAT 더블클릭 후 예약이 시작되지 않음 | 현재는 통합 메뉴가 열림. 실제 예약은 5번, 저장 없는 점검은 4번 선택 |
| 무인 실행에서 설치·설정 필요 오류 | `--no-pause` 없이 `--install-only`와 `--setup-account`를 먼저 실행한 뒤 `--check-config`로 검사 |
| 스케줄러 등록 중 `MSFT_TaskExecAction` / `Action variable` 오류 | 이전 PowerShell 스크립트의 `$Action` 매개변수와 `$action` 변수 충돌. 최신 register_scheduler.ps1로 교체한 뒤 메뉴 6번으로 다시 등록 |
| 스케줄러 미실행 | Windows 로그인 상태, 한국 시간대, 작업 동작 경로, 절전/전원 상태 확인 |

## Windows 설치 중 인코딩 오류

`UnicodeDecodeError: 'cp949' codec can't decode byte 0x80 in position 23`은 이전 `requirements.txt` 첫 줄의 한글 주석에서 재현됩니다. pip 업데이트 안내는 실패 원인이 아닙니다. 현재 패키지 목록의 주석과 BAT 안내는 ASCII로 작성하여 Windows 코드 페이지의 영향을 제거했습니다. 계정 설정 마법사는 기존 한국어 안내를 유지합니다.

1. Windows 프로젝트 폴더의 `run_automation.bat`과 `requirements.txt`를 최신 파일 전체로 교체합니다. `config.json`과 기존 `venv`는 유지합니다.
2. 프로젝트 폴더에서 `run_automation.bat --install-only`를 다시 실행합니다.
3. 설치 성공 후 `run_automation.bat --check-config`를 실행합니다. 계정 설정이 필요하면 `run_automation.bat --setup-account`를 먼저 실행합니다.

## 저장 팝업이 안 보이거나 `UNKNOWN`으로 끝날 때

브라우저 기본 알림·확인창과 사이트 내부 HTML 안내는 처리 방식이 다릅니다.

- **브라우저 기본 팝업:** Windows의 `--headful` 모드에서는 해당 탭을 앞으로 가져와 브라우저 창과 팝업을 함께 촬영한 뒤 확인을 누릅니다. 파일은 `*_browser_dialog_01.png`처럼 순번을 붙이며 같은 시간대 폴더와 HTML에서 볼 수 있습니다. 캡처는 최대 4초이고, 실패하면 경고와 팝업 문구를 남긴 뒤 확인을 눌러 진행합니다.
- **사이트 내부 완료 안내:** 서버 저장 응답을 받은 뒤 안내창이 표시될 때까지 기다려 문구와 `*_08_save_notice.png`를 저장합니다. 대상 시간과 확정·대기 문구를 확인한 뒤 닫습니다. 이후 목록 재조회까지 성공해야 확정·대기 결과로 기록합니다.

완료·대기 팝업 이미지는 같은 시간대 폴더의 `*_08_save_notice.png`를 확인하세요. 이후 `*_09_reservation_result.png`, `*_10_final.png`는 안내창을 닫은 뒤 화면입니다. 브라우저 기본 `alert/confirm`은 `*_browser_dialog_*.png`에서 확인합니다. 이 기능은 화면의 픽셀을 촬영하는 Windows [CopyFromScreen](https://learn.microsoft.com/en-us/dotnet/api/system.drawing.graphics.copyfromscreen) 방식입니다. 메뉴 6번으로 등록한 스케줄러는 headless 모드라 네이티브 팝업 이미지가 없으며 문구만 기록합니다. macOS/Linux도 현재 문구만 기록합니다. Windows가 잠겨 있거나 다른 창이 전면에 있으면 캡처 실패 로그를 확인하세요.

저장 응답이 늦으면 3초 뒤부터 간격을 늘려 서버 예약 내역을 다시 확인하지만 기존 요청은 최대 60초 동안 유지합니다. 이 중 예약이 확인되면 재저장하지 않습니다. 저장 요청이 네트워크 오류, HTTP 408·429·5xx, 비정상 응답으로 끝난 경우에만 같은 시간대 예약이 두 번 연속 없음을 확인하고, 사이트 알림을 닫은 뒤 다시 저장합니다. 서버 내역을 확인할 수 없거나 서로 맞지 않으면 중복 저장하지 않고 `UNKNOWN`으로 남깁니다. 해당 시간대는 기본 15분 동안 독립적으로 복구합니다.

품목 수 제한은 자재 선택 전과 저장 직전에 검사합니다. 예를 들어 기존 6개·허용 8개이면 2개만 추가합니다. 기존 예약번호가 있고 이미 한도에 도달했으면 `EXISTING_CONFIRMED`, 예약번호가 없으면 `NO_CHANGE`이며, 저장 직전 한도가 변경되어 초과하면 `FAILED`로 원인을 남깁니다. 사이트가 저장 클릭 후 제한 경고를 표시한 경우에도 문구를 `ERROR`로 기록합니다. 응답 대기 실패 시 제한 초과·미달 경고가 있고 저장 요청이 전송되지 않았다면 `FAILED`, 요청이 이미 전송됐다면 `UNKNOWN`으로 기록하며 경고 원문을 `[RESULT]`에 보존합니다. 이전 버전 로그에서는 이 경고가 `INFO`, 최종 결과가 타임아웃으로만 남을 수 있습니다.

1. 해당 시간대 로그에서 저장 직전 품목 수와 브라우저 팝업 문구를 확인합니다.
2. 서버의 실제 예약 내역과 품목 수를 확인합니다.
3. 품목 수 제한을 해소하지 않고 동일한 추가 작업을 반복하지 않습니다. 자동화는 기존 품목을 삭제하거나 한도를 우회하지 않습니다.

13시를 점검할 때 14·15시의 비활성 체크박스 오류와 섞어 판단하지 마세요. 아래처럼 `--hours 13`으로 범위를 좁힐 수 있습니다.

## 재현 명령

```bat
run_automation.bat --check-config
run_automation.bat --headful --force --dry-run --hours 13
```

PowerShell에서는 명령 앞에 `.\`를 붙입니다. macOS/Linux에서는 `run_automation.bat` 대신 `./run_automation.sh`를 사용합니다.

점검은 최종 저장을 생략하므로 저장 버튼 이후의 서버 검증·팝업까지 재현하지는 않습니다. `--headful --force`만 사용하면 실제 예약이 진행됩니다.

`UNKNOWN` 결과가 있어도 `run_automation.bat --headful --hours 13`으로 실행하면 COSMAX 서버 예약번호와 품목 수를 다시 확인한 뒤 필요한 경우 실제 예약을 다시 시도합니다. `--retry-unknown`은 호환용으로 유지하지만 지정할 필요가 없습니다. 이전 버전의 `.reservation_state` 파일은 더 이상 사용하지 않습니다. 자세한 규칙은 [운영 가이드](OPERATIONS_GUIDE.md)를 참고하세요.

## 회귀 검사

```bat
venv\Scripts\python.exe -m unittest discover -s tests -v
venv\Scripts\python.exe -m pip check
```

macOS/Linux에서는 위 Python 경로를 `venv/bin/python`으로 바꿉니다.

브라우저 검사는 외부 예약을 만들지 않는 로컬 모의 페이지를 사용합니다. Windows BAT 검사는 임시 폴더의 대체 프로그램으로 인수 전달·종료 코드·무인 실행 오류 처리를 확인하며, Windows 외 환경에서는 건너뜁니다. 이 검사는 실제 작업 스케줄러를 등록하지 않습니다. 테스트 통과만으로 실제 사이트의 성공 예약이나 Windows 정기 실행까지 검증된 것은 아닙니다.

## 녹화 영상이 없거나 팝업이 보이지 않음

- 녹화 기본값은 꺼짐입니다. `--headful --record-video` 또는 `headless=false`, `record_video=true` 설정이 필요합니다. `--no-record-video`가 있으면 녹화하지 않습니다.
- `headless=true`에서는 요청 여부와 관계없이 녹화하지 않습니다. 메뉴 6번으로 등록한 스케줄러가 여기에 해당합니다.
- 실행이 끝난 뒤 `log/날짜/시간대/video_*.webm`과 `동영상 저장` 로그를 확인합니다. 종료 전에는 임시 파일명이며, 강제 종료하면 완성되지 않을 수 있습니다. `동영상 저장 실패` 또는 `녹화 마무리 실패` 경고도 확인하세요.
- 브라우저 기본 `alert/confirm`은 사이트 화면 영상에 포함되지 않습니다. Windows 화면 표시 모드의 `*_browser_dialog_*.png`와 팝업 문구 로그를 확인합니다.
- FFmpeg 실행 파일을 찾을 수 없다는 오류라면 메뉴 1번 또는 `venv\Scripts\python.exe -m playwright install chromium`으로 Playwright 브라우저 구성 요소를 복구합니다.
