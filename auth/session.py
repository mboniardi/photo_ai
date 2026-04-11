"""Firma e verifica del cookie di sessione con itsdangerous."""
import logging
from typing import Optional

from fastapi import Request
from itsdangerous import URLSafeTimedSerializer, BadSignature

import config

logger = logging.getLogger(__name__)

_COOKIE_NAME = "photo_ai_session"
_MAX_AGE_SECONDS = 30 * 24 * 3600  # 30 days


def create_session_token(user_info: dict, secret_key: str) -> str:
    s = URLSafeTimedSerializer(secret_key)
    return s.dumps(user_info)


def decode_session_token(token: str, secret_key: str) -> Optional[dict]:
    s = URLSafeTimedSerializer(secret_key)
    try:
        return s.loads(token, max_age=_MAX_AGE_SECONDS)
    except BadSignature as exc:
        logger.debug("Session token invalido: %s", exc)
        return None


def get_current_user(request: Request) -> Optional[dict]:
    token = request.cookies.get(_COOKIE_NAME)
    if not token:
        return None
    return decode_session_token(token, config.SECRET_KEY)


def require_auth(request: Request) -> dict:
    from fastapi import HTTPException
    user = get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Non autenticato")
    whitelist = getattr(request.app.state, "whitelist", None)
    if whitelist is not None and user.get("email") not in whitelist:
        raise HTTPException(status_code=403, detail="Accesso non autorizzato")
    return user


def set_session_cookie(response, user_info: dict) -> None:
    token = create_session_token(user_info, config.SECRET_KEY)
    response.set_cookie(
        _COOKIE_NAME,
        token,
        max_age=_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
    )
