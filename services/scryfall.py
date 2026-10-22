"""Catálogo de Magic: The Gathering via Scryfall.

A API do Scryfall é pública e não pede chave, mas exige User-Agent e Accept
identificados e pede no máximo ~10 requisições/s (buscas têm limite menor).
O MTGJSON publica os mesmos dados como arquivos diários de centenas de MB:
bons para carga em lote, não para consultar a cada foto. Os IDs do Scryfall
também aparecem no MTGJSON, então uma integração futura continua compatível.
"""
import re
import time
from copy import deepcopy
from threading import Lock
from urllib.parse import quote

import requests

from services.tcgdex import normalize_name, normalize_number


SCRYFALL_BASE_URL = "https://api.scryfall.com"
SCRYFALL_HEADERS = {"User-Agent": "TCGHubBR/1.0", "Accept": "application/json"}
MTG_FINISHES = ("nonfoil", "foil", "etched")
# Idioma do TCG Hub → idioma do Scryfall. O inverso define o catalog_language salvo.
SCRYFALL_LANGUAGES = {
    "en": "en", "pt-br": "pt", "pt": "pt", "es": "es", "fr": "fr", "de": "de", "it": "it",
    "ja": "ja", "ko": "ko", "ru": "ru", "zh-cn": "zhs", "zh-tw": "zht"
}
CATALOG_FROM_SCRYFALL = {"en": "en", "pt": "pt", "es": "es", "fr": "fr", "de": "de", "it": "it",
                         "ja": "ja", "ko": "ko", "ru": "ru", "zhs": "zh-cn", "zht": "zh-tw"}
CARD_ID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SET_CODE_PATTERN = re.compile(r"[a-z0-9]{2,6}")
NUMBER_PATTERN = re.compile(r"[a-z0-9-]{1,12}")
# Coleções sem cartas físicas colecionáveis comuns.
SKIPPED_SET_TYPES = {"token", "memorabilia", "minigame", "alchemy", "treasure_chest", "vanguard"}

_cache = {}
_cache_lock = Lock()
_throttle_lock = Lock()
_last_request = 0.0


def _scryfall_json(path, params=None, ttl=300):
    global _last_request
    key = (path, tuple(sorted((params or {}).items())))
    with _cache_lock:
        cached = _cache.get(key)
        if cached and time.monotonic() - cached[0] < ttl:
            return deepcopy(cached[1])
    # Buscas têm limite menor que consultas diretas por ID.
    interval = 0.5 if path.startswith(("cards/search", "cards/named")) else 0.1
    with _throttle_lock:
        wait = _last_request + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
    response = requests.get(f"{SCRYFALL_BASE_URL}/{path}", params=params,
                            headers=SCRYFALL_HEADERS, timeout=8)
    # Busca sem resultado também responde 404.
    if response.status_code == 404:
        return None
    response.raise_for_status()
    data = response.json()
    with _cache_lock:
        if len(_cache) >= 512:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (time.monotonic(), deepcopy(data))
    return data


def clean_set_code(value):
    value = str(value or "").strip().lower()
    return value if SET_CODE_PATTERN.fullmatch(value) else ""


def clean_number(value):
    """'0149/249 C' e '149' são o mesmo número no Scryfall; 'CLB-187' é mantido."""
    value = str(value or "").strip().split()[0].lower() if str(value or "").strip() else ""
    value = normalize_number(value) or ""
    return value if NUMBER_PATTERN.fullmatch(value) else ""


def is_paper_card(card):
    return isinstance(card, dict) and "paper" in (card.get("games") or []) and not card.get("digital")


def english_name(card):
    """Nome da face da frente em inglês: é como a Liga Magic e o TCGplayer indexam."""
    return str(card.get("name") or "").split(" // ")[0]


def printed_name(card):
    if card.get("printed_name"):
        return card["printed_name"]
    faces = [face.get("printed_name") for face in card.get("card_faces") or []]
    return " // ".join(faces) if faces and all(faces) else card.get("name")


def card_images(card):
    # "small" (146 px) fica borrado na grade; "normal" (488 px) equivale ao low.webp do TCGdex.
    images = card.get("image_uris") or ((card.get("card_faces") or [{}])[0].get("image_uris")) or {}
    return images.get("normal") or images.get("small"), images.get("large") or images.get("normal")


def catalog_language(card):
    return CATALOG_FROM_SCRYFALL.get(card.get("lang"))


def card_finishes(card):
    finishes = set(card.get("finishes") or [])
    return {finish: finish in finishes for finish in MTG_FINISHES}


def card_row(card, score=None):
    thumb, image = card_images(card)
    row = {
        "id": card["id"], "game": "magic", "name": printed_name(card),
        "english_name": english_name(card), "local_id": card.get("collector_number"),
        "image": None, "thumb_url": thumb, "image_url": image,
        "language": catalog_language(card), "set_id": card.get("set"),
        "set_name": card.get("set_name"), "set_names": {}, "set_total": None
    }
    if score is not None:
        row["score"] = score
    return row


def get_mtg_card(card_id):
    if not isinstance(card_id, str) or not CARD_ID_PATTERN.fullmatch(card_id):
        return None
    card = _scryfall_json(f"cards/{card_id}")
    if card is None:
        return None
    if not isinstance(card, dict) or card.get("id") != card_id or not card.get("name"):
        raise ValueError("Resposta inválida do Scryfall.")
    return card


def get_mtg_print(set_code, number, language="en"):
    """Uma impressão exata: coleção + número (+ idioma)."""
    set_code, number = clean_set_code(set_code), clean_number(number)
    if not set_code or not number:
        return None
    lang = SCRYFALL_LANGUAGES.get(language, "en")
    path = f"cards/{quote(set_code)}/{quote(number)}" + ("" if lang == "en" else f"/{lang}")
    card = _scryfall_json(path)
    return card if isinstance(card, dict) and card.get("object") == "card" else None


def get_mtg_sets():
    data = _scryfall_json("sets", ttl=3600)
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise ValueError("Resposta inválida de coleções.")
    return [
        {"id": entry["code"], "name": entry["name"], "names": {"en": entry["name"]}, "official": None}
        for entry in data["data"]
        if not entry.get("digital") and entry.get("set_type") not in SKIPPED_SET_TYPES and entry.get("card_count")
    ]


def _search(query, order="released"):
    data = _scryfall_json("cards/search", {"q": f"{query} game:paper", "unique": "prints",
                                           "order": order, "dir": "desc"})
    if data is None:
        return []
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise ValueError("Resposta inválida do catálogo.")
    return [card for card in data["data"] if is_paper_card(card) and catalog_language(card)]


def _name_term(name):
    # Aspas viram uma frase no nome; o restante da sintaxe do Scryfall é neutralizado.
    name = re.sub(r'["\\]', "", name).strip()
    return f'"{name}"' if name else ""


def _language_term(language):
    if language == "auto":
        return "(lang:pt or lang:en)"
    lang = SCRYFALL_LANGUAGES.get(language)
    if not lang:
        raise ValueError("Idioma inválido.")
    return f"lang:{lang}"


def search_mtg_cards(name, collector_number, language="auto", set_code=""):
    """Busca manual no catálogo, sem chamar o Gemini. Retorna a primeira página do Scryfall."""
    terms = [_name_term(name) if name else ""]
    number = clean_number(collector_number)
    if collector_number and not number:
        return []
    if number:
        terms.append(f"cn:{number}")
    if set_code:
        terms.append(f"e:{clean_set_code(set_code)}")
    terms.append(_language_term(language))
    cards = _search(" ".join(term for term in terms if term))
    wanted = normalize_name(name)
    rows = [card_row(card) for card in cards]
    # Nome exato primeiro, depois o que começa pelo termo; a ordem do Scryfall (mais recente) desempata.
    return sorted(rows, key=lambda row: (
        wanted not in (normalize_name(row["name"]), normalize_name(row["english_name"])),
        not (normalize_name(row["name"]).startswith(wanted) or normalize_name(row["english_name"]).startswith(wanted)),
        not bool(row.get("image_url"))
    ))


def _score(card, card_info, set_code, number):
    score = 0
    names = {normalize_name(printed_name(card)), normalize_name(english_name(card)), normalize_name(card.get("name"))}
    if card_info.printed_name and normalize_name(card_info.printed_name) in names:
        score += 40
    elif card_info.search_name and normalize_name(card_info.search_name) in names:
        score += 35
    if number and clean_number(card.get("collector_number")) == number:
        score += 60
    if set_code and card.get("set") == set_code:
        score += 30
    # Mesma impressão em outro idioma continua como opção, logo abaixo.
    if SCRYFALL_LANGUAGES.get(card_info.language) == card.get("lang"):
        score += 5
    return score


def find_mtg_candidates(card_info):
    """Candidatos a partir do que o Gemini leu na foto, com o mesmo score do TCGdex."""
    set_code = clean_set_code(getattr(card_info, "set_code", None))
    number = clean_number(card_info.collector_number or card_info.local_id)
    language = card_info.language if card_info.language in SCRYFALL_LANGUAGES else "en"
    found = {}

    def add(cards):
        for card in cards:
            if not is_paper_card(card) or not catalog_language(card):
                continue
            score = _score(card, card_info, set_code, number)
            if card["id"] not in found or score > found[card["id"]]["score"]:
                found[card["id"]] = card_row(card, score)

    attempts = []
    # Coleção + número impressos identificam a impressão sem depender do nome.
    if set_code and number:
        attempts.append(lambda: [card for card in (get_mtg_print(set_code, number, language),
                                                   get_mtg_print(set_code, number, "en")) if card])
    if card_info.printed_name:
        terms = [_name_term(card_info.printed_name), f"lang:{SCRYFALL_LANGUAGES[language]}"]
        attempts.append(lambda: _search(" ".join(terms + ([f"cn:{number}"] if number else []))))
    if card_info.search_name:
        attempts.append(lambda: _search(" ".join([f'!{_name_term(card_info.search_name)}', "lang:en"]
                                                 + ([f"e:{set_code}"] if set_code else []))))
    for attempt in attempts:
        try:
            add(attempt())
        except (requests.RequestException, ValueError) as error:
            print("Erro Scryfall:", error)
        # Uma impressão exata e confiável dispensa as buscas por nome.
        if found and max(row["score"] for row in found.values()) >= 90:
            break
    return sorted(found.values(), key=lambda row: row["score"], reverse=True)