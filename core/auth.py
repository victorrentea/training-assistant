"""HTTP Basic Auth dependency for host-only endpoints."""
import hashlib
import hmac
import os
import secrets
from pathlib import Path
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

# Load shared secrets file into os.environ if not already set
_default_secrets_file = Path.home() / ".training-assistants-secrets.env"
_secrets_file = Path(
    os.environ.get("TRAINING_ASSISTANTS_SECRETS_FILE", str(_default_secrets_file))
).expanduser()
if _secrets_file.exists():
    for line in _secrets_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

_security = HTTPBasic()


def require_host_auth(credentials: HTTPBasicCredentials = Depends(_security)):
    expected_user = os.environ.get("HOST_USERNAME") or "host"
    expected_pass = os.environ.get("HOST_PASSWORD") or "host"
    if expected_pass == "host":
        import logging
        logging.getLogger(__name__).warning(
            "HOST_PASSWORD not set — using insecure default. Set HOST_PASSWORD env var."
        )
    ok = (
        secrets.compare_digest(credentials.username.encode(), expected_user.encode())
        and secrets.compare_digest(credentials.password.encode(), expected_pass.encode())
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


def get_host_cookie_token() -> str:
    """Derive a stable token from the host password for httponly cookie auth."""
    key = (os.environ.get("HOST_PASSWORD") or "host").encode()
    return hmac.new(key, b"host-cookie-auth", hashlib.sha256).hexdigest()[:32]


_security_optional = HTTPBasic(auto_error=False)


def require_host_auth_or_cookie(
    credentials: Optional[HTTPBasicCredentials] = Depends(_security_optional),
    is_host: Optional[str] = Cookie(default=None),
):
    """Accept either HTTP Basic Auth or a valid httponly host cookie (set after login)."""
    if is_host and secrets.compare_digest(is_host, get_host_cookie_token()):
        return
    if credentials:
        expected_user = os.environ.get("HOST_USERNAME") or "host"
        expected_pass = os.environ.get("HOST_PASSWORD") or "host"
        ok = (
            secrets.compare_digest(credentials.username.encode(), expected_user.encode())
            and secrets.compare_digest(credentials.password.encode(), expected_pass.encode())
        )
        if ok:
            return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Basic"},
    )
