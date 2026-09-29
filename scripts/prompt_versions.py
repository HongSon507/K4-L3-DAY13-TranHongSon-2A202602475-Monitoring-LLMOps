"""Quản lý prompt `day13-chat` trên Langfuse: tạo v1/v2, xem label, promote và rollback.

Ví dụ:
    python scripts/prompt_versions.py status
    python scripts/prompt_versions.py create
    python scripts/prompt_versions.py promote --version 2   # production -> v2
    python scripts/prompt_versions.py promote --version 1   # rollback production -> v1
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio

PROMPT_V1 = "Feature={{feature}}\nDocs={{docs}}\nQuestion={{message}}"
# v2: thay đổi nhỏ về format/độ dài câu trả lời, giữ nguyên ba biến bắt buộc.
PROMPT_V2 = (
    "Feature={{feature}}\nDocs={{docs}}\nQuestion={{message}}\n"
    "Answer in at most 3 short bullet points, using only the docs above."
)
LABELS_TO_SHOW = ("production", "baseline", "candidate", "latest")


def _client():
    load_dotenv(REPO_ROOT / ".env")
    if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
        raise SystemExit("Thiếu LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY trong .env")
    from langfuse import get_client

    return get_client()


def _prompt_name() -> str:
    return os.getenv("LANGFUSE_PROMPT_NAME", "day13-chat")


def show_status(client, name: str) -> dict[str, int]:
    found: dict[str, int] = {}
    for label in LABELS_TO_SHOW:
        try:
            prompt = client.get_prompt(name, label=label, type="text", cache_ttl_seconds=0)
        except Exception as exc:  # label chưa tồn tại hoặc prompt chưa được tạo
            print(f"  {label:<11} -> (không có: {type(exc).__name__})")
            continue
        found[label] = prompt.version
        print(f"  {label:<11} -> version {prompt.version} | labels={prompt.labels}")
    return found


def create_versions(client, name: str) -> None:
    existing = show_status(client, name)
    if existing:
        raise SystemExit(
            f"Prompt '{name}' đã tồn tại; không tạo thêm version để tránh lệch v1/v2. "
            "Dùng 'status' hoặc 'promote'."
        )
    v1 = client.create_prompt(
        name=name,
        prompt=PROMPT_V1,
        type="text",
        labels=["baseline", "production"],
        commit_message="v1 baseline",
    )
    v2 = client.create_prompt(
        name=name,
        prompt=PROMPT_V2,
        type="text",
        labels=["candidate"],
        commit_message="v2 candidate: concise bullet answers",
    )
    print(f"Đã tạo {name} v{v1.version} (baseline, production) và v{v2.version} (candidate)")


def promote(client, name: str, version: int) -> None:
    print("Trước:")
    show_status(client, name)
    client.update_prompt(name=name, version=version, new_labels=["production"])
    print(f"Đã gắn label production cho version {version}. Sau:")
    show_status(client, name)


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Xem version đang gắn với từng label")
    sub.add_parser("create", help="Tạo v1 (baseline, production) và v2 (candidate)")
    promote_parser = sub.add_parser("promote", help="Chuyển label production sang một version")
    promote_parser.add_argument("--version", type=int, required=True)
    args = parser.parse_args()

    client = _client()
    name = _prompt_name()
    if args.command == "status":
        print(f"Prompt '{name}':")
        show_status(client, name)
    elif args.command == "create":
        create_versions(client, name)
    else:
        promote(client, name, args.version)
    client.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
