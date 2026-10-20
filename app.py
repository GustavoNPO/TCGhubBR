import os
import re
from functools import wraps
from urllib.parse import urlparse

import requests
from flask import Flask, g, jsonify, redirect, render_template, request, url_for

from services.tcgdex import (
    find_card_candidates,
    select_best_candidates,
    get_card_details,
    search_catalog_cards,
    get_catalog_sets,
    is_physical_card,
    normalize_number
)
from services.portfolio import (
    add_portfolio_card, list_portfolio_cards, get_portfolio_card,
    list_portfolio_folders, create_portfolio_folder, update_portfolio_folder,
    delete_portfolio_folder, mutate_portfolio_cards, save_portfolio_prices,
    PortfolioNotFound
)
from services.auth import (
    SESSION_COOKIE, SESSION_DURATION, AuthError, create_client_token, create_session, forget_session,
    revoke_sessions, verify_session
)
from services.accounts import (
    AccountError, clean_profile_update, ensure_account, find_profile_by_handle,
    get_profile, public_view, update_profile
)
from services.market import get_market_prices, prices_are_fresh
from services.firebase import FirebaseUnavailable
from services.ligapokemon import CARD_CONDITIONS, liga_link_for_card
from services.pricing import get_international_prices, PRICING_VERSION

app = Flask(__name__)
# Só para desenvolvimento local e testes: entra direto como este uid, sem login.
# Nunca configure em um servidor acessível por outras pessoas.
app.config["DEV_AUTH_USER_ID"] = os.getenv("DEV_AUTH_USER_ID") or None
# "auto" marca o cookie como Secure quando a requisição chega por HTTPS.
app.config["SESSION_COOKIE_SECURE_MODE"] = os.getenv("SESSION_COOKIE_SECURE", "auto")
_project_id = os.getenv("FIREBASE_PROJECT_ID")
app.config["FIREBASE_WEB_CONFIG"] = {
    "apiKey": os.getenv("FIREBASE_WEB_API_KEY"),
    "authDomain": os.getenv("FIREBASE_AUTH_DOMAIN") or (f"{_project_id}.firebaseapp.com" if _project_id else None),
    "projectId": _project_id,
    "appId": os.getenv("FIREBASE_APP_ID"),
}

CARD_LANGUAGES = {
    "en", "pt-br", "es", "fr", "de", "it", "ja", "ko",
    "zh-tw", "zh-cn", "unknown"
}
LANGUAGE_LABELS = {
    "en": "Inglês", "pt-br": "Português (Brasil)", "es": "Espanhol",
    "fr": "Francês", "de": "Alemão", "it": "Italiano", "ja": "Japonês",
    "ko": "Coreano", "zh-tw": "Chinês tradicional",
    "zh-cn": "Chinês simplificado", "unknown": "Não identificado"
}
CATALOG_LANGUAGES = (CARD_LANGUAGES - {"unknown"}) | {"pt"}
CATALOG_LANGUAGE_LABELS = {
    **{code: label for code, label in LANGUAGE_LABELS.items() if code != "unknown"},
    "pt": "Português (catálogo pt)"
}
CARD_VARIANTS = {"normal", "holo", "reverse"}


@app.get("/api/cards/search")
def catalog_search():
    name = request.args.get("name", "").strip()
    number = request.args.get("collector_number", "").strip()
    language = request.args.get("catalog_language", "auto")
    set_id = request.args.get("set_id", "").strip()
    page_value = request.args.get("page", "1")
    page = int(page_value) if re.fullmatch(r"[0-9]{1,3}", page_value) else None
    if (
        (name and not 2 <= len(name) <= 120) or len(number) > 50
        or not (name or number or set_id) or language not in CATALOG_LANGUAGES | {"auto"}
        or (set_id and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", set_id))
        or page is None or not 1 <= page <= 100
        or (number and not re.fullmatch(r"[A-Za-z0-9]+(?:\s*/\s*[A-Za-z0-9]+)?", number))
    ):
        return jsonify(status="error", error="Informe o nome ou use coleção e número para encontrar a carta."), 400
    try:
        cards = search_catalog_cards(name, number, language, set_id)
    except (requests.RequestException, ValueError):
        return jsonify(status="error", error="Catálogo indisponível. Tente buscar novamente."), 502
    start = (page - 1) * 12
    return jsonify(status="ok", candidates=cards[start:start + 12], page=page,
                   has_more=len(cards) > start + 12, total=len(cards))


@app.get("/api/sets")
def catalog_sets():
    try:
        return jsonify(status="ok", sets=get_catalog_sets())
    except (requests.RequestException, ValueError):
        return jsonify(status="unavailable", sets=[], message="Coleções indisponíveis. Você pode continuar buscando por nome."), 502


@app.get("/api/cards/<card_id>/prices")
def catalog_prices(card_id):
    language = request.args.get("catalog_language", "en")
    variant = request.args.get("variant", "")
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", card_id)
        or language not in CATALOG_LANGUAGES
        or variant not in CARD_VARIANTS | {""}
    ):
        return jsonify(status="error", error="Dados da carta inválidos."), 400
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
    name = folder_name(portfolio_json())
    folder_id = create_portfolio_folder(get_current_user_id(), name)
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

    if data.get("game") != "pokemon" or data.get("provider") != "tcgdex":
        return jsonify(
            status="error", error="Somente Pokémon via TCGdex está disponível."
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
            not isinstance(variant, str) or variant not in CARD_VARIANTS
        ))
        or (
            collector_number is not None and (
                not isinstance(collector_number, str) or len(collector_number) > 50
            )
        )
    ):
        return jsonify(status="error", error="Dados da carta inválidos."), 400

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


# Limite máximo de upload: 10 MB
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024


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

        # Cadastro manual funciona mesmo sem configurar o cliente Gemini.
        from services.vision import extract_card_info

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


        # Por enquanto só integramos Pokémon.
        #
        # Magic, Digimon e Star Wars já podem
        # ser reconhecidos pelo Gemini,
        # mas ainda não possuem provider.

        if card_info.game != "pokemon":

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
        # 6. BUSCAR NO TCGDEX
        # =========================

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

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )