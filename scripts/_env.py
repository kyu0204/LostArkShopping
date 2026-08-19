"""스크립트 공용 — API 키 확보 (.env 읽기 / 없으면 대화식 입력).

keyring 도입은 세션 5로 보류. 지금은 .env 평문.
loa/ 하위에는 넣지 않는다 — 순수 레이어는 I/O 프롬프트를 갖지 않는다.
"""

from __future__ import annotations

import os
import sys
from getpass import getpass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
KEY_NAME = "LOSTARK_API_KEY"


def _write_env(key: str, path: Path = ENV_PATH) -> None:
    """.env 의 KEY_NAME 줄만 교체/추가. 다른 줄은 보존."""
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()

    replaced = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{KEY_NAME}="):
            lines[i] = f"{KEY_NAME}={key}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{KEY_NAME}={key}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)  # Windows에선 사실상 무의미하나 해는 없다
    except OSError:
        pass


def _validate(key: str) -> tuple[bool, str]:
    """실제 요청 1회로 키 검증. (성공여부, 메시지)"""
    from loa.client import LostArkAPIError, LostArkClient

    try:
        client = LostArkClient(api_key=key)
        client.get_auction_options()
        return True, "검증 통과"
    except LostArkAPIError as exc:
        if exc.status == 401:
            return False, "401 — 키가 잘못됐다"
        if exc.status == 403:
            return False, "403 — 키는 유효하나 권한 없음"
        if exc.status == 429:
            return True, "429 — 한도 초과라 검증은 못 했지만 키 자체는 인식됨"
        return False, f"{exc.status} — {exc.body[:200]}"
    except Exception as exc:  # 네트워크 등
        return False, f"요청 실패: {exc}"


def prompt_and_save(validate: bool = True) -> str | None:
    """대화식으로 키를 받아 .env 에 저장. 성공 시 키 반환."""
    if not sys.stdin.isatty():
        print(
            f"[!] {KEY_NAME} 없음. 터미널에서 직접 실행해라:\n"
            f"    .venv/Scripts/python.exe scripts/setup_key.py",
            file=sys.stderr,
        )
        return None

    print("로스트아크 개발자 API 키(JWT)를 입력해라. 화면에 표시되지 않는다.")
    print("발급: https://developer-lostark.game.onstove.com/ → 로그인 → API Key 신청\n")

    for attempt in range(3):
        key = getpass("API Key: ").strip()
        if not key:
            print("빈 값. 다시.")
            continue
        if key.lower().startswith("bearer "):
            key = key[7:].strip()  # 헤더째 붙여넣는 실수 흡수

        if validate:
            print("검증 중…")
            ok, msg = _validate(key)
            print(f"  {msg}")
            if not ok:
                print(f"  남은 시도 {2 - attempt}회\n" if attempt < 2 else "")
                continue

        _write_env(key)
        os.environ[KEY_NAME] = key
        print(f"\n저장 완료: {ENV_PATH}")
        print("이 파일은 .gitignore 에 있다. 커밋되지 않는다.")
        return key

    print("3회 실패. 중단.", file=sys.stderr)
    return None


def ensure_api_key(interactive: bool = True) -> str | None:
    """.env / 환경변수에서 키를 읽고, 없으면 (가능하면) 입력받는다."""
    from dotenv import load_dotenv

    load_dotenv(ENV_PATH)
    key = os.environ.get(KEY_NAME, "").strip()
    if key:
        return key
    if not interactive:
        return None
    return prompt_and_save()
