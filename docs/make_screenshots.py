"""README용 스크린샷을 만든다. 실제 카톡이 아니라 예시 대화를 넣은 mock 어댑터를 쓴다.

    python docs/make_screenshots.py

docs/screenshot-*.svg 를 만들고, Chrome이 있으면 같은 이름의 .png 도 만든다.
"""
from __future__ import annotations

import asyncio
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

from kamoflauge.adapters.mock import MockAdapter
from kamoflauge.app import Config, Kamoflauge
from kamoflauge.models import Message

OUT = Path(__file__).resolve().parent
SIZE = (104, 40)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

ROOMS = {
    "점심팟": [
        Message("민수", "점심 뭐 먹음?", "11:52 AM"),
        Message("민수", "오늘 퇴근 몇시?", "11:52 AM"),
        Message("", "ㄱㄱ 학식 가자", "11:53 AM", True),
        Message("지은", "나도 낄래", "11:54 AM"),
        Message("지은", "사진", "11:54 AM"),
    ],
    "엄마": [Message("엄마", "밥은 먹었어?", "10:10 AM")],
    "스터디": [Message("현우", "오늘 발표 자료 올렸어요", "9:41 AM")],
}
ALIASES = {"점심팟": "scheduler.py", "민수": "config.yaml", "지은": "trainer.py"}


def make_app() -> tuple[Kamoflauge, MockAdapter]:
    ad = MockAdapter(chatter=1e9)
    ad._next = time.time() + 1e9  # 랜덤 메시지 끄기
    ad._rooms = {k: list(v) for k, v in ROOMS.items()}
    cfg = Config(aliases=dict(ALIASES), filler_every=(1e9, 1e9))
    app = Kamoflauge(ad, cfg)
    app._shift.shift_down = lambda: False
    return app, ad


def freeze_spinner(app: Kamoflauge, verb: str = "Mulling") -> None:
    app.verb, app.spin_start, app.tokens = verb, time.time() - 9, 2.9


def fake(lines: list[tuple[str, str]], app: Kamoflauge) -> None:
    app._add(lines, real=False, fake=True)
    app.last_sender = None


async def shoot() -> list[Path]:
    random.seed(7)
    app, ad = make_app()
    files = []
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause(0.6)
        fake([("tool", "Bash(python -m pytest tests/ -q)"), ("result", "57 passed, 1 warnings in 8.42s")], app)
        # 다른 방에 안 읽은 메시지 → "● 2 background tasks"
        app.unread.update({"엄마": 1, "스터디": 1})
        app._update_footer()

        freeze_spinner(app)
        await pilot.pause(0.15)
        files.append(save(app, "screenshot-main"))

        # Shift 꾹 누르기: 실명 보기
        app._shift.shift_down = lambda: True
        app._last_typed = 0.0
        await pilot.pause(0.8)
        files.append(save(app, "screenshot-reveal"))
        app._shift.shift_down = lambda: False
        await pilot.pause(0.4)

        # Esc: 패닉 모드
        await pilot.press("escape")
        rng = random.Random(3)
        from kamoflauge.disguise import fake_event
        for _ in range(4):
            fake(fake_event(rng), app)
        freeze_spinner(app, "Reticulating")
        await pilot.pause(0.3)
        files.append(save(app, "screenshot-panic"))
    return files


def save(app: Kamoflauge, name: str) -> Path:
    app.save_screenshot(f"{name}.svg", path=str(OUT))
    return OUT / f"{name}.svg"


def to_png(svg: Path) -> Path | None:
    chrome = CHROME if Path(CHROME).exists() else shutil.which("chromium") or shutil.which("google-chrome")
    if not chrome:
        return None
    text = svg.read_text(encoding="utf-8")
    vb = text.split('viewBox="', 1)[1].split('"', 1)[0].split()
    w, h = int(float(vb[2])), int(float(vb[3]))
    html = svg.with_suffix(".html")
    html.write_text(
        f'<html><body style="margin:0;background:transparent">'
        f'<img src="{svg.name}" width="{w}" height="{h}" style="display:block"></body></html>',
        encoding="utf-8",
    )
    png = svg.with_suffix(".png")
    try:
        subprocess.run([chrome, "--headless", "--disable-gpu", "--hide-scrollbars",
                        "--default-background-color=00000000", "--force-device-scale-factor=2",
                        f"--window-size={w},{h}", f"--screenshot={png}", html.as_uri()],
                       check=True, capture_output=True, timeout=60)
    finally:
        html.unlink(missing_ok=True)
    return png


def main() -> None:
    files = asyncio.run(shoot())
    for svg in files:
        png = to_png(svg)
        print(svg.name, "→", png.name if png else "(Chrome 없음, svg만)")
    if not any(f.with_suffix(".png").exists() for f in files):
        sys.exit(0)


if __name__ == "__main__":
    main()
