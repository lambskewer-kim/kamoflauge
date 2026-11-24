"""실명 → 파일명 가명, 사진/이모티콘 치환, 가짜 작업 로그 생성."""
from __future__ import annotations

import hashlib
import random
import re

_FILES = [
    "trainer.py", "dataset.py", "model.py", "config.yaml", "utils.py", "eval.py",
    "loss.py", "metrics.py", "README.md", "train.sh", "requirements.txt",
    "scheduler.py", "augment.py", "inference.py", "logger.py", "setup.cfg",
]

_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF️‍]+"
)


class Disguise:
    def __init__(self, aliases: dict[str, str] | None = None, strip_emoji: bool = True):
        self.aliases: dict[str, str] = dict(aliases or {})
        self.strip_emoji = strip_emoji
        self._image_n = 0
        self._paste_n = 0

    def alias(self, name: str) -> str:
        if not name:
            return "main.py"
        if name in self.aliases:
            return self.aliases[name]
        h = int(hashlib.md5(name.encode()).hexdigest(), 16)
        base = _FILES[h % len(_FILES)]
        cand, n = base, 2
        used = set(self.aliases.values())
        while cand in used:
            stem, dot, ext = base.partition(".")
            cand = f"{stem}_{n}.{ext}" if dot else f"{stem}_{n}"
            n += 1
        self.aliases[name] = cand
        return cand

    def room_dir(self, name: str) -> str:
        a = self.alias(name)
        return a.rsplit(".", 1)[0]

    @staticmethod
    def is_media(text: str) -> bool:
        """사진/이모티콘/동영상처럼 글자 없는 메시지인지."""
        t = text.strip()
        return (t in ("사진", "Photo", "photo", "이모티콘", "Emoticon", "emoticon", "동영상", "Video")
                or (t.startswith("사진 ") and t.endswith("장")))

    def text(self, text: str) -> str:
        t = text.strip()
        if t in ("사진", "Photo", "photo") or t.startswith("사진 ") and t.endswith("장"):
            self._image_n += 1
            return f"[Image #{self._image_n}]"
        if t in ("이모티콘", "Emoticon", "emoticon"):
            self._paste_n += 1
            return f"[Pasted text #{self._paste_n} +1 lines]"
        if t in ("동영상", "Video"):
            return "[Video attachment]"
        if t.startswith("파일") or t.endswith((".pdf", ".zip", ".hwp", ".docx")):
            return f"[Attachment: {t}]"
        if self.strip_emoji:
            t = _EMOJI.sub("", t).strip() or "…"
        return t


# ---------- 가짜 작업 로그 ----------

_SRC = ["src/models/transformer.py", "src/data/loader.py", "src/train.py", "configs/base.yaml",
        "src/utils/metrics.py", "tests/test_loader.py", "src/models/attention.py", "scripts/eval.sh"]
_PROSE = [
    "Let me check how the learning rate scheduler is configured.",
    "The loss plateau seems related to the warmup steps. I'll look at the config.",
    "I'll add a unit test for the collate function before changing it.",
    "Found it — the attention mask is broadcast along the wrong axis.",
    "Running the eval script again to confirm the fix.",
    "Now let me update the data augmentation pipeline.",
]
VERBS = ["Thinking", "Pondering", "Crunching", "Computing", "Synthesizing", "Reticulating",
         "Cogitating", "Brewing", "Percolating", "Contemplating", "Mulling", "Noodling"]


def fake_event(rng: random.Random | None = None) -> list[tuple[str, str]]:
    """(style, line) 리스트를 반환. style은 app 쪽에서 해석."""
    r = rng or random
    kind = r.choice(["read", "read", "bash", "update", "prose", "grep"])
    if kind == "read":
        f = r.choice(_SRC)
        return [("tool", f"Read({f})"), ("result", f"Read {r.randint(40, 420)} lines (ctrl+r to expand)")]
    if kind == "bash":
        cmd, out = r.choice([
            ("python -m pytest tests/ -q", f"{r.randint(30, 90)} passed, {r.randint(0, 3)} warnings in {r.uniform(2, 20):.2f}s"),
            ("nvidia-smi --query-gpu=utilization.gpu --format=csv", f"utilization.gpu [%]\n{r.randint(60, 99)} %"),
            ("tail -n 1 logs/train.log", f"epoch {r.randint(5, 40)}/100 | loss {r.uniform(0.2, 0.9):.4f} | acc {r.uniform(0.7, 0.95):.4f}"),
            ("git status --short", " M src/train.py\n M configs/base.yaml"),
        ])
        return [("tool", f"Bash({cmd})")] + [("result", l) for l in out.split("\n")]
    if kind == "update":
        f = r.choice(_SRC)
        a, d = r.randint(1, 12), r.randint(0, 6)
        return [("tool", f"Update({f})"), ("result", f"Updated {f} with {a} additions and {d} removals")]
    if kind == "grep":
        pat = r.choice(["def forward", "warmup_steps", "TODO", "attn_mask", "num_workers"])
        return [("tool", f'Search(pattern: "{pat}", path: "src")'), ("result", f"Found {r.randint(1, 9)} files")]
    return [("prose", r.choice(_PROSE))]
