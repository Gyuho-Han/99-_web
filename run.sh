#!/usr/bin/env bash
# 백엔드(8000)와 프론트엔드(5173)를 함께 띄운다.
#
# 필요: Python 3.10 이상, Node 18 이상
#
# 파이썬을 직접 지정하려면:  PYTHON=/path/to/python ./run.sh
set -e
cd "$(dirname "$0")"

MIN_PY="3.10"

# ---------------------------------------------------------------------------
# 파이썬 고르기
#
# 맥에는 시스템 파이썬 · Command Line Tools · conda · pyenv 가 섞여 있는 일이
# 흔하고, 셸 프롬프트에 (py310) 이 떠 있어도 `python3` 가 3.9 를 가리키기도 한다.
# 이 프로젝트는 `datetime | None` 같은 표기를 쓰므로 3.10 미만에서는 SQLAlchemy 가
# 모델 애노테이션을 해석하지 못하고 기동 중에 터진다. 그래서 여기서 걸러 낸다.
# ---------------------------------------------------------------------------
version_ok() {
  "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null
}

version_of() {
  "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "?"
}

if [ -n "$PYTHON" ]; then
  # 직접 지정했으면 조용히 다른 것으로 바꾸지 않는다. 맞지 않으면 그대로 알려 준다.
  if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "✗ PYTHON=$PYTHON 을 찾을 수 없습니다."
    exit 1
  fi
  if ! version_ok "$PYTHON"; then
    echo "✗ PYTHON=$PYTHON 은 $(version_of "$PYTHON") 입니다. Python $MIN_PY 이상이 필요합니다."
    exit 1
  fi
  PY="$PYTHON"
else
  PY=""
  for cand in python3 python python3.13 python3.12 python3.11 python3.10; do
    command -v "$cand" >/dev/null 2>&1 || continue
    if version_ok "$cand"; then PY="$cand"; break; fi
  done
  if [ -z "$PY" ]; then
    echo "✗ Python $MIN_PY 이상을 찾지 못했습니다."
    echo "  이 프로젝트는 'datetime | None' 표기를 써서 3.10 미만에서는 동작하지 않습니다."
    if command -v python3 >/dev/null 2>&1; then
      echo "  지금 python3 는 $(version_of python3) → $(command -v python3)"
    fi
    echo "  conda 를 쓴다면:  conda activate py310 && PYTHON=\$(which python) ./run.sh"
    exit 1
  fi
fi

echo "▶ 백엔드 의존성 설치"
echo "  파이썬: $("$PY" -c 'import sys; print(sys.executable)')  (버전 $(version_of "$PY"))"

# pip 를 돌린 파이썬과 서버를 띄우는 파이썬은 반드시 같아야 한다.
# uvicorn 을 콘솔 스크립트로 부르면 PATH 에 먼저 걸리는 다른 환경의 것이 잡혀서
# "설치는 됐다는데 모듈을 못 찾는다"는 상황이 난다. 그래서 둘 다 python -m 으로 부른다.
"$PY" -m pip install -q -r backend/requirements.txt

# 설치가 실제로 먹었는지 확인한다. 기동 중에 터지는 것보다 읽기 쉽다.
# (email-validator 는 pydantic 이 EmailStr 을 만들 때에야 필요해져서,
#  없으면 import 시점의 긴 스택트레이스로 나타난다)
if ! "$PY" - <<'PYCHK'
import importlib.util as u, sys
need = {
    "fastapi": "fastapi", "uvicorn": "uvicorn", "sqlalchemy": "sqlalchemy",
    "pydantic": "pydantic", "pydantic_settings": "pydantic-settings",
    "email_validator": "email-validator", "cryptography": "cryptography",
    "httpx": "httpx", "jwt": "PyJWT",
}
missing = [pkg for mod, pkg in need.items() if u.find_spec(mod) is None]
if missing:
    print("  빠진 패키지:", " ".join(missing))
    sys.exit(1)
PYCHK
then
  echo
  echo "✗ 백엔드 의존성이 빠져 있습니다. 아래를 실행한 뒤 다시 시도하세요."
  echo "    $PY -m pip install -r backend/requirements.txt"
  exit 1
fi

echo "▶ 프론트엔드 의존성 설치"
(cd frontend && npm install --silent)

echo "▶ 백엔드 http://localhost:8000  (문서: /docs)"
(cd backend && "$PY" -m uvicorn app.main:app --reload --port 8000) &
BACK=$!
trap 'kill $BACK 2>/dev/null' EXIT

sleep 2
echo "▶ 프론트엔드 http://localhost:5173"
cd frontend && npm run dev
