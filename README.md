# Lyftr AI Chat

A full-stack, multi-turn LLM chat app with LiteLLM caching, ordered API-key failover, per-reply usage metadata, and SQLite-backed session history.

## 1. Live URLs

- Frontend: not deployed yet — deploy the `frontend/` directory as a Vercel project.
- Backend: not deployed yet — deploy the `backend/` directory as a separate Vercel project.
- Public GitHub repository: add the repository URL after publishing this workspace.
- Demo video: add the public 2–3 minute recording URL after recording.

This workspace contains the Vercel deployment configuration, but a public deployment cannot be created from the repository alone: it needs a Vercel account, provider API keys, and project environment variables. No real credentials or URLs are included here.

### Vercel deployment (both tiers on Vercel)

Create two Vercel projects from the same Git repository:

1. **Backend:** set the project root to `backend/`. Vercel reads `backend/vercel.json` and `backend/requirements.txt`. Add these environment variables in the Vercel project settings:
   - `LLM_API_KEYS`: two or more comma-separated provider keys; keep these secret.
   - `LLM_MODEL`: a LiteLLM model name supported by those keys, e.g. `gemini/gemini-3.5-flash-lite` (Google's listed Gemini 3.5 Flash-Lite model).
   - `DATABASE_URL`: `sqlite:////tmp/app.db` for the Vercel function filesystem.
   - `ALLOWED_ORIGINS`: the exact deployed frontend origin, e.g. `https://your-frontend.vercel.app`.
   - `ENABLE_FAILURE_SIMULATION`: `true`.
   - `DEFAULT_SYSTEM_PROMPT`: `You are a helpful assistant.`
2. **Frontend:** set the project root to `frontend/`. Add `VITE_API_BASE_URL` as the deployed backend base URL (no trailing slash), then redeploy so Vite bakes it into the static build.
3. Set the backend `ALLOWED_ORIGINS` to the final public frontend origin and redeploy the backend.
4. Check `<backend-url>/health`, then open the frontend URL and send a message.

**Vercel/SQLite limitation:** Vercel Functions do not provide a persistent mounted Docker volume. `/tmp/app.db` is writable but ephemeral and instance-local; history is not guaranteed to survive a cold start or to be shared between function instances. This is the closest Vercel-only setup while retaining SQLite and no external database. Durable, shared SQLite history is provided by the required local Docker setup through the named `/data` volume. Vercel alone cannot guarantee the assignment's durable SQLite-volume requirement; use a host with persistent volumes if that requirement must hold in production.

## 2. Run locally: with Docker and without

### With Docker

1. Copy `.env.example` to `.env` and replace the two example key values with real keys. Never commit `.env`.
2. From the repository root, run `make up`.
3. Open `http://localhost:3000`; the API is at `http://localhost:8000`.
4. Stop the stack with `make down`. The named `app_data` volume preserves SQLite history across container recreation.

The local frontend and backend are built into separate multi-stage Docker images. Compose mounts the named volume at `/data`; the default database path is `sqlite:////data/app.db`.

### Without Docker

Requirements: Python 3.12+, Node.js 22+, and npm.

1. In `backend/`, create and activate a virtual environment, then install `requirements-dev.txt` (it includes the runtime requirements and test tools).
2. Set `LLM_API_KEYS`, `LLM_MODEL`, `DATABASE_URL` (for example `sqlite:///./app.db`), `ALLOWED_ORIGINS=http://localhost:3000`, and `ENABLE_FAILURE_SIMULATION=true` in the backend shell.
3. Start the API from `backend/` with `uvicorn main:app --reload --port 8000`.
4. In a second terminal, set `VITE_API_BASE_URL=http://localhost:8000` in the frontend shell, run `npm install`, and run `npm run dev -- --port 3000` from `frontend/`.

SQLite creates its schema automatically. The provider key values are read only by the backend and are never returned by the API.

## 3. Design decisions: key fallback, caching, SQLite session storage

- **Key fallback:** `LLM_API_KEYS` is tried in its listed order and exposed only as safe IDs (`key_1`, `key_2`, …). Each call uses LiteLLM. A provider exception moves to the next key; the API returns only a generic JSON `503` after all keys fail. Failed requests are not committed to history.
- **Failure simulation:** when `ENABLE_FAILURE_SIMULATION=true`, `X-Simulate-Failure` can mark selected keys as failed for a single request. Simulations happen before the LiteLLM call and never mutate or exhaust the real keys.
- **Caching:** LiteLLM's local cache is enabled on provider calls. An in-process response index keyed by the model and canonical full message list gives deterministic cache-hit metadata and cached usage values. Exact prompt repeats—including the system prompt and conversation history—reuse the identical response, report `LLM_CACHE`, set `key_id` to `null`, and do not call the provider again. Cache contents are in memory and reset on process restart.
- **Conversation state:** the browser creates a new random session ID per page load and submits only the new message. SQLite stores messages and the session's system prompt. The system prompt is sent to the model but is omitted from the history endpoint. User and assistant rows are committed together only after a successful inference.
- **Usage metadata:** prompt and completion tokens are reported per request from LiteLLM's provider usage, not accumulated across the conversation. The response includes source, model, latency, token counts, safe key ID, and fallback count.

## 4. Verification: how to see failover, cache hits and per-message token usage

With the local stack and two real provider keys configured:

- **Health:** `GET http://localhost:8000/health` returns the key count and cache status.
- **Failover:** send a chat request with `X-Simulate-Failure: key_1=429`. It should answer through `key_2`, with `fallback_attempts: 1`. Try `key_1=500,key_2=429` to make all configured keys fail, or `*=429`; this should return `503 {"detail":"all providers unavailable"}` and create no history.
- **Cache hit:** send the same message in two different new sessions. The first assistant reply should say `LIVE_INFERENCE`; the second should say `LLM_CACHE`, have the same reply and token counts, and have `key_id: null`. A changed message or system prompt has a different cache key.
- **Multi-turn:** send a follow-up in the same page/session. The assistant receives the earlier user/assistant turns. `GET /sessions/{session_id}/messages` returns user and assistant messages oldest-first, without the system prompt.
- **UI:** each assistant reply displays the resolution source, model, latency in milliseconds, and input/output tokens. The send field clears after submission. API errors are displayed inline.
- **Tests:** run `make test` from the repository root. Tests stub the provider so no API keys or paid model calls are needed.

The simulation header only takes effect when the backend has `ENABLE_FAILURE_SIMULATION=true`. The header is intentionally not exposed as a frontend control; use an API client to demonstrate it.

## 5. Setup Used: your editor and AI tools

- Editor: Visual Studio Code.
- AI tools: GitHub Copilot (AI-assisted implementation).

## 6. Bonus features (if any): what you added beyond the requirements and why

- Optional per-session system prompt, accessible from the chat header.
- Responsive chat layout, connection status, starter prompts, and inline error states.
- Separate Vercel project configurations for the React frontend and FastAPI backend.
- A small additional `sessions` table stores system-prompt settings and lets the history route distinguish an existing empty session from an unknown one.
