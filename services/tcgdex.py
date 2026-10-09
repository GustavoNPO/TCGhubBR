import requests


TCGDEX_BASE_URL = "https://api.tcgdex.net/v2"


def normalize_number(value):

    if not value:
        return None

    value = str(value)

    # Caso venha algo como 025/165
    value = value.split("/")[0]

    # 025 e 25 devem ser considerados iguais
    value = value.lstrip("0")

    return value or "0"


def normalize_name(value):

    if not value:
        return ""

    return value.strip().casefold()


def build_search_attempts(card_info):

    attempts = []

    # Primeiro tentamos exatamente o idioma
    # e o nome impresso na carta.

    if (
        card_info.language != "unknown"
        and card_info.printed_name
    ):

        attempts.append(
            (
                card_info.language,
                card_info.printed_name
            )
        )


    # Se o Gemini conseguiu nos dar um
    # nome canônico em inglês, usamos como fallback.

    if card_info.search_name:

        attempts.append(
            (
                "en",
                card_info.search_name
            )
        )


    # Remove tentativas duplicadas.

    unique_attempts = []

    for attempt in attempts:

        if attempt not in unique_attempts:
            unique_attempts.append(attempt)

    return unique_attempts


def find_card_candidates(card_info):

    attempts = build_search_attempts(
        card_info
    )

    candidates_by_id = {}


    for language, search_name in attempts:

        print(
            f"TCGdex -> idioma={language} "
            f"nome={search_name}"
        )

        try:

            response = requests.get(
                f"{TCGDEX_BASE_URL}/{language}/cards",
                params={
                    "name": search_name
                },
                timeout=8
            )

        except requests.RequestException as error:

            print(
                "Erro TCGdex:",
                error
            )

            continue


        if not response.ok:

            print(
                "TCGdex respondeu:",
                response.status_code
            )

            continue


        cards = response.json()


        for card in cards:

            score = 0


            api_name = normalize_name(
                card.get("name")
            )

            printed_name = normalize_name(
                card_info.printed_name
            )

            search_name_normalized = normalize_name(
                card_info.search_name
            )


            # Nome exato no mesmo idioma.

            if (
                printed_name
                and
                api_name == printed_name
            ):
                score += 40


            # Nome canônico em inglês.

            elif (
                search_name_normalized
                and
                api_name == search_name_normalized
            ):
                score += 35


            api_number = normalize_number(
                card.get("localId")
            )

            detected_number = normalize_number(
                card_info.local_id
            )


            # Número da carta tem bastante peso.

            if (
                detected_number
                and
                api_number == detected_number
            ):
                score += 60


            candidate = {
                "id": card.get("id"),
                "name": card.get("name"),
                "local_id": card.get("localId"),
                "image": card.get("image"),
                "language": language,
                "score": score
            }


            card_id = candidate["id"]

            previous = candidates_by_id.get(
                card_id
            )


            # Podemos achar a mesma carta
            # através de mais de um idioma.
            # Mantemos o match de maior score.

            if (
                previous is None
                or
                candidate["score"] > previous["score"]
            ):
                candidates_by_id[card_id] = candidate


    candidates = list(
        candidates_by_id.values()
    )


    candidates.sort(
        key=lambda card: card["score"],
        reverse=True
    )


    return candidates

def select_best_candidates(
    candidates,
    scan_confidence
):

    if not candidates:
        return []


    # Gemini não conseguiu ler a carta
    # com confiança suficiente.

    if scan_confidence < 0.55:
        return []


    candidates.sort(
        key=lambda card: card["score"],
        reverse=True
    )


    best_score = candidates[0]["score"]


    # Mesmo o melhor candidato foi fraco.

    if best_score < 55:
        return []


    # Scanner muito confiante +
    # match muito forte:
    # mostramos somente duas.

    if (
        scan_confidence >= 0.85
        and
        best_score >= 85
    ):
        limit = 2

    else:
        limit = 3


    # Não faz sentido mostrar candidatos
    # muito piores que o primeiro.

    minimum_score = max(
        55,
        best_score - 20
    )


    filtered = [
        card
        for card in candidates
        if card["score"] >= minimum_score
    ]


    return filtered[:limit]