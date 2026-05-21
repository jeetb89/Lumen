#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

# Backend
cd "$ROOT/chatbot"
[ ! -d ".venv" ] && python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
.venv/bin/pip install -q -e ../sdk   # local editable SDK install
.venv/bin/uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!

# Ingestion service
cd "$ROOT/ingestion"
[ ! -d ".venv" ] && python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
.venv/bin/uvicorn main:app --reload --port 8001 &
INGESTION_PID=$!

# Frontend
cd "$ROOT/frontend"
npm install --silent
npm run dev &
FRONTEND_PID=$!

trap "kill $BACKEND_PID $INGESTION_PID $FRONTEND_PID 2>/dev/null" EXIT INT TERM

echo ""
echo "  Backend    → http://localhost:8000"
echo "  Ingestion  → http://localhost:8001"
echo "  Frontend   → http://localhost:5173"
echo ""
wait
