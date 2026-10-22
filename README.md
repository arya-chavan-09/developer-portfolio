# Developer portfolio (FastAPI + SQLite)

A backend-developer portfolio where the terminal is the front end of a real API.
Every command (`projects`, `skills`, `sql …`, `curl …`) sends an HTTP request to the FastAPI
server, which reads from a SQLite database. A "Visual" mode gives non-technical visitors a
normal page built from the same API.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://localhost:8000 · API docs at http://localhost:8000/docs

```bash
pytest -q          # run the tests
docker build -t portfolio . && docker run -p 8000:8000 -v portfolio-data:/data portfolio
```

## Admin: manage experience from the terminal

Admin is off until you set a password. It is read from the environment, never stored in the code or database.

```bash
ADMIN_PASSWORD='choose-a-long-password' SECRET_KEY='any-long-random-string' uvicorn app.main:app --reload
```

In the terminal:

| Command | What it does |
|---|---|
| `login` | Prompts for the password (masked). Session lasts 2 hours. |
| `experience` | Lists entries; ids are shown once you are logged in. |
| `exp add` | Prompts for company, role, start, end (blank = current) and summary. |
| `exp rm <id>` | Deletes an entry after you type `yes`. |
| `logout` | Ends the session. |

Security notes: login attempts are rate limited (10 per 15 minutes per IP), tokens are HMAC-signed and expire,
and only `POST /api/experience` and `DELETE /api/experience/{id}` need a token. Set `SECRET_KEY` in production so
sessions survive restarts, and serve the site over HTTPS (Render, Railway and Fly.io do this by default).
The same endpoints appear in `/docs`, where the Authorize button accepts the token.

## Make it yours

1. Edit `app/content.py` (profile, projects, skills, experience).
2. Delete the `data/` folder so the database is re-seeded, then restart.
3. Change the `<title>` and meta description in `static/index.html`.
4. Messages sent via `contact` are stored in the `contact_messages` table
   (`sqlite3 data/portfolio.db "SELECT * FROM contact_messages"`).

## What's in it

| Piece | Where |
|---|---|
| REST API, validation, OpenAPI docs | `app/main.py` |
| Per-IP sliding-window rate limiting (60 req/min; 3 contact messages/hour) | `app/main.py` |
| Request telemetry shown by the `status` command (p50/p95, top routes) | `app/main.py` |
| Read-only SQL endpoint using a SQLite authorizer (table allow-list, 1s timeout, 50-row cap) | `app/main.py` |
| Schema and seeding | `app/db.py` |
| Tests, including SQL-injection and rate-limit cases | `tests/test_api.py` |
| Docker image and GitHub Actions CI | `Dockerfile`, `.github/workflows/ci.yml` |

## Deploy

Render, Railway or Fly.io can run the Dockerfile directly. Attach a persistent volume at
`/data`, otherwise the SQLite file (and stored messages) resets on each deploy. Because
the frontend is served by the same app, there is nothing else to host.

## Ideas to extend

- Email yourself on new contact messages (SMTP or a provider API)
- Swap SQLite for PostgreSQL and add Redis for the rate limiter
- JWT-protected `/admin/messages` endpoint
- Prometheus `/metrics` and a Grafana screenshot in your README
