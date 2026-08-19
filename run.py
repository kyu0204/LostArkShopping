"""어느 경로에서 실행해도 앱이 뜨게 하는 진입점.

  python run.py

`python -m app` 은 현재 디렉터리가 프로젝트 루트여야 하고,
`python app/main.py` 는 상대 임포트라서 바로는 안 돈다. 이 파일이 그 둘을 대신한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
