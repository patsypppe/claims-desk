"""Pre-authenticated channel assertions (e.g. a logged-in portal hands the chat a signed identity).

Token = base64url(json{party_id, exp, nonce}) + "." + base64url(HMAC-SHA256). Verification is constant-time,
rejects expired tokens and replays, and is only ever consumed through a permission-guarded tool.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Callable


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: str, key: str) -> str:
    return _b64(hmac.new(key.encode(), payload.encode(), hashlib.sha256).digest())


def mint(party_id: str, key: str, ttl: int = 300, now: Callable[[], float] = time.time) -> str:
    payload = _b64(json.dumps({"party_id": party_id, "exp": int(now()) + ttl,
                               "nonce": secrets.token_hex(8)}).encode())
    return f"{payload}.{_sign(payload, key)}"


class ChannelVerifier:
    def __init__(self, key: str, now: Callable[[], float] = time.time) -> None:
        self._key, self._now = key, now
        self._seen: set[str] = set()

    def verify(self, token: str) -> str | None:
        try:
            payload, signature = token.split(".")
            if not hmac.compare_digest(signature, _sign(payload, self._key)):
                return None
            claims = json.loads(_unb64(payload))
        except (ValueError, json.JSONDecodeError):
            return None
        if claims.get("exp", 0) < self._now() or claims.get("nonce") in self._seen:
            return None
        self._seen.add(claims["nonce"])
        return claims.get("party_id")
