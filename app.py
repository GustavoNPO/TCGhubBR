from flask import Flask, jsonify, render_template, request

from services.vision import extract_card_info

from services.tcgdex import (
    find_card_candidates,
    select_best_candidates
)


app = Flask(__name__)


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