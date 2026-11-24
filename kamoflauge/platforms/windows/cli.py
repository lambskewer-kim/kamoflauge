"""윈도우 전용 CLI 부분: 어댑터 만들기, check 머리말/꼬리말, dump."""
from __future__ import annotations

from .adapter import WinKakaoAdapter, dump_tree

__all__ = ["adapter_opts", "make_adapter", "check_header", "check_footer", "dump_tree"]


def adapter_opts(raw: dict) -> dict:
    return {"my_name": raw.get("my_name", "")}


def make_adapter(raw: dict) -> WinKakaoAdapter:
    return WinKakaoAdapter(**adapter_opts(raw))


def check_header(raw: dict) -> WinKakaoAdapter:
    print("윈도우 카카오톡 어댑터 (클립보드 복사 방식)")
    return make_adapter(raw)


def check_footer(ad: WinKakaoAdapter) -> None:
    name = ad.my_name
    print(f"\n내 이름: {name!r}" + ("" if name else "  → 못 찾음. config.toml 의 my_name 에 카톡에 보이는 내 이름을 적으세요"))
