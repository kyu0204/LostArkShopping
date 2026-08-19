"""API 키 입력/교체.

  python scripts/setup_key.py            # 키 없을 때만 물어봄
  python scripts/setup_key.py --replace  # 기존 키 있어도 새로 입력
  python scripts/setup_key.py --check    # 저장된 키 검증만
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts._env import ENV_PATH, KEY_NAME, _validate, ensure_api_key, prompt_and_save  # noqa: E402


def _masked(key: str) -> str:
    return f"{key[:8]}…{key[-6:]} (len={len(key)})" if len(key) > 20 else "(짧음)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replace", action="store_true", help="기존 키 무시하고 새로 입력")
    ap.add_argument("--check", action="store_true", help="저장된 키 검증만 하고 종료")
    ap.add_argument("--no-validate", action="store_true", help="API 호출 없이 저장")
    args = ap.parse_args()

    if args.check:
        key = ensure_api_key(interactive=False)
        if not key:
            print(f"{KEY_NAME} 없음 ({ENV_PATH})")
            return 1
        print(f"저장된 키: {_masked(key)}")
        ok, msg = _validate(key)
        print(msg)
        return 0 if ok else 1

    if args.replace:
        key = prompt_and_save(validate=not args.no_validate)
    else:
        key = ensure_api_key(interactive=True)
        if key:
            print(f"키 확보됨: {_masked(key)}")

    return 0 if key else 1


if __name__ == "__main__":
    raise SystemExit(main())
