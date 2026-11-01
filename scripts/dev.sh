#!/usr/bin/env bash
set -e

echo "Starting CodeTwin Development Environment..."

# Launch backend in background
(cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000) &
BACKEND_PID=$!

# Launch frontend
(cd frontend && npm run dev) &
FRONTEND_PID=$!

trap "kill $BACKEND_PID $FRONTEND_PID" EXIT
wait
