"""Route di autenticazione Google OAuth2."""
import logging
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from authlib.integrations.starlette_client import OAuth

import config
from auth.session import get_current_user, set_session_cookie, _COOKIE_NAME
from auth.whitelist import load_whitelist

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

oauth = OAuth()


def init_oauth() -> None:
    """Initialize OAuth registration with current config values."""
    oauth.register(
        name="google",
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_id=config.GOOGLE_CLIENT_ID,
        client_secret=config.GOOGLE_CLIENT_SECRET,
        client_kwargs={"scope": "openid email profile"},
    )

_UNAUTHORIZED_HTML = """<!DOCTYPE html>
<html lang="it">
<head><meta charset="UTF-8"><title>Accesso negato</title>
<style>
body{background:#111;color:#eee;font-family:sans-serif;
     display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.box{text-align:center}h1{color:#e74c3c}a{color:#aaa}
</style></head>
<body><div class="box">
<h1>Accesso non autorizzato</h1>
<p>Il tuo account Google non è nella lista degli utenti autorizzati.</p>
<a href="/auth/logout">&#x2190; Torna al login</a>
</div></body></html>"""


def callback_url(request) -> str:
    """
    URL di callback da dichiarare a Google.
    Deve combaciare carattere per carattere con quello registrato in console:
    dietro un proxy la richiesta arriva su localhost, quindi quando
    PUBLIC_BASE_URL e' configurata ha la precedenza sull'URL della richiesta.
    """
    if config.PUBLIC_BASE_URL:
        return config.PUBLIC_BASE_URL.rstrip("/") + request.url_for("auth_callback").path
    return str(request.url_for("auth_callback"))


@router.get("/login")
async def login(request: Request):
    return await oauth.google.authorize_redirect(request, callback_url(request))


@router.get("/callback", name="auth_callback")
async def callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    user_info = token.get("userinfo") or {}
    email = (user_info.get("email") or "").lower()

    whitelist = load_whitelist(config.AUTHORIZED_EMAILS_PATH)
    if email not in whitelist:
        logger.warning("Accesso negato per: %s", email)
        return HTMLResponse(_UNAUTHORIZED_HTML, status_code=403)

    response = RedirectResponse(url="/")
    set_session_cookie(response, {
        "email": email,
        "name": user_info.get("name", ""),
        "picture": user_info.get("picture", ""),
    })
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse(url="/auth/login")
    response.delete_cookie(_COOKIE_NAME)
    return response


@router.get("/me")
def me(request: Request):
    user = get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Non autenticato")
    return user
