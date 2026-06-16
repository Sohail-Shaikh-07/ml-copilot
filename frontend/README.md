# ML Copilot Frontend

React + Vite shell for the ML Copilot API.

The frontend expects the backend API to serve session, chat, approval, event stream, and metrics endpoints under `/api`.

## Run

```bash
npm ci
npm run dev
```

By default the app proxies `/api` to `http://127.0.0.1:8000`.

To point at another backend, set:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## Build

```bash
npm run build
```

The production Dockerfile copies `frontend/dist` into the backend image. When that directory contains `index.html`, the FastAPI app serves the built frontend from `/` while keeping API routes under `/api`.
