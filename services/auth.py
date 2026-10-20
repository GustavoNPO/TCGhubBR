"""Sessão do servidor com Firebase Authentication.

O navegador faz login com o SDK do Firebase e envia o ID token uma única vez.
O servidor troca esse token por um cookie de sessão HttpOnly; a partir daí,
o dono do inventário vem sempre do cookie verificado, nunca do navegador.
"""
import hashlib
import time
from datetime import timedelta
from threading import Lock

from services.firebase import FirebaseUnavailable, get_firebase_app


SESSION_COOKIE = "__session"
SESSION_DURATION = timedelta(days=5)
# Só aceitamos trocar tokens de logins recentes: um token roubado e antigo não abre sessão.
RECENT_SIGN_IN_SECONDS = 5 * 60
VERIFY_CACHE_SECONDS = 5 * 60
_verified = {}
_verify_lock = Lock()


class AuthError(ValueError):
    pass


def _auth():
    try:
        from firebase_admin import auth
    except ImportError as error:
        raise FirebaseUnavailable("Instale as dependências do projeto para usar o login.") from error
    return auth, get_firebase_app()


def create_session(id_token):
    """Valida o ID token e devolve (cookie de sessão, claims)."""
    auth, app = _auth()
    try:
        claims = auth.verify_id_token(id_token, app=app, check_revoked=True)
    except (auth.InvalidIdTokenError, auth.ExpiredIdTokenError, auth.RevokedIdTokenError,
            auth.UserDisabledError, ValueError) as error:
        raise AuthError("Login inválido ou expirado. Entre novamente.") from error
    if time.time() - claims.get("auth_time", 0) > RECENT_SIGN_IN_SECONDS:
        raise AuthError("Faça login novamente para continuar.")
    try:
        cookie = auth.create_session_cookie(id_token, expires_in=SESSION_DURATION, app=app)
    except auth.FirebaseError as error:
        raise AuthError("Não foi possível iniciar a sessão. Tente novamente.") from error
    return cookie, claims


def verify_session(cookie):
    """Claims do cookie ou None.

    Verifica revogação ("sair de todos os dispositivos") com um cache curto:
    uma sessão revogada deixa de valer em até VERIFY_CACHE_SECONDS sem que cada
    página consulte o Firebase.
    """
    if not cookie:
        return None
    key = hashlib.sha256(cookie.encode()).hexdigest()
    now = time.monotonic()
    with _verify_lock:
        cached = _verified.get(key)
        if cached and cached[0] > now:
            return cached[1]
    try:
        auth, app = _auth()
        claims = auth.verify_session_cookie(cookie, app=app, check_revoked=True)
    except Exception:
        return None
    with _verify_lock:
        if len(_verified) >= 1024:
            _verified.pop(next(iter(_verified)))
        _verified[key] = (now + VERIFY_CACHE_SECONDS, claims)
    return claims


def forget_session(cookie):
    if cookie:
        with _verify_lock:
            _verified.pop(hashlib.sha256(cookie.encode()).hexdigest(), None)


def revoke_sessions(uid):
    """Encerra as sessões do usuário em todos os dispositivos."""
    auth, app = _auth()
    auth.revoke_refresh_tokens(uid, app=app)
    with _verify_lock:
        for key in [key for key, (_, claims) in _verified.items() if claims.get("uid") == uid]:
            _verified.pop(key, None)


def create_client_token(uid):
    """Token para o SDK do navegador entrar como o mesmo uid (chat em tempo real).

    O navegador não guarda login próprio: quando precisar do Firestore direto,
    pede este token ao servidor e chama signInWithCustomToken. Exige credencial
    de conta de serviço (a mesma de GOOGLE_APPLICATION_CREDENTIALS).
    """
    auth, app = _auth()
    token = auth.create_custom_token(uid, app=app)
    return token.decode() if isinstance(token, bytes) else token