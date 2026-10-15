import re
import time
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

import requests


TCGDEX_BASE_URL = "https://api.tcgdex.net/v2"
_catalog_cache = {}
_catalog_lock = Lock()


def _catalog_json(path, params=None, ttl=300):
    key = (path, tuple(sorted((params or {}).items())))
    with _catalog_lock:
        cached = _catalog_cache.get(key)
        if cached and time.monotonic() - cached[0] < ttl:
            return deepcopy(cached[1])
    response = requests.get(f"{TCGDEX_BASE_URL}/{path}", params=params, timeout=8)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    data = response.json()
    with _catalog_lock:
        if len(_catalog_cache) >= 512:
            _catalog_cache.pop(next(iter(_catalog_cache)))
        _catalog_cache[key] = (time.monotonic(), deepcopy(data))
    return data


def is_physical_card(card):
    set_info = card.get("set") or {}
    set_id = set_info.get("id") or str(card.get("id", "")).rsplit("-", 1)[0]
    assets = " ".join(str(value or "") for value in
                      [card.get("image"), card.get("logo"), card.get("symbol"),
                       set_info.get("logo"), set_info.get("symbol")])
    # Pocket tem catálogo/numeração próprios e não é uma carta física cotável.
    return "/tcgp/" not in assets and not re.fullmatch(r"(?:[A-Z]\d+[a-z]?|P-[A-Z])", set_id)


def _search_languages(language):
    # Na API atual, o catálogo físico em português usa 'pt'; 'pt-br'
    # contém sobretudo Pocket. O idioma físico continua sendo pt-br.
    return ["pt", "en"] if language == "auto" else ["pt" if language == "pt-br" else language]


def get_catalog_sets(language="auto"):
    languages = _search_languages(language)
    def load(lang):
        try:
            data = _catalog_json(f"{lang}/sets", ttl=3600)
            if not isinstance(data, list):
                raise ValueError("Resposta inválida de coleções.")
            return lang, data
        except (requests.RequestException, ValueError) as error:
            return lang, error
    with ThreadPoolExecutor(max_workers=len(languages)) as pool:
        responses = list(pool.map(load, languages))
    result = {}
    successes = 0
    for lang, data in responses:
        if isinstance(data, Exception):
            continue
        successes += 1
        for entry in data:
            # O ID aqui já é o da coleção, não o da carta.
            if not is_physical_card({**entry, "set": {"id": entry.get("id")}}):
                continue
            row = result.setdefault(entry["id"], {
                "id": entry["id"], "name": entry["name"], "names": {},
                "official": (entry.get("cardCount") or {}).get("official")
            })
            row["names"][lang] = entry["name"]
    if not successes:
        raise requests.RequestException("Coleções indisponíveis.")
    return list(result.values())

def get_card_details(card_id, language):
    # Apenas a carta confirmada precisa de uma consulta de detalhes.
    card = _catalog_json(f"{language}/cards/{card_id}")
    if card is None:
        return None
    if not isinstance(card, dict) or card.get("id") != card_id or not card.get("name"):
        raise ValueError("Resposta inválida do TCGdex.")
    return card

def search_catalog_cards(name, collector_number, language="auto", set_id=""):
    """Busca manual no catálogo, sem chamar o Gemini."""
    params = {}
    if name:
        params["name"] = name
    if collector_number:
        # Busca parcial na API e igualdade normalizada localmente: evita a
        # diferença entre números JSON e strings/zeros no filtro eq da fonte.
        params["localId"] = normalize_number(collector_number)
    if set_id:
        params["set.id"] = f"eq:{set_id}"
    languages = _search_languages(language)
    def load(lang):
        try:
            data = _catalog_json(f"{lang}/cards", params)
            if not isinstance(data, list):
                raise ValueError("Resposta inválida do catálogo.")
            return lang, data
        except (requests.RequestException, ValueError) as error:
            return lang, error
    with ThreadPoolExecutor(max_workers=len(languages)) as pool:
        responses = list(pool.map(load, languages))
    # Metadados das coleções são pequenos e reutilizados entre buscas.
    try:
        sets = {entry["id"]: entry for entry in get_catalog_sets(language)}
    except (requests.RequestException, ValueError):
        sets = {}
    expected_total = collector_number.split("/", 1)[1].strip().lstrip("0") if "/" in collector_number else None
    result = {}
    successes = 0
    for lang, cards in responses:
        if isinstance(cards, Exception):
            continue
        successes += 1
        for card in cards:
            if not is_physical_card(card):
                continue
            if collector_number and normalize_number(card.get("localId")) != normalize_number(collector_number):
                continue
            card_set = card["id"].rsplit("-", 1)[0]
            if set_id and card_set != set_id:
                continue
            metadata = sets.get(card_set, {})
            if expected_total and str(metadata.get("official")) != expected_total:
                continue
            if card["id"] not in result:
                result[card["id"]] = {
                    "id": card["id"], "name": card["name"],
                    "local_id": card.get("localId"), "image": card.get("image"),
                    "language": lang, "set_id": card_set,
                    "set_name": metadata.get("name", card_set),
                    "set_names": metadata.get("names", {}), "set_total": metadata.get("official")
                }
    if not successes:
        raise requests.RequestException("Catálogo indisponível.")
    wanted = normalize_name(name)
    # Nome exato primeiro, depois o que começa pelo termo digitado.
    return sorted(result.values(), key=lambda row: (
        normalize_name(row["name"]) != wanted,
        not normalize_name(row["name"]).startswith(wanted), not bool(row.get("image"))
    ))

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
                "pt" if card_info.language == "pt-br" else card_info.language,
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

            if not is_physical_card(card):
                continue

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