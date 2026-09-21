"""Signed, expiring login tokens stored in a browser cookie.

Streamlit keeps login state in per-connection session state, which is lost
whenever the websocket drops for more than ~2 minutes (laptop sleep, wifi
change) or the tab is reloaded. A signed cookie lets a returning browser
prove it logged in recently without the server remembering anything.
"""

import hashlib
import hmac
import time


def _sign(secret: str, expiry: int) -> str:
    return hmac.new(secret.encode("utf-8"), str(expiry).encode("ascii"), hashlib.sha256).hexdigest()


def make_token(secret: str, ttl_seconds: int, now: float | None = None) -> tuple[str, int]:
    """Return (token, expiry_unix_seconds) valid for ttl_seconds from now."""
    expiry = int((time.time() if now is None else now) + ttl_seconds)
    return f"{expiry}.{_sign(secret, expiry)}", expiry


def verify_token(secret: str, token: str | None, now: float | None = None) -> int | None:
    """Return the token's expiry if it is authentic and unexpired, else None."""
    if not token or "." not in token:
        return None
    expiry_text, signature = token.split(".", 1)
    if not expiry_text.isdigit():
        return None
    expiry = int(expiry_text)
    if not hmac.compare_digest(signature, _sign(secret, expiry)):
        return None
    if (time.time() if now is None else now) >= expiry:
        return None
    return expiry
