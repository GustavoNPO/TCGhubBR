import requests


TCGDEX_BASE_URL = "https://api.tcgdex.net/v2"


def get_languages(language):
    if language == "pt-br":
        return ["pt-br", "en"]

    if language == "en":
        return ["en", "pt-br"]

    return ["en", "pt-br"]


def find_card_candidates(card_info):
    if not card_info.name:
        return []

    candidates = []

    for language in get_languages(card_info.language):

        response = requests.get(
            f"{TCGDEX_BASE_URL}/{language}/cards",
            params={
                "name": card_info.name
            },
            timeout=10
        )

        if not response.ok:
            continue

        cards = response.json()

        for card in cards:

            score = 0

            # Nome encontrado pela API.
            if (
                card.get("name", "").lower()
                ==
                card_info.name.lower()
            ):
                score += 50

            # Número da carta é um identificador
            # extremamente importante.
            if (
                card_info.local_id
                and
                str(card.get("localId")) == str(card_info.local_id)
            ):
                score += 50

            candidates.append({
                "id": card.get("id"),
                "name": card.get("name"),
                "local_id": card.get("localId"),
                "image": card.get("image"),
                "language": language,
                "score": score
            })

    candidates.sort(
        key=lambda card: card["score"],
        reverse=True
    )

    return candidates[:5]