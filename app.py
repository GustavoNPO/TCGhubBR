from flask import Flask, jsonify, render_template, request

from services.tcgdex import find_card_candidates
from services.vision import extract_card_info


app = Flask(__name__)


# Impede uploads gigantes.
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

    image = request.files.get("card")

    if not image:
        return jsonify({
            "error": "Nenhuma imagem enviada."
        }), 400

    if image.mimetype not in ALLOWED_IMAGE_TYPES:
        return jsonify({
            "error": "Formato de imagem não suportado."
        }), 400

    image_bytes = image.read()

    try:
        card_info = extract_card_info(
            image_bytes
        )

        candidates = find_card_candidates(
            card_info
        )

    except Exception as error:

        print(error)

        return jsonify({
            "error": "Não foi possível analisar a carta."
        }), 500

    return jsonify({
        "detected": card_info.model_dump(),
        "candidates": candidates
    })


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )