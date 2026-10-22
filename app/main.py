import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from collections import Counter, defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from psycopg_pool import PoolTimeout
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import content, db

log = logging.getLogger("portfolio")
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
STARTED = time.time()

# configuration 
RATE_LIMIT, RATE_WINDOW = 60, 60            # API requests per IP per minute
CONTACT_LIMIT, CONTACT_WINDOW = 3, 3600     # contact messages per IP per hour
LOGIN_LIMIT, LOGIN_WINDOW = 10, 900         # admin login attempts per IP per 15 min
MAX_BODY_BYTES = 20_000                     # reject larger request bodies
MIN_ADMIN_PASSWORD = 12
TRUSTED_PROXY_HOPS = int(os.environ.get("TRUSTED_PROXY_HOPS", "1"))

# Content-Security-Policy
CSP_APP = (
    "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)

CSP_DOCS = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
    "object-src 'none'; frame-ancestors 'none'"
)
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")

# telemetry + limits
RECENT: deque = deque(maxlen=15)
ROUTE_HITS: Counter = Counter()
LATENCIES: deque = deque(maxlen=500)
TOTAL = {"requests": 0, "errors": 0, "rate_limited": 0}
_hits: dict = defaultdict(deque)
_contact_hits: dict = defaultdict(deque)
_login_hits: dict = defaultdict(deque)


def _allow(bucket: dict, key: str, limit: int, window: int) -> bool:
    now = time.time()
    q = bucket[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


def client_ip(request: Request) -> str:
    """Real client IP. X-Forwarded-For can be forged by the client, but each trusted proxy
    appends the address it saw, so we read from the right, TRUSTED_PROXY_HOPS entries in."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd and TRUSTED_PROXY_HOPS > 0:
        parts = [p.strip() for p in fwd.split(",") if p.strip()]
        if parts:
            return parts[max(0, len(parts) - TRUSTED_PROXY_HOPS)]
    return request.client.host if request.client else "unknown"


# admin auth
SECRET = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
TOKEN_TTL = 2 * 3600
bearer = HTTPBearer(auto_error=False)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _sign(payload: str) -> str:
    return _b64(hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).digest())


def make_token(exp: float | None = None) -> str:
    exp = time.time() + TOKEN_TTL if exp is None else exp
    payload = _b64(json.dumps({"sub": "admin", "exp": exp}).encode())
    return f"{payload}.{_sign(payload)}"


def verify_token(token: str) -> bool:
    try:
        payload, sig = token.split(".")
        if not hmac.compare_digest(sig, _sign(payload)):
            return False
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return data.get("sub") == "admin" and data["exp"] > time.time()
    except Exception:
        return False


def require_admin(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    if not creds or not verify_token(creds.credentials):
        raise HTTPException(401, "Admin login required (or your session expired). Run: login",
                            headers={"WWW-Authenticate": "Bearer"})


# app
@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    pw = os.environ.get("ADMIN_PASSWORD")
    if pw and not os.environ.get("SECRET_KEY"):
        log.warning("SECRET_KEY is not set: admin sessions will end whenever the server restarts.")
    if pw and len(pw) < MIN_ADMIN_PASSWORD:
        log.warning("ADMIN_PASSWORD is shorter than %d characters: admin login is disabled.", MIN_ADMIN_PASSWORD)
    yield
    db.close_db()


app = FastAPI(
    title="Portfolio API",
    description="The API behind my terminal portfolio. Try it from the terminal on the home page, or here.",
    version="2.0.0",
    lifespan=lifespan,
)

_hosts = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]
if _hosts:  # e.g. ALLOWED_HOSTS=your-app.onrender.com
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_hosts)


@app.exception_handler(psycopg.OperationalError)
@app.exception_handler(PoolTimeout)
async def db_unavailable(_: Request, exc: Exception):
    log.error("database unavailable: %s", exc)
    return JSONResponse({"detail": "The database is waking up or unavailable. Try again in a few seconds."}, status_code=503)


@app.middleware("http")
async def guard_and_observe(request: Request, call_next):
    start = time.perf_counter()
    path = request.url.path
    is_api = path.startswith("/api")

    cl = request.headers.get("content-length")
    if request.method in ("POST", "PUT", "PATCH") and cl and cl.isdigit() and int(cl) > MAX_BODY_BYTES:
        response = JSONResponse({"detail": "Request body too large."}, status_code=413)
    elif is_api and not _allow(_hits, client_ip(request), RATE_LIMIT, RATE_WINDOW):
        TOTAL["rate_limited"] += 1
        response = JSONResponse(
            {"error": "rate_limited", "detail": f"Limit is {RATE_LIMIT} requests per {RATE_WINDOW}s. Slow down."},
            status_code=429, headers={"Retry-After": str(RATE_WINDOW)},
        )
    else:
        response = await call_next(request)

    ms = (time.perf_counter() - start) * 1000
    if is_api:
        TOTAL["requests"] += 1
        if response.status_code >= 400:
            TOTAL["errors"] += 1
        ROUTE_HITS[f"{request.method} {path}"] += 1
        LATENCIES.append(ms)
        RECENT.appendleft({"time": time.strftime("%H:%M:%S"), "method": request.method, "path": path,
                           "status": response.status_code, "ms": round(ms, 1)})

    h = response.headers
    h["X-Response-Time-ms"] = f"{ms:.1f}"
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "strict-origin-when-cross-origin"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    h["Content-Security-Policy"] = CSP_DOCS if path.startswith(DOCS_PATHS) else CSP_APP
    if request.headers.get("x-forwarded-proto") == "https" or request.url.scheme == "https":
        h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if is_api:
        h["Cache-Control"] = "no-store"
    return response


# public routes
@app.api_route("/health", methods=["GET", "HEAD"], tags=["meta"])
def health():
    return {"status": "ok"}


@app.get("/api/profile", tags=["portfolio"])
def profile():
    return content.PROFILE


@app.get("/api/projects", tags=["portfolio"])
def list_projects(stack: str | None = None, status: str | None = None):
    """Filter with ?stack=Python or ?status=live."""
    with db.connect() as conn:
        rows = [db.project_row(r) for r in conn.execute("SELECT * FROM projects ORDER BY year DESC, slug")]
    if stack:
        rows = [r for r in rows if any(stack.lower() == s.lower() for s in r["stack"])]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


@app.get("/api/projects/{slug}", tags=["portfolio"])
def get_project(slug: str):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE slug = %s", (slug,)).fetchone()
    if not row:
        raise HTTPException(404, f"No project with slug '{slug}'. Try: ls projects")
    return db.project_row(row)


@app.get("/api/skills", tags=["portfolio"])
def list_skills(category: str | None = None):
    sql, args = "SELECT * FROM skills", ()
    if category:
        sql, args = sql + " WHERE category = %s", (category,)
    with db.connect() as conn:
        return list(conn.execute(sql + " ORDER BY level DESC, name", args))


@app.get("/api/experience", tags=["portfolio"])
def list_experience():
    with db.connect() as conn:
        return list(conn.execute("SELECT * FROM experience ORDER BY start DESC, id DESC"))


class Contact(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=120)
    message: str = Field(min_length=5, max_length=2000)


@app.post("/api/contact", status_code=201, tags=["portfolio"])
def contact(body: Contact, request: Request):
    ip = client_ip(request)
    if not _allow(_contact_hits, ip, CONTACT_LIMIT, CONTACT_WINDOW):
        raise HTTPException(429, "Too many messages from this address. Try again later.")
    with db.connect() as conn:
        row = conn.execute(
            "INSERT INTO contact_messages (name,email,message,ip) VALUES (%s,%s,%s,%s) RETURNING id",
            (body.name, body.email, body.message, ip),
        ).fetchone()
    return {"id": row["id"], "status": "received", "detail": "Thanks! I'll reply to your email."}


# read-only SQL
class Query(BaseModel):
    sql: str = Field(min_length=1, max_length=500)


#  block  catalog and admin-style functions.
_DENY = re.compile(r"(?i)\b(pg_\w+|information_schema|set_config|current_setting|lo_\w+|dblink\w*|copy)\b")


@app.post("/api/query", tags=["portfolio"])
def run_query(body: Query):
    """Read-only SQL over the projects, skills and experience tables."""
    sql = body.sql.strip().rstrip(";").strip()
    if ";" in sql or not re.match(r"(?is)^select\b", sql) or _DENY.search(sql):
        raise HTTPException(400, "Only a single, plain SELECT statement is allowed.")
    with db.readonly() as conn:
        if conn is None:
            raise HTTPException(503, "The sql command is not configured on this server.")
        try:
            conn.execute("SET TRANSACTION READ ONLY")
            conn.execute("SET LOCAL statement_timeout = 1000")
            cur = conn.execute(sql)
            rows = cur.fetchmany(50)
            cols = [d.name for d in cur.description] if cur.description else []
        except psycopg.errors.InsufficientPrivilege:
            raise HTTPException(400, f"Not allowed. Readable tables: {', '.join(sorted(db.PUBLIC_TABLES))}.")
        except psycopg.errors.QueryCanceled:
            raise HTTPException(400, "Query took too long (limit: 1 second).")
        except psycopg.Error as e:
            raise HTTPException(400, str(e).splitlines()[0])
    return {"columns": cols, "rows": [list(r) for r in rows], "row_count": len(rows), "truncated": len(rows) == 50}


# admin
class Login(BaseModel):
    password: str = Field(min_length=1, max_length=200)


@app.post("/api/admin/login", tags=["admin"])
def admin_login(body: Login, request: Request):
    expected = os.environ.get("ADMIN_PASSWORD")
    if not expected:
        raise HTTPException(503, "Admin is disabled. Set the ADMIN_PASSWORD environment variable and restart.")
    if len(expected) < MIN_ADMIN_PASSWORD:
        raise HTTPException(503, f"Admin is disabled: ADMIN_PASSWORD must be at least {MIN_ADMIN_PASSWORD} characters.")
    if not _allow(_login_hits, client_ip(request), LOGIN_LIMIT, LOGIN_WINDOW):
        raise HTTPException(429, "Too many login attempts. Try again in 15 minutes.")
    if not hmac.compare_digest(body.password.encode(), expected.encode()):
        log.warning("failed admin login from %s", client_ip(request))
        raise HTTPException(401, "Wrong password.")
    return {"token": make_token(), "token_type": "bearer", "expires_in": TOKEN_TTL}


YEAR_MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"


class NewExperience(BaseModel):
    company: str = Field(min_length=1, max_length=100)
    role: str = Field(min_length=1, max_length=100)
    start: str = Field(pattern=YEAR_MONTH, description="YYYY-MM")
    end: str | None = Field(default=None, pattern=YEAR_MONTH, description="YYYY-MM, or null for a current role")
    summary: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def end_after_start(self):
        if self.end and self.end < self.start:
            raise ValueError("end must not be earlier than start")
        return self


@app.post("/api/experience", status_code=201, tags=["admin"], dependencies=[Depends(require_admin)])
def add_experience(body: NewExperience):
    with db.connect() as conn:
        row = conn.execute(
            'INSERT INTO experience (company,role,start,"end",summary) VALUES (%s,%s,%s,%s,%s) RETURNING id',
            (body.company, body.role, body.start, body.end, body.summary),
        ).fetchone()
    return {"id": row["id"], **body.model_dump()}


@app.delete("/api/experience/{exp_id}", status_code=204, tags=["admin"], dependencies=[Depends(require_admin)])
def delete_experience(exp_id: int):
    with db.connect() as conn:
        row = conn.execute("DELETE FROM experience WHERE id = %s RETURNING id", (exp_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"No experience with id {exp_id}.")
    return Response(status_code=204)


# status + frontend 
@app.get("/api/status", tags=["meta"])
def status():
    lat = sorted(LATENCIES)

    def pct(p: float) -> float:
        return round(lat[min(len(lat) - 1, int(len(lat) * p))], 1) if lat else 0.0

    return {
        "uptime_seconds": int(time.time() - STARTED),
        "requests": TOTAL["requests"],
        "errors": TOTAL["errors"],
        "rate_limited": TOTAL["rate_limited"],
        "latency_ms": {"p50": pct(0.50), "p95": pct(0.95)},
        "top_routes": ROUTE_HITS.most_common(5),
        "recent": list(RECENT)[:8],
    }


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")