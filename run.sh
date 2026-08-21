#!/usr/bin/env bash
# 백엔드(8000)와 프론트엔드(5173)를 함께 띄운다.
set -e
cd "$(dirname "$0")"

echo "▶ 백엔드 의존성 설치"
python3 -m pip install -q -r backend/requirements.txt

echo "▶ 프론트엔드 의존성 설치"
(cd frontend && npm install --silent)

echo "▶ 백엔드 http://localhost:8000  (문서: /docs)"
(cd backend && uvicorn app.main:app --reload --port 8000) &
BACK=$!
trap 'kill $BACK 2>/dev/null' EXIT

sleep 2
echo "▶ 프론트엔드 http://localhost:5173"
cd frontend && npm run dev
