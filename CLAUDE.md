# kamoflauge (카모플라지, 카톡+위장): 인수인계 노트

이 문서는 클라우드 세션에서 만들던 작업을 로컬 맥 세션으로 넘기기 위한 것이다.
이 맥에서 직접 `kamoflauge check`와 `kamoflauge`을 돌리면서 이어서 작업하면 된다.

## 목표

연구실에서 몰래 카톡을 하기 위한 프로그램이다. 맥 카카오톡을 **Claude Code처럼 보이는 터미널 UI**로 읽고 보낸다.
- 상대 메시지는 `⏺ Read(<가명 파일명>)` 아래 `⎿ 본문`으로, 내 메시지는 `> 본문`으로 보인다.
- 상대 이름은 `config.yaml` 같은 파일명 가명으로 바뀐다. 사진은 `[Image #N]`, 이모티콘은 `[Pasted text #N +1 lines]`로 바뀐다(`show_media = false`면 숨김). 사진 판정은 Share 버튼이나 80px 이상 이미지가 있을 때만(말풍선 배경도 AXImage라서).
- 화면 아래 스피너가 계속 돈다(`✻ Mulling… esc to interrupt`). 가짜 작업 로그(Read/Bash/Update)가 가끔 섞인다.
- `Esc`를 누르면 패닉 모드가 된다(카톡 내용 숨김, 가짜 로그만 표시). `Ctrl+B`로 켜고 끈다.
- 다른 방의 안 읽은 메시지 수는 푸터에 `● N background tasks`로 보인다.
- 맥과 윈도우(미검증)를 지원한다. 나중에 다른 테마(노션/워드/주피터)도 할 수 있다.

## 설계 원칙

- **비공식 카톡 프로토콜(LOCO, node-kakao 등)은 쓰지 않는다.** 계정이 정지될 수 있다.
  공식 카카오톡 맥 앱을 **손쉬운 사용(Accessibility) API**로 읽고 조작한다.
- 어댑터 패턴을 쓴다. UI는 `Adapter.rooms() / messages(room_id) / send(room_id, text)`만 안다.

```
kamoflauge/
  __main__.py         CLI: kamoflauge [--mock] | check | shifttest | dump [--out F] [--raw]  (OS 분기 없음, platforms에 위임)
  app.py / app.tcss   Textual UI (Claude Code 스킨). Entry(lines, real, fake) 목록을 유지하고, 패닉 모드에서는 real=True를 숨겨서 다시 그린다
  palette.py          / 명령어 메뉴 (COMMANDS 목록, Palette 위젯)
  models.py           Message(sender, text, time, is_me), Room(id, name), ChatEntry(name, unread). key()에서 time은 의도적으로 뺐다 (아래 참고)
  sync.py             이전/현재 스냅샷 비교 → 새 메시지 추출 (prev 꼬리와 cur 머리의 최장 겹침)
  disguise.py         가명 매핑, 사진/이모티콘 치환, 가짜 작업 로그 생성(fake_event)
  adapters/base.py    인터페이스 (rooms/messages/send 필수, chat_list/open_room/close_room 선택)
  adapters/mock.py    가짜 카톡 (UI 테스트용, 아무 OS에서나 동작)
  platforms/          OS별 코드. 공통 코드에는 sys.platform 분기를 두지 않는다
    __init__.py       current(), load(part), theme(), shift_watcher()
    mac/              adapter.py (pyobjc 손쉬운 사용 API), shift.py, cli.py, theme.py (⏺, ✳ 스피너)
    windows/          adapter.py (ctypes Win32 + 클립보드), shift.py, cli.py, theme.py (●, * 스피너: Windows Terminal은 ⏺/✳을 이모지로 그림)
```

설정 파일은 `~/.kamoflauge/config.toml`이다(처음 실행 시 자동 생성). aliases, cwd, poll, filler, history, strip_emoji, show_time, send_mode가 있다.

## 실제 카톡 맥 앱 접근성 구조 (사용자 맥에서 덤프로 확인함)

카톡 UI는 영어로 설정돼 있다(`Enter a message`, `4:07 PM`).

```
AXWindow/AXStandardWindow  title=방 이름
  AXScrollArea
    AXTable                         ← 메시지 목록. 행 약 53개가 화면 밖 것까지 전부 로드돼 있음(음수 y)
      AXRow/AXTableRow > AXCell >
        [날짜 구분선]  AXButton ''만 있음
        [상대 첫 메시지] AXButton 'Profile', AXStaticText '이름'(x≈197), AXStaticText '4:08 PM' 또는 '2'(안읽음) 또는 '2\n4:13 PM',
                         AXImage(말풍선), AXTextArea '본문'(x≈202)
        [상대 연속 메시지] Profile/이름 없이 AXImage + AXTextArea(x≈202) (+시간)
        [내 메시지]      Profile 없음, 본문이 오른쪽 정렬 (셀 왼쪽 142 기준 본문 x가 228~453, 오른쪽 끝 ≈487)
      AXColumn
    AXScrollBar
  AXButton 'Profile' / AXStaticText 방이름 / AXButton 'Search','Voice Call','Video Call','Menu'
  AXScrollArea
    AXTextArea 'Enter a message'  [settable]   ← 입력창
  AXButton 'Send'                               ← 전송 버튼
  AXButton/AXCloseButton 등
```

여기에 맞춘 `macos.py`의 현재 로직은 다음과 같다.
- `is_chat_window`: 창의 직계 자식 중에 Send 버튼이나 settable한 AXTextArea가 있으면 채팅방이다.
  메인 창(채팅 목록)은 이렇게 제외한다. 처음에는 제목만으로 걸렀는데, 메인 창을 방으로 오인하는 버그가 있었다.
- `find_input`: 직계 AXScrollArea > settable AXTextArea.
- `find_send_button`: 직계 AXButton 중 'Send' 또는 '전송'.
- `_message_table` → `parse_window`: 마지막 50행만 `_cell_items`로 (role, text, x, width)를 뽑고 순수 함수 `parse_rows`로 파싱한다.
  - Profile이 있으면 상대이고, 시간/숫자가 아닌 StaticText를 이름으로 본다. 이름이 없으면 직전 상대를 이어받는다.
  - Profile이 없고 본문 x와 셀 왼쪽의 거리가 `ME_LEFT_MARGIN`(73)보다 크면 내 메시지다.
  - StaticText는 `\n`으로 나눠서 시간(TIME_RE, ` ` 처리), 숫자(안읽음), 날짜를 걸러낸다.
  - 텍스트 없이 이미지만 있으면 "사진"으로 본다.
- `send`: 입력창에 AXValue를 설정하고 **Send 버튼에 AXPress**를 보낸다(포커스를 안 뺏음). 입력창이 안 비워지면
  CGEventPostToPid로 Return을 보내고, 그래도 안 되면 카톡을 잠깐 activate해서 Return을 누른 뒤 원래 앱으로 돌아온다(send_mode=auto).
- `dump_tree`: 채팅방 창 하나만, 노드 3000개 / 자식 40개 제한으로 빠르게 덤프하고 한글을 ㅁ으로 가린다.
  예전 버전은 앱 전체를 훑어서 몇 분씩 걸렸다.

### 왜 Message.key()에서 time을 뺐나
카톡은 같은 분에 같은 사람이 연속으로 보내면 시간 표시를 마지막 메시지로 옮긴다. 그러면 이전 행의 time이 사라진다.
time을 키에 넣으면 sync가 이전 메시지를 '바뀐 것'으로 보고 중복 출력한다.

## 현재 상태

- [x] mock 어댑터로 UI 전체 동작 확인 (헤드리스 Textual 테스트, 스크린샷)
- [x] 사용자 맥에서 카톡 연결과 방 인식 확인. 단, 당시에는 메인 창을 방으로 오인했다 → 수정함
- [x] 실제 덤프 구조를 바탕으로 파서 재작성. 덤프를 본뜬 데이터로 `parse_rows` 단위 테스트 통과
- [x] 이름을 kakaoterm에서 kamoflauge(카모플라지)로 변경. 설정 파일은 `~/.kamoflauge/config.toml` (2026-11-24)
- [x] 수정된 macos.py로 실제 맥에서 `check` 통과 (2026-11-24): 방 인식, 입력창 찾음, 나/상대 구분, 연속 메시지 시간 처리 모두 정상.
  보낸 사람 이름에 공백이 있는 건(예: 'ㅁㅁㅁ ㅁㅁㅁ') 카톡에 저장된 이름 그대로라 정상이다
- [x] 한글 IME 조합 글자가 화면 중간에 뜨던 문제 수정: `_sync_ime_cursor`가 터미널 커서를 입력창에 맞춘다 (실제 터미널에서 재확인 필요)
- [x] 현재 방 표시: 푸터 왼쪽 `⎇ <방>/ (i/n)`, 메시지는 `Read(<방>/<보낸 사람>)`, 입력창 placeholder에도 방 이름
- [x] `Shift+Tab`: auto-claude on(가짜 작업 로그 섞기, 푸터 초록색) ↔ off(채팅만). Shift로 실명을 볼 때는 가짜 로그(Entry.fake)와 스피너를 숨긴다
- [x] Shift를 0.3초 이상 누르고 있으면 `Read(...)` 옆과 푸터에 실명(방 · 보낸 사람)을 노란색으로 표시 (`platforms/*/shift.py`).
  터미널은 Shift 단독 입력을 안 보내므로 Quartz로 modifier 상태를 읽고, 맨 앞 앱이 이 터미널일 때만 반응한다.
  방금 타이핑했으면 무시한다(쌍자음 입력과 구분). 실제 터미널에서 재확인 필요
- [x] 윈도우 어댑터 작성 (`platforms/windows/adapter.py`, ctypes만 사용). 2026-11-24 실제 윈도우 테스트 후 패치 반영:
  채팅방 창 클래스가 `EVA_Window_Dblclk`인 경우도 인정, 전송은 입력칸 클릭+EM_REPLACESEL 후 되읽어 확인, 빈 입력칸이 "메시지 입력"을 돌려줌,
  Shift를 누르는 동안 Ctrl+A/C 복사 건너뜀(카톡 캡처 단축키 Ctrl+Shift+C와 겹침), 클립보드는 GetClipboardSequenceNumber로 확인,
  Windows Terminal은 콘솔 창의 GW_OWNER가 실제 창
  - 채팅방 = 최상위 `#32770`(또는 `EVA_Window_Dblclk`) 창 중 `RICHEDIT50W`(입력창)와 `EVA_VH_ListControl_Dblclk`(메시지 목록)를 가진 것. 클래스 이름은 커뮤니티 자료 기준
  - 읽기: 목록에 Ctrl+A/Ctrl+C를 PostMessage로 보내고(대상 스레드 키보드 상태를 잠깐 바꿔 Ctrl을 흉내냄) 클립보드를 `parse_clipboard`로 파싱. 원래 클립보드 텍스트는 복원
  - 내 메시지 구분: 복사 텍스트에 내 이름이 그대로 나오므로 `my_name` 설정 필요. 비우면 1:1 방(제목=상대 이름)에서 추측
  - 쓰기: WM_SETTEXT + Enter PostMessage, 입력창이 비었는지로 성공 판정
  - 위험: 폴링마다 클립보드에 대화가 복사됨 → Windows 클립보드 기록에 쌓일 수 있음 (README에 안내)
- [x] `tests/`: 윈도우 클립보드 파서, sync 단위 테스트 (`python3 -m pytest -q tests`)
- 참고: 프로젝트 폴더를 kakao-term에서 kamoflauge로 바꿨다 (venv도 새로 만듦). 이제 Claude Code 셸에서도 손쉬운 사용 권한이 OK라 `check`/`dump`를 직접 돌릴 수 있다
- [ ] Send 버튼 AXPress로 실제 전송되는지. 첫 방은 됐지만 방 전환 후 전송이 안 됐다 → 보내기 전에 `_make_main`으로
  대상 창을 카톡 안에서 main으로 올리게 고침 (실제 맥에서 재확인 필요). 어느 방법이 통했는지는 `~/.kamoflauge/send.log`에 남는다
- [ ] 카톡 창을 숨긴 상태(Cmd+H, 다른 Space, 최소화)에서도 읽기/전송이 되는지
- [~] 폴링 성능: 요소마다 AXUIElementCopyMultipleAttributeValues 한 번으로 읽기(`_multi`), 방별 창/테이블 캐시,
  현재 방은 0.7초마다, 방 목록과 다른 방은 4번에 한 번 읽기(`BG_EVERY`)로 바꿈. 실제 맥 측정은 `check`의 '읽기 시간'으로 확인할 것.
  못 읽어서 빈 결과가 오면 스냅샷을 유지한다(안 그러면 다음 폴링 때 메시지가 전부 새 것으로 쏟아진다)

- [x] 전송 실패 원인 (2026-11-24): 카톡이 AX 요청 하나에 5~10ms라 50행 읽기가 2~3초. 0.7초마다 읽으니 카톡이 계속 바빠서
  전송 AX 호출이 밀리고 실패했다. → 처음만 50행(`FULL_ROWS`), 이후엔 15행(`POLL_ROWS`)만 읽고 맨 앞이 연속 메시지면 Profile 행까지 더 읽음,
  읽기 끝난 뒤 poll초 쉬기, 전송 중엔 폴링 중지 + 어댑터 락, 전송 성공은 입력창이 완전히 빌 때만, 실패 사유도 send.log에 남김.
  측정: 폴링 읽기 0.2~1.2초 (실제 전송은 사용자 재확인 필요)

- [x] (2026-11-24) 방을 처음 열 때도 가짜 로그 섞기(`HISTORY_FAKE`), 다른 방 알림(`notify` 스타일, 내용 없이 가명+개수,
  열린 창은 sync로, 안 연 방은 메인 창 채팅 목록 `chat_list()`의 안 읽은 수 증가로), `/` 명령어 팔레트(`palette.py`),
  `/open-chatroom`(목록 행 AXSelected + Return, 안 되면 activate) / `/close-chatroom`(AXCloseButton), `/mute`.
  메인 창 채팅 목록 행: [Profile] 이름 [멤버 수] 시간 [마지막 메시지] [안 읽은 수(300+ 가능)] → `parse_chat_row`.
  **open/close는 실제 맥에서 아직 안 눌러봄**(방을 열면 읽음 처리돼서 사용자 확인 필요)
- [x] (2026-11-24) 윈도우 `/open-chatroom <이름>` / `/close-chatroom`: 메인 창 '카카오톡' > EVA_ChildWindow > 두 번째 EVA_Window > Edit(채팅 탭 검색칸)에
  WM_SETTEXT + Enter, 새 방 창이 뜨면 검색칸 비움. 닫기는 WM_CLOSE. 채팅 목록은 못 읽어서(`chat_list` 미지원) 메뉴에 목록 대신 친 이름을 띄운다.
  안 연 방 알림도 윈도우는 없음(열린 창 방만). **실제 윈도우에서 아직 안 돌려봄**
- [x] (2026-11-24) 방 전환 시 섞임 방지: `Entry.room`(추가될 때 보던 방)으로 다른 방 줄은 숨기고, `_open`은 그 방의 예전 줄을 지운 뒤 최근 대화를 다시 불러온다.
  mock은 친구 단톡방(고딩 친구들/대학 동기들/민수, 안 연 방 동아리)이고 메시지가 항상 자기 방에만 들어간다
- [x] (2026-11-24) `/speed 빠르게|보통|느리게`, 설정 `speed`: 가짜 로그 간격과 방 처음 열 때 섞는 확률(`speed.py`의 SPEEDS)

## 다음 할 일 (순서대로)

1. `kamoflauge check`: 방마다 최근 메시지 5개의 보낸 사람/나 여부가 맞는지, "입력창 찾음"이 나오는지 확인한다.
   틀리면 `kamoflauge dump`로 구조를 다시 보고 `parse_rows` / `ME_LEFT_MARGIN`을 조정한다.
2. `kamoflauge`으로 실제 송수신을 테스트한다. 중복 출력이나 누락이 없는지 본다(sync.py).
3. 숨김 상태에서 동작하는지 확인하고, 안 되면 대안을 찾는다(창을 화면 밖으로 이동하거나 다른 Space로 옮기기 등).
4. 그 외 개선 아이디어:
   - 메인 창의 채팅 목록을 읽어서 안 열린 방도 `/rooms`에 보여주기. 방을 열 때는 행 더블클릭(AXPress) → 새 창
   - 사진/이모티콘을 더 정확히 판별하기. 지금은 텍스트 없는 말풍선을 "사진"으로 친다
   - 시스템 알림 소리/배너 끄기 안내
   - 한글 폭 문제: 터미널 폰트가 D2Coding이나 나눔고딕코딩이어야 자연스럽게 보인다

## 개발/테스트

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -e .
kamoflauge --mock        # 카톡 없이 UI 확인
kamoflauge check         # 맥 카톡 연결 진단
kamoflauge dump          # 채팅방 창 구조 → ax_redacted.txt (한글 가림), --raw면 원문
python3 -m pyflakes kamoflauge
```

- 터미널 앱(Terminal/iTerm/Ghostty)에 **손쉬운 사용 권한**이 필요하다. 권한을 바꾼 뒤에는 터미널을 재시작해야 한다.
- Claude Code에서 `kamoflauge`(TUI)을 직접 띄우면 안 된다. 인터랙티브 화면이라 멈춘다. 대신 `check`/`dump`를 쓰거나,
  Textual의 `App.run_test()`로 헤드리스 테스트를 한다(예: mock 어댑터로 `pilot.press(...)` 후 `app.save_screenshot()`).
- 주의: 채팅방 창이 열려 있으면 카톡이 읽음 처리한다(상대 화면의 1이 사라짐).
- 덤프나 로그에는 실제 대화 내용이 들어 있다. 커밋하지 말 것(.gitignore에 등록돼 있음).
