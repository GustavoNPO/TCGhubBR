import os
import re
from functools import wraps
from urllib.parse import urlparse

import requests
from flask import Flask, g, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from services.tcgdex import (
    find_card_candidates,
    select_best_candidates,
    get_card_details,
    search_catalog_cards,
    get_catalog_sets,
    is_physical_card,
    normalize_number
)
from services.scryfall import (
    find_mtg_candidates,
    get_mtg_card,
    get_mtg_sets,
    search_mtg_cards,
    card_finishes,
    card_images,
    catalog_language as mtg_catalog_language,
    clean_number as mtg_clean_number,
    english_name as mtg_english_name,
    is_paper_card,
    printed_name as mtg_printed_name,
    MTG_FINISHES
)
from services.portfolio import (
    GAMES, add_portfolio_card, list_portfolio_cards, get_portfolio_card,
    list_portfolio_folders, create_portfolio_folder, update_portfolio_folder,
    delete_portfolio_folder, mutate_portfolio_cards, save_portfolio_prices,
    PortfolioNotFound
)
from services.auth import (
    SESSION_COOKIE, SESSION_DURATION, AuthError, create_client_token, create_session, forget_session,
    is_email_verified, revoke_sessions, verify_session
)
from services.chat import ChatError, ChatNotFound, mark_read, open_conversation, send_message
from services.ratelimit import RateLimited, RateLimiter
from services.vision import InvalidImage, extract_card_info
from services.accounts import (
    AccountError, clean_profile_update, ensure_account, find_profile_by_handle,
    get_profile, public_view, update_profile
)
from services.market import get_market_prices, prices_are_fresh
from services.firebase import FirebaseUnavailable
from services.ligamagic import liga_magic_link_for_card
from services.ligapokemon import CARD_CONDITIONS, liga_link_for_card
from services.pricing import get_international_prices, get_mtg_international_prices, PRICING_VERSION

app = Flask(__name__)
PRODUCTION = os.getenv("APP_ENV", "development") == "production"
# Só para desenvolvimento local e testes: entra direto como este uid, sem login.
# Nunca configure em um servidor acessível por outras pessoas.
app.config["DEV_AUTH_USER_ID"] = os.getenv("DEV_AUTH_USER_ID") or None
# "auto" marca o cookie como Secure quando a requisição chega por HTTPS.
app.config["SESSION_COOKIE_SECURE_MODE"] = os.getenv("SESSION_COOKIE_SECURE") or ("1" if PRODUCTION else "auto")
if PRODUCTION:
    # Um .env de desenvolvimento copiado para o servidor deixaria qualquer visitante entrar como esse uid.
    if app.config["DEV_AUTH_USER_ID"]:
        raise RuntimeError("DEV_AUTH_USER_ID não pode ser usado com APP_ENV=production.")
    # Atrás do nginx: o IP, o HTTPS e o host reais vêm dos cabeçalhos do proxy local.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
# Domínios aceitos no cabeçalho Host (ex.: "tcghub.com.br,www.tcghub.com.br"); vazio aceita qualquer um.
app.config["TRUSTED_HOSTS"] = [host.strip() for host in os.getenv("APP_HOSTS", "").split(",") if host.strip()] or None
# Fotos do scan; o nginx usa o mesmo teto (client_max_body_size).
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
# Cada scan chama o Gemini (custo por chamada): teto por pessoa e por hora.
scan_limit = RateLimiter(int(os.getenv("SCAN_LIMIT_PER_HOUR", "40")), 3600,
                         "Você atingiu o limite de scans por hora. Use a busca por nome ou tente mais tarde.")
_project_id = os.getenv("FIREBASE_PROJECT_ID")
app.config["FIREBASE_WEB_CONFIG"] = {
    "apiKey": os.getenv("FIREBASE_WEB_API_KEY"),
    "authDomain": os.getenv("FIREBASE_AUTH_DOMAIN") or (f"{_project_id}.firebaseapp.com" if _project_id else None),
    "projectId": _project_id,
    "appId": os.getenv("FIREBASE_APP_ID"),
}

CARD_LANGUAGES = {
    "en", "pt-br", "es", "fr", "de", "it", "ja", "ko", "ru",
    "zh-tw", "zh-cn", "unknown"
}
LANGUAGE_LABELS = {
    "en": "Inglês", "pt-br": "Português (Brasil)", "es": "Espanhol",
    "fr": "Francês", "de": "Alemão", "it": "Italiano", "ja": "Japonês",
    "ko": "Coreano", "ru": "Russo", "zh-tw": "Chinês tradicional",
    "zh-cn": "Chinês simplificado", "unknown": "Não identificado"
}
CATALOG_LANGUAGES = (CARD_LANGUAGES - {"unknown"}) | {"pt"}
CATALOG_LANGUAGE_LABELS = {
    **{code: label for code, label in LANGUAGE_LABELS.items() if code != "unknown"},
    "pt": "Português (catálogo pt)"
}
CARD_VARIANTS = {"pokemon": {"normal", "holo", "reverse"}, "magic": set(MTG_FINISHES)}
PROVIDERS = {"pokemon": "tcgdex", "magic": "scryfall"}


def request_game():
    game = request.args.get("game", "pokemon")
    return game if game in GAMES else None


@app.get("/api/cards/search")
def catalog_search():
    name = request.args.get("name", "").strip()
    number = request.args.get("collector_number", "").strip()
    language = request.args.get("catalog_language", "auto")
    set_id = request.args.get("set_id", "").strip()
    page_value = request.args.get("page", "1")
    page = int(page_value) if re.fullmatch(r"[0-9]{1,3}", page_value) else None
    game = request_game()
    if (
        not game or (name and not 2 <= len(name) <= 120) or len(number) > 50
        or not (name or number or set_id) or language not in CATALOG_LANGUAGES | {"auto"}
        or (set_id and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", set_id))
        or page is None or not 1 <= page <= 100
        or (number and not re.fullmatch(r"[A-Za-z0-9-]+(?:\s*/\s*[A-Za-z0-9]+)?", number))
    ):
        return jsonify(status="error", error="Informe o nome ou use coleção e número para encontrar a carta."), 400
    try:
        search = search_mtg_cards if game == "magic" else search_catalog_cards
        cards = search(name, number, language, set_id)
    except (requests.RequestException, ValueError):
        return jsonify(status="error", error="Catálogo indisponível. Tente buscar novamente."), 502
    start = (page - 1) * 12
    return jsonify(status="ok", candidates=cards[start:start + 12], page=page,
                   has_more=len(cards) > start + 12, total=len(cards))


@app.get("/api/sets")
def catalog_sets():
    game = request_game()
    if not game:
        return jsonify(status="error", sets=[], message="Jogo inválido."), 400
    try:
        return jsonify(status="ok", sets=get_mtg_sets() if game == "magic" else get_catalog_sets())
    except (requests.RequestException, ValueError):
        return jsonify(status="unavailable", sets=[], message="Coleções indisponíveis. Você pode continuar buscando por nome."), 502


@app.get("/api/cards/<card_id>/prices")
def catalog_prices(card_id):
    language = request.args.get("catalog_language", "en")
    variant = request.args.get("variant", "")
    game = request_game()
    if (
        not game or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", card_id)
        or language not in CATALOG_LANGUAGES
        or variant not in CARD_VARIANTS[game] | {""}
    ):
        return jsonify(status="error", error="Dados da carta inválidos."), 400
    if game == "magic":
        return mtg_catalog_prices(card_id, variant)
    try:
        card = get_card_details(card_id, language)
        if card is None:
            return jsonify(status="error", error="Carta não encontrada."), 404
        if not is_physical_card(card):
            return jsonify(status="error", error="Esta carta é do Pokémon Pocket. Busque uma edição física."), 400
        quotes = get_international_prices(card, variant, language)
    except (requests.RequestException, ValueError):
        return jsonify(status="unavailable", quotes=[], message="Referência internacional indisponível."), 502
    return jsonify(
        status="ok" if quotes else "unavailable", quotes=quotes,
        catalog_language=language,
        pricing_version=PRICING_VERSION,
        # A Liga é conferida por link: edição e número levam à carta exata.
        liga=liga_link_for_card(card),
        card={"name": card["name"], "image": card.get("image"), "set_name": (card.get("set") or {}).get("name"),
              "local_id": card.get("localId"), "set_total": (card.get("set") or {}).get("cardCount", {}).get("official"),
              "variants": card.get("variants") or {}},
        message="Referência do exterior. A conversão não confirma o valor da carta no Brasil, seu idioma ou conservação."
    )


def mtg_catalog_prices(card_id, variant):
    try:
        card = get_mtg_card(card_id)
        if card is None:
            return jsonify(status="error", error="Carta não encontrada."), 404
        if not is_paper_card(card):
            return jsonify(status="error", error="Esta carta é só digital. Busque uma edição física."), 400
        quotes = get_mtg_international_prices(card, variant)
    except (requests.RequestException, ValueError):
        return jsonify(status="unavailable", quotes=[], message="Referência internacional indisponível."), 502
    thumb, image = card_images(card)
    return jsonify(
        status="ok" if quotes else "unavailable", quotes=quotes,
        catalog_language=mtg_catalog_language(card), pricing_version=PRICING_VERSION,
        liga=liga_magic_link_for_card(card),
        card={"name": mtg_printed_name(card), "image": None, "image_url": image, "thumb_url": thumb,
              "set_name": card.get("set_name"), "local_id": card.get("collector_number"), "set_total": None,
              "variants": card_finishes(card)},
        message="Referência do exterior. A conversão não confirma o valor da carta no Brasil, seu idioma ou conservação."
    )


class AuthRequired(Exception):
    pass


@app.before_request
def load_session_user():
    """O dono vem do cookie de sessão verificado; o navegador nunca escolhe o uid."""
    g.user = None
    if request.endpoint == "static":
        return None
    claims = verify_session(request.cookies.get(SESSION_COOKIE))
    if claims:
        g.user = {"uid": claims["uid"], "email": claims.get("email"), "name": claims.get("name"),
                  "picture": claims.get("picture"), "email_verified": bool(claims.get("email_verified"))}
    elif app.config["DEV_AUTH_USER_ID"]:
        g.user = {"uid": app.config["DEV_AUTH_USER_ID"], "email": None, "name": "Desenvolvimento",
                  "picture": None, "email_verified": False, "dev": True}
    # O cookie SameSite=Lax já barra POST vindo de outros sites; a origem é conferida também.
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).netloc != request.host:
            return jsonify(status="error", error="Origem da requisição não permitida."), 403
    return None


def get_current_user_id():
    if not g.get("user"):
        raise AuthRequired()
    user_id = g.user["uid"]
    if not isinstance(user_id, str) or not user_id.strip() or "/" in user_id:
        raise AuthRequired()
    return user_id


def safe_next(value):
    # Só caminhos internos: evita redirecionar para outro site depois do login.
    if isinstance(value, str) and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return url_for("home")


@app.errorhandler(AuthRequired)
def handle_auth_required(_error):
    login_url = url_for("login_page", next=request.full_path.rstrip("?"))
    if request.path.startswith("/api/") or request.path == "/scan":
        return jsonify(status="error", error="Entre na sua conta para continuar.", login_url=login_url), 401
    return redirect(login_url)


def wants_json():
    return request.path.startswith("/api/") or request.path == "/scan"


@app.errorhandler(RateLimited)
def handle_rate_limited(error):
    response = jsonify(status="error", error=str(error))
    response.headers["Retry-After"] = str(error.retry_after)
    return response, 429


HTTP_MESSAGES = {
    400: "Requisição inválida.", 404: "Endereço não encontrado.", 405: "Operação não permitida.",
    413: "Arquivo grande demais. Envie uma foto de até 10 MB.", 429: "Muitas requisições. Aguarde um instante."
}


@app.errorhandler(HTTPException)
def handle_http_error(error):
    # Na API, erros (inclusive os não tratados, que viram 500) saem em JSON e sem detalhes internos.
    if not wants_json():
        return error
    message = HTTP_MESSAGES.get(error.code, "Não foi possível concluir a operação. Tente novamente.")
    return jsonify(status="error", error=message), error.code


# O app não usa scripts inline: só arquivos próprios e os SDKs do Firebase/Google.
# Imagens, conexões e iframes ficam livres (catálogos, avatares e login do Firebase).
CONTENT_SECURITY_POLICY = "; ".join((
    "script-src 'self' https://www.gstatic.com https://apis.google.com https://www.google.com/recaptcha/",
    "object-src 'none'", "base-uri 'self'", "form-action 'self'", "frame-ancestors 'none'"
))


@app.after_request
def security_headers(response):
    headers = response.headers
    headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("X-Frame-Options", "DENY")
    headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), payment=(), usb=()")
    if wants_json():
        headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/healthz")
def healthz():
    """Para o nginx/monitoramento: o processo responde, sem tocar em Firebase ou Gemini."""
    return jsonify(status="ok")


def login_required(function):
    @wraps(function)
    def handle(*args, **kwargs):
        get_current_user_id()
        return function(*args, **kwargs)
    return handle


@app.context_processor
def inject_user():
    return {"current_user": g.get("user")}


def profile_json(profile):
    if not profile:
        return None
    fields = ("uid", "handle", "display_name", "bio", "avatar_url", "profile_visibility", "portfolio_visibility")
    return {key: profile.get(key) for key in fields}


@app.get("/entrar")
def login_page():
    if g.user and not g.user.get("dev"):
        return redirect(safe_next(request.args.get("next")))
    config = app.config["FIREBASE_WEB_CONFIG"]
    configured = bool(config.get("apiKey") and config.get("projectId"))
    return render_template("login.html", firebase_config=config if configured else None,
                           next_url=safe_next(request.args.get("next")))


@app.post("/api/auth/session")
def start_session():
    data = request.get_json(silent=True)
    id_token = data.get("id_token") if isinstance(data, dict) else None
    if not isinstance(id_token, str) or not 20 <= len(id_token) <= 4096:
        return jsonify(status="error", error="Login inválido."), 400
    try:
        cookie, claims = create_session(id_token)
        profile = ensure_account(claims)
    except AuthError as error:
        return jsonify(status="error", error=str(error)), 401
    except FirebaseUnavailable as error:
        return jsonify(status="error", error=str(error)), 503
    except Exception:
        app.logger.exception("Erro ao iniciar sessão")
        return jsonify(status="error", error="Não foi possível entrar agora. Tente novamente."), 503
    mode = app.config["SESSION_COOKIE_SECURE_MODE"]
    response = jsonify(status="ok", profile=profile_json(profile), redirect_url=safe_next(data.get("next")))
    response.set_cookie(
        SESSION_COOKIE, cookie, max_age=int(SESSION_DURATION.total_seconds()), httponly=True,
        secure=request.is_secure if mode == "auto" else mode == "1", samesite="Lax", path="/"
    )
    return response


@app.post("/api/auth/logout")
def end_session():
    data = request.get_json(silent=True) or {}
    forget_session(request.cookies.get(SESSION_COOKIE))
    if data.get("everywhere") is True and g.user and not g.user.get("dev"):
        try:
            revoke_sessions(g.user["uid"])
        except Exception:
            app.logger.exception("Erro ao encerrar sessões")
            return jsonify(status="error", error="Não foi possível encerrar as outras sessões."), 503
    response = jsonify(status="ok", redirect_url=url_for("login_page"))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@app.post("/api/auth/client-token")
@login_required
def client_token():
    """Base do chat: o SDK do navegador entra como o mesmo uid, sem novo login."""
    if g.user.get("dev"):
        return jsonify(status="error", error="Indisponível na sessão de desenvolvimento."), 400
    try:
        return jsonify(status="ok", token=create_client_token(g.user["uid"]))
    except Exception:
        app.logger.exception("Erro ao emitir token do cliente")
        return jsonify(status="error", error="Não foi possível conectar o chat agora."), 503


@app.get("/api/me")
@login_required
def me():
    try:
        profile = get_profile(g.user["uid"])
    except FirebaseUnavailable as error:
        return jsonify(status="error", error=str(error)), 503
    user = {key: value for key, value in g.user.items() if key != "dev"}
    return jsonify(status="ok", user=user, profile=profile_json(profile))


@app.patch("/api/me/profile")
@login_required
def edit_profile():
    try:
        changes = clean_profile_update(request.get_json(silent=True))
        profile = update_profile(g.user["uid"], changes)
    except AccountError as error:
        return jsonify(status="error", error=str(error)), 400
    except FirebaseUnavailable as error:
        return jsonify(status="error", error=str(error)), 503
    except Exception:
        app.logger.exception("Erro ao atualizar perfil")
        return jsonify(status="error", error="Não foi possível salvar o perfil. Tente novamente."), 503
    return jsonify(status="ok", profile=profile_json(profile),
                   public_url=url_for("public_profile", handle=profile["handle"], _external=True))


@app.get("/perfil")
@login_required
def profile_page():
    try:
        profile = get_profile(g.user["uid"])
    except FirebaseUnavailable as error:
        return render_template("profile.html", profile=None, error=str(error)), 503
    public_url = url_for("public_profile", handle=profile["handle"], _external=True) if profile else None
    return render_template("profile.html", profile=profile, error=None, public_url=public_url)


@app.get("/u/<handle>")
def public_profile(handle):
    try:
        profile = find_profile_by_handle(handle)
        view = None
        if profile:
            view = public_view(profile, list_portfolio_cards(profile["uid"]),
                               list_portfolio_folders(profile["uid"]), (g.user or {}).get("uid"))
    except FirebaseUnavailable as error:
        return render_template("public_profile.html", view=None, error=str(error)), 503
    if view is None:
        # Perfil privado e inexistente respondem igual: não revelamos quem tem conta.
        return render_template("public_profile.html", view=None, error=None), 404
    return render_template("public_profile.html", view=view, error=None, language_labels=LANGUAGE_LABELS)


def chat_blocker():
    """Motivo para a pessoa ainda não poder conversar, ou None."""
    if g.user.get("dev"):
        return "O chat precisa de uma conta real. Entre com e-mail ou Google."
    if not g.user.get("email_verified") and not is_email_verified(g.user["uid"]):
        return "Confirme seu e-mail pelo link que enviamos para conversar com outros colecionadores."
    return None


@app.get("/conversas")
@login_required
def chat_page():
    config = app.config["FIREBASE_WEB_CONFIG"]
    try:
        blocker = chat_blocker()
    except Exception:
        app.logger.exception("Erro ao verificar conta para o chat")
        blocker = "Não foi possível abrir as conversas agora. Tente novamente."
    if not blocker and not (config.get("apiKey") and config.get("projectId")):
        blocker = "Chat indisponível: o Firebase do navegador não está configurado."
    return render_template("chat.html", firebase_config=config, blocker=blocker,
                           me={"uid": g.user["uid"]}, selected=request.args.get("c", ""))


def chat_api(function):
    @wraps(function)
    @login_required
    def handle(*args, **kwargs):
        try:
            blocker = chat_blocker()
            if blocker:
                return jsonify(status="error", error=blocker), 403
            return function(*args, **kwargs)
        except RateLimited:
            raise
        except ChatNotFound as error:
            return jsonify(status="error", error=str(error)), 404
        except ChatError as error:
            return jsonify(status="error", error=str(error)), 400
        except FirebaseUnavailable as error:
            return jsonify(status="error", error=str(error)), 503
        except Exception:
            app.logger.exception("Erro no chat")
            return jsonify(status="error", error="Não foi possível concluir a operação. Tente novamente."), 503
    return handle


@app.post("/api/chat/conversations")
@chat_api
def start_conversation():
    data = request.get_json(silent=True)
    handle = data.get("handle") if isinstance(data, dict) else None
    other = find_profile_by_handle(handle) if isinstance(handle, str) else None
    # Só perfis públicos recebem conversas novas; privado e inexistente respondem igual.
    if not other or other.get("profile_visibility") != "public":
        raise ChatNotFound("Perfil não encontrado.")
    profile = get_profile(g.user["uid"])
    if not profile:
        raise ChatError("Entre novamente para criar seu perfil.")
    conversation = open_conversation(profile, other)
    return jsonify(status="ok", conversation_id=conversation, url=url_for("chat_page", c=conversation))


@app.post("/api/chat/conversations/<conversation>/messages")
@chat_api
def post_message(conversation):
    data = request.get_json(silent=True)
    message_id = send_message(g.user["uid"], conversation, data.get("text") if isinstance(data, dict) else None)
    return jsonify(status="ok", message_id=message_id), 201


@app.post("/api/chat/conversations/<conversation>/read")
@chat_api
def read_conversation(conversation):
    mark_read(g.user["uid"], conversation)
    return jsonify(status="ok")


@app.get("/portfolio")
@login_required
def portfolio():
    try:
        user_id = get_current_user_id()
        cards = list_portfolio_cards(user_id)
        folders = list_portfolio_folders(user_id)
    except FirebaseUnavailable as error:
        return render_template(
            "portfolio.html", cards=[], folders=[], error=str(error),
            language_labels={**LANGUAGE_LABELS, "pt": "Português (catálogo pt)"}
        ), 503
    except Exception:
        app.logger.exception("Erro ao carregar portfolio")
        return render_template(
            "portfolio.html", cards=[], folders=[],
            error="Não foi possível carregar seu inventário. Tente novamente.",
            language_labels={**LANGUAGE_LABELS, "pt": "Português (catálogo pt)"}
        ), 503

    return render_template(
        "portfolio.html", cards=cards, folders=folders, error=None,
        language_labels={**LANGUAGE_LABELS, "pt": "Português (catálogo pt)"}
    )


def portfolio_api(function):
    @wraps(function)
    @login_required
    def handle(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except PortfolioNotFound as error:
            return jsonify(status="error", error=str(error)), 404
        except ValueError as error:
            return jsonify(status="error", error=str(error)), 400
        except FirebaseUnavailable as error:
            return jsonify(status="error", error=str(error)), 503
        except Exception:
            app.logger.exception("Erro na manutenção do portfólio")
            return jsonify(status="error", error="Não foi possível concluir a operação. Tente novamente."), 503
    return handle


def portfolio_json():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("Envie um objeto JSON válido.")
    return data


def portfolio_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}", value):
        raise ValueError("Identificador inválido.")
    return value


def folder_name(data):
    name = data.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError("Informe um nome de pasta com até 80 caracteres.")
    return name.strip()


@app.post("/api/portfolio/folders")
@portfolio_api
def create_folder():
    data = portfolio_json()
    game = data.get("game", "pokemon")
    if game not in GAMES:
        raise ValueError("Jogo inválido.")
    folder_id = create_portfolio_folder(get_current_user_id(), folder_name(data), game)
    return jsonify(status="ok", folder_id=folder_id), 201


@app.patch("/api/portfolio/folders/<folder_id>")
@portfolio_api
def rename_folder(folder_id):
    folder_id = portfolio_id(folder_id)
    data = portfolio_json()
    changes = {}
    if "name" in data:
        changes["name"] = folder_name(data)
    if "visibility" in data:
        # Pasta pública aparece no perfil público mesmo com o portfólio privado.
        if data["visibility"] not in ("private", "public"):
            raise ValueError("Visibilidade inválida.")
        changes["visibility"] = data["visibility"]
    if not changes:
        raise ValueError("Informe o nome ou a visibilidade da pasta.")
    update_portfolio_folder(get_current_user_id(), folder_id, changes)
    return jsonify(status="ok")


@app.delete("/api/portfolio/folders/<folder_id>")
@portfolio_api
def delete_folder(folder_id):
    delete_portfolio_folder(get_current_user_id(), portfolio_id(folder_id))
    return jsonify(status="ok")


@app.post("/api/portfolio/cards/bulk")
@portfolio_api
def maintain_cards():
    data = portfolio_json()
    action = data.get("action")
    if action not in ("move", "delete", "reorder"):
        raise ValueError("Operação inválida.")
    card_ids = data.get("card_ids")
    if not isinstance(card_ids, list) or not 1 <= len(card_ids) <= 450:
        raise ValueError("Selecione de 1 a 450 cartas por operação.")
    card_ids = [portfolio_id(card_id) for card_id in card_ids]
    if len(set(card_ids)) != len(card_ids):
        raise ValueError("A seleção contém cartas repetidas.")
    folder_id = data.get("folder_id")
    if action == "move" and folder_id is not None:
        folder_id = portfolio_id(folder_id)
    mutate_portfolio_cards(get_current_user_id(), card_ids, action, folder_id)
    return jsonify(status="ok")


@app.delete("/api/portfolio/cards/<card_id>")
@portfolio_api
def delete_card(card_id):
    mutate_portfolio_cards(get_current_user_id(), [portfolio_id(card_id)], "delete")
    return jsonify(status="ok")


@app.patch("/api/portfolio/cards/<card_id>")
@portfolio_api
def move_card(card_id):
    data = portfolio_json()
    if "folder_id" not in data:
        raise ValueError("Informe a pasta de destino.")
    folder_id = data["folder_id"]
    if folder_id is not None:
        folder_id = portfolio_id(folder_id)
    mutate_portfolio_cards(get_current_user_id(), [portfolio_id(card_id)], "move", folder_id)
    return jsonify(status="ok")


@app.post("/api/portfolio/cards/<card_id>/prices")
@portfolio_api
def portfolio_prices(card_id):
    data = portfolio_json()
    force = data.get("force", False)
    if not isinstance(force, bool):
        raise ValueError("Atualização inválida.")
    user_id = get_current_user_id()
    item = get_portfolio_card(user_id, portfolio_id(card_id))
    saved = item.get("market_prices")
    if saved and saved.get("pricing_version") != PRICING_VERSION:
        # Não reapresenta como fallback uma cotação do mapeamento antigo.
        saved = None
    if saved and not force and prices_are_fresh(saved):
        return jsonify(**saved, cached=True)
    prices = get_market_prices(item, force=force)
    if prices["status"] == "ok":
        save_portfolio_prices(user_id, card_id, prices)
    elif saved and saved.get("status") == "ok":
        return jsonify(**saved, cached=True, stale=True,
                       refresh_message="Não foi possível atualizar. Exibindo a última referência salva.")
    return jsonify(**prices, cached=False)


@app.post("/api/portfolio/cards")
@login_required
def create_portfolio_card():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(status="error", error="Envie um objeto JSON válido."), 400

    game = data.get("game")
    if game not in GAMES or data.get("provider") != PROVIDERS[game]:
        return jsonify(
            status="error", error="Jogo ou catálogo não disponível."
        ), 400

    external_id = data.get("external_id")
    language = data.get("language", "unknown")
    catalog_language = data.get("catalog_language")
    collector_number = data.get("collector_number")
    condition = data.get("condition")
    variant = data.get("variant") or None

    if (
        not isinstance(external_id, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", external_id)
        or not isinstance(language, str) or language not in CARD_LANGUAGES
        or not isinstance(catalog_language, str)
        or catalog_language not in CATALOG_LANGUAGES
        or (condition is not None and (
            not isinstance(condition, str) or condition not in CARD_CONDITIONS
        ))
        or (variant is not None and (
            not isinstance(variant, str) or variant not in CARD_VARIANTS[game]
        ))
        or (
            collector_number is not None and (
                not isinstance(collector_number, str) or len(collector_number) > 50
            )
        )
    ):
        return jsonify(status="error", error="Dados da carta inválidos."), 400

    if game == "magic":
        return create_mtg_portfolio_card(external_id, language, collector_number, condition, variant)

    try:
        user_id = get_current_user_id()
        # Nome, coleção e imagem vêm do catálogo, não do navegador.
        card = get_card_details(external_id, catalog_language)
        if card is None:
            return jsonify(
                status="error", error="Carta não encontrada no catálogo. Faça outro scan."
            ), 404

        if not is_physical_card(card):
            return jsonify(status="error", error="Pokémon Pocket não pode ser adicionado como carta física."), 400

        if variant and (card.get("variants") or {}).get(variant) is False:
            return jsonify(status="error", error="Esta variante não está disponível para a edição escolhida."), 400

        image = card.get("image")
        # O número de catálogo confirma a carta; não cotamos outra edição
        # apenas porque um número diferente foi digitado no navegador.
        if collector_number and normalize_number(collector_number) != normalize_number(card.get("localId")):
            return jsonify(status="error", error="O número não corresponde à carta selecionada."), 400
        local_id = str(card.get("localId") or "")
        total = (card.get("set") or {}).get("cardCount", {}).get("official")
        item = {
            "game": "pokemon",
            "provider": "tcgdex",
            "external_id": card["id"],
            "name": card["name"],
            "collector_number": f"{local_id}/{total}" if local_id and total else local_id,
            "set_name": card.get("set", {}).get("name"),
            "set_id": card.get("set", {}).get("id"),
            "set_total": total,
            "folder_id": None,
            "image_url": f"{image}/high.webp" if image else None,
            "language": language,
            "catalog_language": catalog_language,
            "condition": condition,
            "variant": variant,
            "favorite": False,
            "for_trade": False,
            "for_sale": False
        }
        card_id = add_portfolio_card(user_id, item)
    except FirebaseUnavailable as error:
        return jsonify(status="error", error=str(error)), 503
    except (requests.RequestException, ValueError):
        app.logger.exception("Erro ao consultar detalhes no TCGdex")
        return jsonify(
            status="error", error="Catálogo indisponível. Tente confirmar novamente."
        ), 502
    except Exception:
        app.logger.exception("Erro ao salvar carta no portfolio")
        return jsonify(
            status="error", error="Não foi possível salvar a carta. Tente novamente."
        ), 503

    return jsonify(
        status="ok", card_id=card_id, redirect_url=url_for("portfolio")
    ), 201


def create_mtg_portfolio_card(external_id, language, collector_number, condition, variant):
    try:
        user_id = get_current_user_id()
        # Nome, coleção e imagem vêm do Scryfall, não do navegador.
        card = get_mtg_card(external_id)
        if card is None:
            return jsonify(status="error", error="Carta não encontrada no catálogo. Faça outro scan."), 404
        if not is_paper_card(card):
            return jsonify(status="error", error="Cartas só digitais não podem ser adicionadas como carta física."), 400
        if variant and not card_finishes(card).get(variant):
            return jsonify(status="error", error="Este acabamento não existe para a impressão escolhida."), 400
        if collector_number and mtg_clean_number(collector_number) != mtg_clean_number(card.get("collector_number")):
            return jsonify(status="error", error="O número não corresponde à carta selecionada."), 400
        _thumb, image = card_images(card)
        item = {
            "game": "magic",
            "provider": "scryfall",
            "external_id": card["id"],
            "name": mtg_printed_name(card),
            "english_name": mtg_english_name(card),
            "collector_number": card.get("collector_number"),
            "set_name": card.get("set_name"),
            "set_id": card.get("set"),
            "set_total": None,
            "folder_id": None,
            "image_url": image,
            "language": language,
            "catalog_language": mtg_catalog_language(card),
            "condition": condition,
            "variant": variant,
            "favorite": False,
            "for_trade": False,
            "for_sale": False
        }
        card_id = add_portfolio_card(user_id, item)
    except FirebaseUnavailable as error:
        return jsonify(status="error", error=str(error)), 503
    except (requests.RequestException, ValueError):
        app.logger.exception("Erro ao consultar detalhes no Scryfall")
        return jsonify(status="error", error="Catálogo indisponível. Tente confirmar novamente."), 502
    except Exception:
        app.logger.exception("Erro ao salvar carta no portfolio")
        return jsonify(status="error", error="Não foi possível salvar a carta. Tente novamente."), 503
    return jsonify(status="ok", card_id=card_id, redirect_url=url_for("portfolio", game="magic")), 201


ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp"
}


@app.route("/")
@login_required
def home():

    return render_template(
        "index.html", language_labels=LANGUAGE_LABELS,
        catalog_language_labels=CATALOG_LANGUAGE_LABELS
    )


@app.route("/scan", methods=["POST"])
@login_required
def scan():

    print("\n--- NOVO SCAN ---")


    # =========================
    # 1. RECEBER A FOTO
    # =========================

    image = request.files.get("card")

    if not image:

        return jsonify({
            "error": "Nenhuma imagem enviada."
        }), 400


    print("Imagem recebida:", image.filename)
    print("Formato:", image.mimetype)


    # =========================
    # 2. VALIDAR O FORMATO
    # =========================

    if image.mimetype not in ALLOWED_IMAGE_TYPES:

        return jsonify({
            "error": "Formato de imagem não suportado."
        }), 400


    scan_limit.hit(get_current_user_id())
    image_bytes = image.read()


    print(
        "Tamanho:",
        round(
            len(image_bytes) / 1024,
            2
        ),
        "KB"
    )


    try:

        # =========================
        # 3. GEMINI ANALISA A CARTA
        # =========================

        print("Enviando imagem para o Gemini...")


        card_info = extract_card_info(
            image_bytes
        )


        print("Gemini respondeu:")
        print(card_info)


        # =========================
        # 4. CONFIANÇA BAIXA
        # =========================

        if card_info.confidence < 0.55:

            print(
                "Confiança muito baixa:",
                card_info.confidence
            )

            return jsonify({

                "status": "retry",

                "message": (
                    "Não conseguimos ler a carta com "
                    "segurança. Tente tirar outra foto "
                    "com melhor iluminação e a carta "
                    "inteira visível."
                ),

                "detected": card_info.model_dump(),

                "candidates": []

            })


        # =========================
        # 5. VER QUAL É O TCG
        # =========================

        print(
            "TCG identificado:",
            card_info.game
        )


        # Pokémon (TCGdex) e Magic (Scryfall) têm catálogo.
        #
        # Digimon e Star Wars já podem
        # ser reconhecidos pelo Gemini,
        # mas ainda não possuem provider.

        if card_info.game not in GAMES:

            return jsonify({

                "status": "game_detected",

                "message": (
                    f"Identificamos uma carta de "
                    f"{card_info.game}, mas o catálogo "
                    f"desse TCG ainda não foi integrado."
                ),

                "detected": card_info.model_dump(),

                "candidates": []

            })


        # =========================
        # 6. BUSCAR NO CATÁLOGO DO JOGO
        # =========================

        if card_info.game == "magic":

            print("Buscando candidatos no Scryfall...")

            candidates = find_mtg_candidates(
                card_info
            )

        else:

            print("Buscando candidatos no TCGdex...")

            candidates = find_card_candidates(
                card_info
            )


        print(
            "Candidatos encontrados:",
            len(candidates)
        )


        # =========================
        # 7. ESCOLHER OS MELHORES
        # =========================

        candidates = select_best_candidates(
            candidates,
            card_info.confidence
        )


        print(
            "Candidatos selecionados:",
            len(candidates)
        )


        # =========================
        # 8. NENHUM MATCH CONFIÁVEL
        # =========================

        if not candidates:

            return jsonify({

                "status": "retry",

                "message": (
                    "Conseguimos ler parte da carta, "
                    "mas não encontramos uma "
                    "correspondência confiável. "
                    "Tente aproximar a câmera e "
                    "evitar reflexos."
                ),

                "detected": card_info.model_dump(),

                "candidates": []

            })


        # =========================
        # 9. SUCESSO
        # =========================

        return jsonify({

            "status": "ok",

            "detected": card_info.model_dump(),

            "candidates": candidates

        })


    except InvalidImage as error:

        return jsonify({"status": "error", "error": str(error)}), 400


    except Exception as error:

        print("\nERRO DURANTE O SCAN:")
        print(repr(error))


        return jsonify({

            "status": "error",

            "error": (
                "Não foi possível analisar "
                "a carta."
            )

        }), 500


if __name__ == "__main__":

    # Servidor de desenvolvimento. Em produção quem roda o app é o gunicorn (deploy/).
    if PRODUCTION:
        raise SystemExit("Em produção use o gunicorn: veja docs/deploy-oracle-cloud.md.")

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )