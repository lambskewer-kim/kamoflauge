# kamoflauge

**카모플라지 = 카톡 + 위장(camouflage).** 
카카오톡을 **Claude Code처럼 보이는 터미널 화면**에서 읽고 보내는 프로그램이에요.
옆에서 보면 AI 코딩 에이전트가 열심히 일하는 화면으로 보여요.

![kamoflauge 화면: 카톡 대화가 Claude Code 작업 로그처럼 보여요](docs/screenshot-main.png)

<sub>스크린샷은 예시 대화예요. `점심팟` 방은 `scheduler/`, 민수는 `config.yaml`, 지은은 `trainer.py`로 보여요.</sub>

| 플랫폼 | 상태 |
|---|---|
| macOS | 동작 확인함 (카톡 맥 앱, 영어 UI) |
| Windows | 코드만 작성함. **실제 윈도우에서 아직 테스트 안 됨** |

---

## 주요 기능

### 위장
- **방과 사람을 파일명으로 바꿔 보여줘요.** 채팅방은 `scheduler/` 같은 폴더, 보낸 사람은 `config.yaml` 같은 파일이 돼요.
  상대 메시지는 `⏺ Read(scheduler/config.yaml)`, 내 메시지는 프롬프트 입력처럼 `> 내용`으로 보여요.
- **사진과 이모티콘을 바꿔 보여줘요.** 사진은 `[Image #1]`, 이모티콘은 `[Pasted text #1 +1 lines]`가 돼요.
- **스피너가 계속 돌아요.** `✻ Mulling… (12s · ↑ 3.1k tokens)`처럼 Claude가 작업 중인 것 같은 화면이에요.
- **auto-claude 모드:** `Shift+Tab`으로 켜고 꺼요.
  - **on** (푸터 초록색 `⏵⏵ auto-claude on`): 가짜 작업 로그(`Read`, `Bash(pytest …)`, `Update(…)`, Claude 말투 문장)가 가끔 섞여요.
  - **off** (회색 `⏸ auto-claude off`): 가짜 로그 없이 채팅만 보여요.
- **안 읽은 메시지**: 다른 방에 온 메시지 수가 푸터에 `● N background tasks`로 보여요.

### 긴급 기능
- **패닉 모드 (`Esc`)**: 누르는 즉시 카톡 내용이 전부 사라지고 가짜 작업 로그만 빠르게 올라가요.
  이 상태에서 입력한 건 카톡으로 가지 않고 가짜 응답만 나와요. `Ctrl+B`로 원래 화면으로 돌아와요.
- **실명 보기 (Shift 꾹 누르기)**: Shift를 0.3초 이상 누르고 있는 동안에만 각 메시지 옆과 푸터에
  실제 방 이름과 보낸 사람이 노란색으로 보여요. 이때는 가짜 로그와 스피너가 숨겨져서 채팅만 보여요. 손을 떼면 바로 원래대로 돌아와요.
  - 한글 쌍자음(ㅆ, ㅃ…)을 칠 때처럼 Shift를 짧게 누르거나 방금 타이핑했으면 반응하지 않아요.
  - kamoflauge를 띄운 터미널이 맨 앞에 있을 때만 동작해요.

| Shift 꾹 누르기: 실명 보기 | Esc: 패닉 모드 |
|---|---|
| ![Shift를 누르고 있는 동안 실제 방 이름과 보낸 사람이 노란색으로 보여요](docs/screenshot-reveal.png) | ![패닉 모드에서는 카톡 내용이 사라지고 가짜 작업 로그만 보여요](docs/screenshot-panic.png) |

### 채팅
- 현재 방에 바로 입력해서 보내요. 카톡 창을 앞으로 꺼내지 않아요(맥에서 실패하면 잠깐 꺼냈다가 돌아와요).
- 열려 있는 채팅방 창이 곧 방 목록이에요. `Ctrl+N` / `Ctrl+P`로 방을 바꿔요.
- 새 메시지는 현재 방 기준 약 0.7초마다 확인해요.

### 단축키와 명령어

| 입력 | 동작 |
|---|---|
| 입력 + `Enter` | 현재 방에 메시지 전송 |
| `Ctrl+N` / `Ctrl+P` | 다음 / 이전 방 |
| `Shift+Tab` | auto-claude on / off |
| **Shift 꾹 누르기** | **누르는 동안 실명 보기** |
| **`Esc`** | **패닉 모드** |
| `Ctrl+B` | 패닉 모드 켜기 / 끄기 |
| `Ctrl+C` 두 번 | 종료 |
| `/rooms` | 방 목록 (파일 목록처럼 보임) |
| `/open 2`, `/open config` | 방 이동 (번호 또는 가명 일부) |
| `/alias 엄마 config.yaml` | 가명 직접 지정 |
| `/who` | 지금 방의 실제 이름 확인 |
| `/clear`, `/help` | 화면 지우기, 도움말 |

---

## 세팅 방법 (macOS)

### 1. 설치

Python 3.9 이상이 필요해요.

```bash
git clone <이 저장소> kamoflauge   # 또는 폴더를 그대로 복사
cd kamoflauge
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. 손쉬운 사용 권한 주기

kamoflauge는 공식 카톡 맥 앱을 **손쉬운 사용(Accessibility) API**로 읽고 조작해요.

1. **시스템 설정 → 개인정보 보호 및 보안 → 손쉬운 사용**을 열어요.
2. 쓰는 터미널 앱(터미널, iTerm2, Ghostty 등)을 켜요.
3. 터미널을 **완전히 종료했다가 다시 실행**해요. 권한은 재시작해야 적용돼요.

### 3. 카톡 채팅방을 창으로 열기

카톡에서 대화할 채팅방을 **더블클릭해서 별도 창으로 열어두세요.** 열려 있는 채팅방 창이 kamoflauge의 방 목록이 돼요.
여러 방을 열어두면 `Ctrl+N` / `Ctrl+P`로 오갈 수 있어요.

### 4. 연결 확인

```bash
kamoflauge check
```

방마다 최근 메시지 5개의 보낸 사람과 내 메시지 구분이 맞고 `입력창 찾음`이 나오면 성공이에요.
`읽기 시간`도 같이 나와요. '다시 읽기'가 수백 ms 이하면 충분히 빨라요.

### 5. 실행

```bash
kamoflauge
```

다음부터는 `cd kamoflauge && source .venv/bin/activate && kamoflauge`만 하면 돼요.

---

## 세팅 방법 (Windows) ⚠️ 미검증

### 1. 설치

[python.org](https://www.python.org/)에서 Python 3.9 이상을 설치해요. 설치할 때 "Add python.exe to PATH"를 체크하세요.

```powershell
cd kamoflauge
py -m venv .venv
.venv\Scripts\activate
pip install -e .
```

추가 패키지 없이 파이썬 기본 기능(ctypes)만 써요.

### 2. 터미널 준비

**Windows Terminal** 사용을 추천해요.

### 3. 클립보드 기록 끄기 (중요)

윈도우 카톡은 메시지 글자를 직접 읽을 수 없어서, **채팅방 메시지 목록에 Ctrl+A, Ctrl+C를 보내 클립보드로 복사한 뒤** 읽어요.

- **설정 → 시스템 → 클립보드**에서 **클립보드 기록**과 **기기 간 동기화**를 꺼두세요.
  켜져 있으면 대화 내용이 Win+V 기록에 계속 쌓여요.
- 읽은 뒤에는 원래 클립보드 텍스트를 되돌려 놓아요. 클립보드에 있던 이미지나 파일은 복원되지 않아요.

### 4. 카톡 채팅방을 창으로 열기

카톡 PC에서 대화할 채팅방을 **더블클릭해서 별도 창으로 열어두세요.** 최소화한 상태에서도 되는지는 아직 확인 전이에요.

### 5. 연결 확인과 내 이름 설정

```powershell
kamoflauge check
```

윈도우에서는 복사된 대화에 내 메시지도 내 이름으로 나와요. 그래서 **내 이름을 알아야 내 메시지를 구분**할 수 있어요.

- 1:1 방이 열려 있으면 자동으로 추측해요.
- `내 이름: ''  → 못 찾음`이 나오면 `%USERPROFILE%\.kamoflauge\config.toml`을 열고 `my_name`에 카톡에 보이는 내 이름을 적으세요.

### 6. 실행

```powershell
kamoflauge
```

---

## 설정

설정 파일은 처음 실행할 때 자동으로 만들어져요.
- macOS: `~/.kamoflauge/config.toml`
- Windows: `%USERPROFILE%\.kamoflauge\config.toml`

```toml
cwd = "~/research/vision-transformer"   # 환영 박스에 보일 가짜 작업 경로
poll = 0.7                              # 현재 방 확인 주기(초)
filler = true                           # 시작할 때 auto-claude on/off
history = 15                            # 방을 열 때 보여줄 이전 메시지 수
strip_emoji = true                      # 이모지 지우기
show_time = false                       # 메시지 시간 표시
send_mode = "auto"                      # (맥) auto | background | activate
my_name = ""                            # (윈도우) 카톡에 보이는 내 이름

# 실명 → 화면에 보일 이름. 적지 않은 방/사람은 자동으로 배정돼요.
[aliases]
"엄마" = "config.yaml"
"랩실 단톡" = "trainer.py"
```

`send_mode` (맥)
- `background`: 카톡을 앞으로 꺼내지 않고 보내요. 화면 깜빡임은 없지만 실패할 수 있어요.
- `activate`: 카톡을 0.2초 정도 앞으로 꺼내서 보내고 바로 터미널로 돌아와요. 확실하지만 깜빡여요.
- `auto` (기본값): background를 먼저 해보고 실패하면 activate로 보내요.

---

## 안 될 때

| 증상 | 해결 |
|---|---|
| `손쉬운 사용 권한이 없습니다` (맥) | 권한을 켠 뒤 터미널을 **완전히 껐다가** 다시 실행하세요. |
| `열린 채팅방 창: 0개` | 카톡에서 채팅방을 더블클릭해 별도 창으로 여세요. |
| 한글이 입력창이 아닌 엉뚱한 곳에 써짐 | 최신 버전으로 업데이트하세요. 그래도 그러면 쓰는 터미널 이름을 알려주세요. |
| 전송이 안 됨 | 화면에 `Error: …` 줄이 떴는지 보세요. 맥은 `~/.kamoflauge/send.log`에 어떤 전송 방법이 통했는지 남아요. |
| 내 메시지가 상대 메시지로 보임 (윈도우) | `config.toml`의 `my_name`을 확인하세요. |
| 메시지가 이상하게 읽힘 | 아래 `dump`로 창 구조를 확인하세요. |

카톡 UI 구조는 버전마다 달라질 수 있어요. 메시지가 이상하게 읽히면 창 구조를 파일로 뽑아 보세요.

```bash
kamoflauge dump          # 한글은 ㅁ으로 가려서 ax_redacted.txt 에 저장
kamoflauge dump --raw    # 원문 그대로
```

- 맥: 채팅방 창의 접근성 트리가 저장돼요. `kamoflauge/adapters/macos.py`의 `parse_rows()`와 `ME_LEFT_MARGIN`을 맞추면 돼요.
- 윈도우: 카톡 창과 자식 컨트롤의 클래스 이름이 저장돼요. `kamoflauge/adapters/windows.py` 위쪽의 `ROOM_CLASS`, `INPUT_CLASS`, `LIST_CLASS`를 맞추면 돼요.

---

## 주의

- **채팅방 창이 열려 있으면 카톡은 그 방을 읽음으로 처리해요.** 상대 화면에서 1이 사라져요.
- 비공식 카톡 프로토콜(LOCO 등)을 쓰지 않고 공식 카톡 앱을 조작만 해요. 계정 정지 위험은 낮지만 카톡 업데이트 후 깨질 수 있어요.
- `dump` 결과와 로그에는 실제 대화가 들어 있을 수 있어요. 남에게 공유하거나 커밋하지 마세요(`.gitignore`에 등록돼 있어요).
- 알림 배너가 뜨면 위장이 들통나요. 카톡 알림이나 맥/윈도우 알림 설정에서 카톡 배너와 소리를 꺼두는 걸 추천해요.

---

## 개발

```bash
kamoflauge --mock               # 카톡 없이 가짜 대화로 화면 구경
python3 -m pytest -q tests      # 단위 테스트
python3 -m pyflakes kamoflauge  # 린트
python3 docs/make_screenshots.py  # README 스크린샷 다시 만들기 (예시 대화, Chrome 필요)
```

```
kamoflauge/
  __main__.py          CLI: kamoflauge [--mock] | check | dump
  app.py / app.tcss    Textual UI (Claude Code 스킨)
  adapters/base.py     어댑터 인터페이스: rooms() / messages() / send()
  adapters/macos.py    맥 카톡 (Accessibility API + CGEvent, pyobjc)
  adapters/windows.py  윈도우 카톡 (Win32 메시지 + 클립보드, ctypes)
  adapters/mock.py     테스트용 가짜 카톡
  sync.py              이전/현재 화면 비교 → 새 메시지만 추출
  disguise.py          가명, 사진/이모티콘 치환, 가짜 작업 로그
  shift.py             Shift 꾹 누르기 감지 (맥: Quartz, 윈도우: GetAsyncKeyState)
  models.py            Message, Room
tests/                 윈도우 클립보드 파서, sync 테스트
docs/                  README 스크린샷과 생성 스크립트
```

새 플랫폼은 `adapters/base.py`의 `Adapter`를 구현해서 `adapters/__init__.py`의 `get_adapter`에 등록하면 돼요.
