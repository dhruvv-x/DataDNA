#!/bin/bash
set -e

echo "=== 1. Starting Fabric containers ==="
docker start peer0.org1.example.com peer0.org2.example.com orderer.example.com ca_org1 ca_org2 ca_orderer 2>&1 || true

echo "=== 2. Waiting for containers to stabilize (15s) ==="
sleep 15

echo "=== 3. Detecting WSL IP ==="
WSL_IP=$(ip addr show eth0 | grep "inet " | awk '{print $2}' | cut -d/ -f1)
echo "WSL IP: $WSL_IP"

echo "=== 4. Updating frontend API URLs to current IP ==="
cd ~/datadna/frontend
# Replace any existing IP pattern (172.x.x.x:8000) with the current one
sed -i -E "s|http://[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:8000|http://${WSL_IP}:8000|g" src/App.tsx
echo "Frontend now points to: http://${WSL_IP}:8000"

echo "=== 5. Starting backend (background) ==="
cd ~/datadna/backend
source venv/bin/activate
nohup uvicorn app.main:app --reload --port 8000 --host 0.0.0.0 > /tmp/backend.log 2>&1 &
echo "Backend starting... (log: /tmp/backend.log)"

sleep 3

echo "=== 6. Testing backend ==="
curl -s "http://${WSL_IP}:8000/datasets" > /dev/null && echo "Backend OK" || echo "Backend NOT responding yet, check /tmp/backend.log"

echo ""
echo "=== DONE ==="
echo "Backend: http://${WSL_IP}:8000"
echo "Now run frontend manually in a new terminal:"
echo "  cd ~/datadna/frontend && npm run dev"
echo ""
echo "If ca_org2 shows an error above, ignore it — not needed for the demo."
