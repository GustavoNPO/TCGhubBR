import os
import re
from functools import wraps

import requests
from flask import Flask, jsonify, render_template, request, url_for

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
    list_portfolio_folders, create_portfolio_folder, rename_portfolio_folder,
    delete_portfolio_folder, mutate_portfolio_cards, save_portfolio_prices,
    PortfolioNotFound
)
from services.market import get_market_prices, prices_are_fresh
from services.firebase import FirebaseUnavailable
from services.ligapokemon import CARD_CONDITIONS, liga_link_for_card
from services.pricing import get_international_prices, PRICING_VERSION

app = Flask(__name__)
app.config["DEV_USER_ID"] = os.getenv("DEV_USER_ID", "demo-user")

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


def get_current_user_id():
    # Futuramente: UID do token Firebase Authentication validado no servidor.
    # O navegador nunca escolhe o dono do inventário.
    user_id = app.config["DEV_USER_ID"]
    if not isinstance(user_id, str) or not user_id.strip() or "/" in user_id:
        raise FirebaseUnavailable("Configure um DEV_USER_ID válido no servidor.")
    return user_id

@app.get("/portfolio")
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
    name = folder_name(portfolio_json())
    rename_portfolio_folder(get_current_user_id(), folder_id, name)
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
def home():

    return render_template(
        "index.html", language_labels=LANGUAGE_LABELS,
        catalog_language_labels=CATALOG_LANGUAGE_LABELS
    )


@app.route("/scan", methods=["POST"])
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