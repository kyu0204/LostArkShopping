"""진입점.

  python -m app

키가 없으면 창을 띄우기 전에 입력 다이얼로그를 먼저 보여준다.
저장은 .env 평문 — keyring 전환은 나중에 _save_key 자리만 갈아끼우면 된다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QInputDialog, QLineEdit, QMessageBox  # noqa: E402

from loa.client import LostArkAPIError, LostArkClient  # noqa: E402
from scripts._env import ENV_PATH, KEY_NAME, _validate, _write_env  # noqa: E402

from .window import MainWindow, load_options  # noqa: E402


def _stored_key() -> str:
    from dotenv import load_dotenv

    load_dotenv(ENV_PATH)
    return os.environ.get(KEY_NAME, "").strip()


def ask_for_key(parent=None) -> str | None:
    """키를 받아 검증하고 .env 에 저장. 취소하면 None."""
    while True:
        key, ok = QInputDialog.getText(
            parent,
            "API 키 입력",
            "로스트아크 개발자 API 키(JWT)를 붙여넣어라.\n"
            "발급: developer-lostark.game.onstove.com\n\n"
            "저장 위치: .env (커밋되지 않음)",
            QLineEdit.Password,
        )
        if not ok:
            return None
        key = key.strip()
        if key.lower().startswith("bearer "):
            key = key[7:].strip()  # 헤더째 붙여넣는 실수 흡수
        if not key:
            continue

        valid, msg = _validate(key)
        if valid:
            _write_env(key)
            os.environ[KEY_NAME] = key
            return key
        QMessageBox.warning(parent, "키 검증 실패", msg)


def main() -> int:
    qt = QApplication(sys.argv)
    qt.setApplicationName("로스트아크 경매장 매물 비교기")

    key = _stored_key() or ask_for_key()
    if not key:
        return 1

    client = LostArkClient(api_key=key)
    try:
        options_payload = load_options(client)
    except LostArkAPIError as exc:
        QMessageBox.critical(None, "옵션 목록을 못 받았다", f"HTTP {exc.status}\n{exc.body[:300]}")
        return 1

    window = MainWindow(client, options_payload)
    window.show()
    return qt.exec()


if __name__ == "__main__":
    raise SystemExit(main())
