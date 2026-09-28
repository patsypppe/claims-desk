"""HTTP API + static demo UI. Sessions are server-issued (httpOnly cookie); clients never choose ids."""
import logging
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import Cookie, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from claims_agent.agent import MAX_INPUT_CHARS, build_agent
from claims_agent.config import Settings
from claims_agent.sessions import UnknownSessionError

log = logging.getLogger("claims_agent.api")
WEB_DIR = Path(__file__).resolve().parents[1] / "web"
RATE_LIMIT, RATE_WINDOW_S = 30, 60.0
SECURITY_HEADERS = {
    "Content-Security-Policy": ("default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
                                "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
                                "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class SessionIn(BaseModel):
    channel_token: str | None = Field(default=None, max_length=1024)


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_INPUT_CHARS)
    sensitive: bool = False  # "secure field": this turn is processed on-server only (never sent to an LLM)

    @field_validator("text")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value


def _public_event(event) -> dict:
    """Debug view: validator internals (which atom was rejected) are summarized, not exposed."""
    data = event.model_dump(mode="json")
    if "violations" in data["detail"]:
        data["detail"] = {"count": len(data["detail"]["violations"])}
    return data


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    agent = build_agent(settings)
    hits: dict[str, deque] = defaultdict(deque)
    app = FastAPI(title="Claims Support Agent", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    def _set_cookie(response: Response, sid: str) -> None:
        response.set_cookie("sid", sid, httponly=True, samesite="strict", secure=settings.cookie_secure,
                            max_age=settings.session_ttl_minutes * 60)

    def _rate_limited(key: str, limit: int) -> bool:
        now, window = time.monotonic(), hits[key]
        while window and now - window[0] > RATE_WINDOW_S:
            window.popleft()
        window.append(now)
        if len(hits) > 10_000:  # prune idle keys so the map can't grow without bound
            for idle in [k for k, w in hits.items() if not w or now - w[-1] > RATE_WINDOW_S]:
                hits.pop(idle, None)
        return len(window) > limit

    @app.get("/healthz")
    def health() -> dict:
        return {"status": "ok", "mode": settings.agent_mode}

    @app.post("/api/session")
    def new_session(request: Request, response: Response, body: SessionIn | None = None) -> dict:
        client = request.client.host if request.client else "unknown"
        if _rate_limited(f"create:{client}", settings.session_create_limit):
            raise HTTPException(status_code=429, detail="Too many new conversations. Please wait a minute.")
        agent.sessions.prune()
        _set_cookie(response, agent.new_session(channel_token=body.channel_token if body else None))
        return {"ok": True, "mode": settings.agent_mode, "debug_panel": settings.debug_panel}

    @app.post("/api/reset")
    def reset(response: Response, sid: str | None = Cookie(default=None)) -> dict:
        if sid:
            agent.sessions.drop(sid)
        _set_cookie(response, agent.new_session())
        return {"ok": True}

    @app.post("/api/chat")
    def chat(body: ChatIn, sid: str | None = Cookie(default=None)) -> dict:
        if not sid:
            raise HTTPException(status_code=401, detail="No session. Start a new conversation.")
        if _rate_limited(f"chat:{sid}", RATE_LIMIT):
            raise HTTPException(status_code=429, detail="Too many messages. Please slow down.")
        try:
            result = agent.handle(sid, body.text, sensitive=body.sensitive)
        except UnknownSessionError:
            raise HTTPException(status_code=401, detail="Session expired. Start a new conversation.") from None
        log.info("turn phase=%s escalated=%s events=%s", result.snapshot.phase, result.snapshot.escalated,
                 [e.kind for e in result.events])
        payload = {"reply": result.reply}
        if settings.debug_panel:
            payload["snapshot"] = result.snapshot.model_dump(mode="json")
            payload["events"] = [_public_event(e) for e in result.events]
        return payload

    @app.exception_handler(Exception)
    async def unexpected(_request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "Something went wrong. Please try again."})

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app
