"""HTTP Basic Auth dependency for host-only endpoints."""
import os
import secrets
from pathlib import Path

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

# Load secrets.env into os.environ if not already set
_secrets_file = Path(__file__).parent / "secrets.env"
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
