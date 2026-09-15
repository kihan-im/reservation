# 문제 해결

## 먼저 볼 기록

최신 `logs/YYYYMMDD/HHMMSS_ffffff/result.json`에서 시간대와 상태를 찾고 같은 폴더의 HTML에서 `[FAIL]`, `[UNKNOWN]`, 통신 실패, `[COMPLETE]`를 검색합니다. `attempt_N/시간대/` 스크린샷은 오류 알림을 보존합니다.

| 증상 | 확인 및 대응 |
|---|---|
| 설정 오류 | `--check-config` 실행. JSON 형식, 중복/빈 시간대, 시간 형식, 양수 시간 제한을 확인 |
| 로그인 완료 확인 실패 | 로그인 화면의 실제 오류와 접속 상태 확인. JSESSIONID 쿠키만으로 로그인 성공을 판단하지 않음 |
| 창고 또는 예약 정보 불일치 | 청북2층·일반품목·대상 시간·사이트 예약일을 확인. 다른 선택값으로 자동 진행하지 않음 |
| 조회 버튼 클릭 시 부모 창이 pointer events를 가로챔 | 전체 페이지 캡처가 resize 이벤트를 발생시켜 부모 팝업을 앞으로 올리는 사이트 동작. 현재 화면 캡처를 사용하는 최신 코드로 새로 실행 |
| 자급자재 알림이 비어 있음 | HTML 알림과 통신 로그의 HTTP 오류/요청 실패 확인. 팝업을 강제로 숨겨 진행하지 않음 |
| 미선택 납품허용 자급자재 3개 미만 | 이미 체크된 항목을 제외하고 `O`이며 선택 가능한 항목이 3개 이상인지 확인. 기존 체크는 유지 |
| 시간대 미오픈/마감 | 사이트의 슬롯 상태 확인. 필요하면 `grid_wait_timeout_seconds` 조정. 폐기된 `grid_max_retries`는 효과 없음 |
| Keep-Alive 실패 | 네트워크·로그인 만료 확인. 요청 제한은 `keep_alive_timeout_seconds`, 주기는 `keep_alive_interval_seconds` |
| `WAIT` | 대기 접수 상태. 사이트에서 예약 확정으로 바뀌었는지 확인 |
| `UNKNOWN` | 저장 응답 유실, 후속 대기 저장 실패, 예약번호 재조회 불일치 등. 먼저 서버 내역 확인 |
| `SUBMITTING` | 같은 슬롯 실행 중이거나 비정상 종료. 다른 프로세스와 서버 내역을 확인하고 운영자 검토 |
| 설치 실패 | `run_automation.bat --install-only`의 첫 실패 명령 확인. 프록시/인터넷/권한 확인 후 재시도 |
| 공휴일 패키지 없음 | 고정된 requirements.txt 설치. 불완전한 고정일 달력으로 진행하지 않음 |
| 스케줄러 미실행 | Windows 로그인 상태, 한국 시간대, 작업 동작 경로, 절전/전원 상태 확인 |

## 재현 명령

```bat
run_automation.bat --check-config
run_automation.bat --headful --force --dry-run --hours 13
```

점검은 최종 저장을 생략합니다. `--headful --force`만 사용하면 실제 예약이 진행됩니다.

`UNKNOWN` 재시도는 서버에 미등록임을 확인한 시간만 `--hours 13 --retry-unknown`으로 지정합니다. 확정/대기/기존 예약을 덮어쓰거나 DB 전체를 삭제하지 마세요. 자세한 규칙은 [운영 가이드](OPERATIONS_GUIDE.md)를 참고하세요.

## 회귀 검사

```bat
venv\Scripts\python.exe -m unittest discover -s tests -v
venv\Scripts\python.exe -m pip check
```

테스트는 로컬 모의 페이지에서만 실행합니다. 테스트가 통과해도 실제 서비스의 변경된 응답 형식이나 Windows 예약 작업 동작까지 검증된 것은 아닙니다.
