#!/bin/bash
set -e

echo "=== 1. Starting Fabric containers (only peers and orderer exist) ==="
docker start peer0.org1.example.com peer0.org2.example.com orderer.example.com 2>&1 || true

echo "=== 2. Starting PostgreSQL ==="
cd ~/datadna && docker compose up -d db

echo "=== 3. Waiting for containers to stabilize (15s) ==="
sleep 15

echo "=== 4. Writing frontend API address to .env.local ==="
# The browser calls /api on the same address as the page. The Vite dev server forwards it to port 8000.
echo "VITE_API_BASE=/api" > ~/datadna/frontend/.env.local

echo "=== 5. Starting backend (background) ==="
cd ~/datadna/backend
source venv/bin/activate
nohup uvicorn app.main:app --reload --port 8000 --host 127.0.0.1 > /tmp/backend.log 2>&1 &
echo "Backend starting... (log: /tmp/backend.log)"

sleep 3

echo "=== 6. Testing backend ==="
curl -s "http://127.0.0.1:8000/health" > /dev/null && echo "Backend OK" || echo "Backend NOT responding yet, check /tmp/backend.log"

echo ""
echo "=== DONE ==="
echo "Backend API docs: http://localhost:8000/docs"
echo "Now run the frontend in a new terminal:"
echo "  cd ~/datadna/frontend && npm run dev"
echo "Then open http://localhost:5173"
echo ""
echo "Needs COOKIE_PATH=/api/auth in ~/datadna/.env (see .env.example)."
