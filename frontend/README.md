# Frontend (React + TypeScript + Vite)

Run from WSL:

    cd ~/datadna/frontend
    npm install
    npm run dev          # http://localhost:5173
    npm run lint
    npm run build
    npm test

Needs `VITE_API_BASE=/api` in `frontend/.env.local` and `COOKIE_PATH=/api/auth` in `~/datadna/.env`
(see `.env.example`). The dev server forwards `/api` to the backend on port 8000.
