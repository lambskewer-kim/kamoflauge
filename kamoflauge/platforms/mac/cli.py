"""맥 전용 CLI 부분: 어댑터 만들기, check 머리말, dump."""
from __future__ import annotations

from .adapter import MacKakaoAdapter, dump_tree, is_trusted

__all__ = ["adapter_opts", "make_adapter", "check_header", "dump_tree"]


def adapter_opts(raw: dict) -> dict:
    return {"send_mode": raw.get("send_mode", "auto")}


def make_adapter(raw: dict) -> MacKakaoAdapter:
    return MacKakaoAdapter(**adapter_opts(raw))


def check_header(raw: dict) -> MacKakaoAdapter:
    """연결 상태를 출력하고 어댑터를 돌려준다 (kamoflauge check)."""
    print(f"손쉬운 사용 권한: {'OK' if is_trusted(prompt=True) else '없음 → 시스템 설정에서 터미널 앱 허용'}")
    ad = make_adapter(raw)
    app = ad._app()
    print(f"카카오톡 실행 중: pid={app.processIdentifier()} hidden={bool(app.isHidden())}")
    return ad


def check_footer(ad: MacKakaoAdapter) -> None:
    pass
