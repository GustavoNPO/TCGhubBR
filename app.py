import os
import re

import requests
from flask import Flask, jsonify, render_template, request, url_for

from services.vision import extract_card_info

from services.tcgdex import (
    find_card_candidates,
    select_best_candidates,
    get_card_details
)
from services.portfolio import add_portfolio_card, list_portfolio_cards
from services.firebase import FirebaseUnavailable


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
        cards = list_portfolio_cards(get_current_user_id())
    except FirebaseUnavailable as error:
        return render_template(
            "portfolio.html", cards=[], error=str(error),
            language_labels=LANGUAGE_LABELS
        ), 503
    except Exception:
        app.logger.exception("Erro ao carregar portfolio")
        return render_template(
            "portfolio.html", cards=[],
            error="Não foi possível carregar seu inventário. Tente novamente.",
            language_labels=LANGUAGE_LABELS
        ), 503

    return render_template(
        "portfolio.html", cards=cards, error=None,
        language_labels=LANGUAGE_LABELS
    )


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

    if (
        not isinstance(external_id, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", external_id)
        or not isinstance(language, str) or language not in CARD_LANGUAGES
        or not isinstance(catalog_language, str)
        or catalog_language not in CARD_LANGUAGES - {"unknown"}
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

        image = card.get("image")
        item = {
            "game": "pokemon",
            "provider": "tcgdex",
            "external_id": card["id"],
            "name": card["name"],
            "collector_number": (collector_number or "").strip() or card.get("localId"),
            "set_name": card.get("set", {}).get("name"),
            "image_url": f"{image}/high.webp" if image else None,
            "language": language,
            "catalog_language": catalog_language,
            "condition": None,
            "variant": None,
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

    return render_template("index.html")


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