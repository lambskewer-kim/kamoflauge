from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

CONFIG_PATH = Path(os.path.expanduser("~/.kamoflauge/config.toml"))

DEFAULT_CONFIG = """\
# kamoflauge 설정
cwd = "~/research/vision-transformer"   # 환영 박스에 보일 경로
poll = 0.7                              # 현재 방 확인 주기(초)
filler = true                           # 평소에도 가짜 작업 로그를 가끔 섞기
history = 15                            # 방 열 때 보여줄 이전 메시지 수
strip_emoji = true
show_time = false
send_mode = "auto"                      # (맥) auto | background | activate
my_name = ""                            # (윈도우) 카톡에 보이는 내 이름. 비우면 1:1 방에서 자동 추측

# 실명 → 화면에 보일 파일명. 없으면 자동 배정.
[aliases]
# "엄마" = "config.yaml"
# "랩실 단톡" = "trainer.py"
"""


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(DEFAULT_CONFIG, encoding="utf-8")
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def cmd_run(args) -> None:
    from .adapters import get_adapter
    from .app import Config, Kamoflauge

    raw = load_config()
    cfg = Config(
        aliases=raw.get("aliases", {}),
        cwd=raw.get("cwd", Config.cwd),
        poll=float(raw.get("poll", Config.poll)),
        filler=bool(raw.get("filler", True)),
        history=int(raw.get("history", Config.history)),
        strip_emoji=bool(raw.get("strip_emoji", True)),
        show_time=bool(raw.get("show_time", False)),
    )
    name = "mock" if args.mock else "auto"
    try:
        adapter = get_adapter(name, **({} if args.mock else _adapter_opts(raw)))
    except Exception as ex:  # noqa: BLE001
        print(f"error: {ex}", file=sys.stderr)
        sys.exit(1)
    Kamoflauge(adapter, cfg).run()


def _ms(t0: float) -> str:
    return f"{(time.perf_counter() - t0) * 1000:.0f}ms"


def _adapter_opts(raw: dict) -> dict:
    if sys.platform == "darwin":
        return {"send_mode": raw.get("send_mode", "auto")}
    if sys.platform == "win32":
        return {"my_name": raw.get("my_name", "")}
    return {}


def _open_adapter():
    """플랫폼별 연결 상태를 출력하고 어댑터를 돌려준다."""
    if sys.platform == "darwin":
        from .adapters.macos import MacKakaoAdapter, is_trusted
        print(f"손쉬운 사용 권한: {'OK' if is_trusted(prompt=True) else '없음 → 시스템 설정에서 터미널 앱 허용'}")
        ad = MacKakaoAdapter()
        app = ad._app()
        print(f"카카오톡 실행 중: pid={app.processIdentifier()} hidden={bool(app.isHidden())}")
        return ad
    from .adapters.windows import WinKakaoAdapter
    ad = WinKakaoAdapter(**_adapter_opts(load_config()))
    print("윈도우 카카오톡 어댑터 (클립보드 복사 방식)")
    return ad


def cmd_check(args) -> None:
    try:
        ad = _open_adapter()
    except (PermissionError, RuntimeError) as ex:
        print(f"error: {ex}", file=sys.stderr)
        sys.exit(1)
    t0 = time.perf_counter()
    rooms = ad.rooms()
    print(f"열린 채팅방 창: {len(rooms)}개  (방 목록 읽기 {_ms(t0)})")
    for r in rooms:
        t0 = time.perf_counter()
        msgs = ad.messages(r.id)
        first = _ms(t0)
        t0 = time.perf_counter()
        ad.messages(r.id)
        again = _ms(t0)
        print(f"\n[{r.name}]  메시지 {len(msgs)}개 파싱됨, 입력창 {'찾음' if ad.has_input(r.id) else '못 찾음'}")
        print(f"   읽기 시간: 처음 {first}, 다시 읽기 {again}  (폴링마다 '다시 읽기'만큼 걸림)")
        for m in msgs[-5:]:
            who = "나" if m.is_me else (m.sender or "?")
            print(f"   {who:>8} | {m.text[:40]!r}  {m.time}")
    if sys.platform == "win32":
        name = getattr(ad, "my_name", "")
        print(f"\n내 이름: {name!r}" + ("" if name else "  → 못 찾음. config.toml 의 my_name 에 카톡에 보이는 내 이름을 적으세요"))
    if not rooms:
        print("→ 카톡에서 채팅방을 더블클릭해 창으로 열어두고 다시 실행하세요.")


def cmd_dump(args) -> None:
    if sys.platform == "win32":
        from .adapters.windows import dump_tree
    else:
        from .adapters.macos import dump_tree

    n = dump_tree(args.out, redact=not args.raw)
    note = "원문 그대로" if args.raw else "한글은 ㅁ으로 가림"
    print(f"{n}개 요소를 {args.out} 에 저장했습니다. ({note})")


def main() -> None:
    p = argparse.ArgumentParser(prog="kamoflauge")
    p.add_argument("--mock", action="store_true", help="가짜 카톡으로 UI만 테스트")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("check", help="카톡 연결 상태 진단")
    d = sub.add_parser("dump", help="카톡 창 구조를 파일로 저장")
    d.add_argument("--out", default="ax_redacted.txt")
    d.add_argument("--raw", action="store_true", help="한글을 가리지 않음")
    args = p.parse_args()

    if args.cmd in ("check", "dump") and sys.platform not in ("darwin", "win32"):
        print("check/dump 는 macOS 와 Windows 에서만 동작합니다.", file=sys.stderr)
        sys.exit(1)
    {"check": cmd_check, "dump": cmd_dump}.get(args.cmd, cmd_run)(args)


if __name__ == "__main__":
    main()
