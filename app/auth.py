from fastapi import Request, HTTPException
from base64 import b64decode
from .config import BASIC_USER, BASIC_PASS, API_KEY, BEARER_TOKEN


def validate_basic(auth_header: str):
    try:
        encoded = auth_header.split(" ")[1]
        decoded = b64decode(encoded).decode()
        username, password = decoded.split(":")
        return username == BASIC_USER and password == BASIC_PASS
    except Exception:
        return False


async def authenticate(request: Request, allowed: list):
    auth_header = request.headers.get("authorization")
    api_key = request.headers.get("x-api-key")

    if not auth_header and not api_key:
        if "none" in allowed:
            return
        raise HTTPException(status_code=401, detail="Unauthorized")

    if api_key and "apikey" in allowed:
        if api_key == API_KEY:
            return
        raise HTTPException(status_code=401, detail="Invalid API Key")

    if auth_header:
        if auth_header.startswith("Basic") and "basic" in allowed:
            if validate_basic(auth_header):
                return
        if auth_header.startswith("Bearer") and "bearer" in allowed:
            if auth_header.split(" ")[1] == BEARER_TOKEN:
                return

    raise HTTPException(status_code=401, detail="Unauthorized")