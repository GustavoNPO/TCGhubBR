
"""Consulta de mercado independente das operações de inventário."""
from datetime import datetime, timezone

import requests

from services.ligamagic import liga_magic_link, liga_magic_link_for_card
from services.ligapokemon import liga_link, liga_link_for_card
from services.pricing import get_international_prices, get_mtg_international_prices, PRICING_VERSION
from services.scryfall import get_mtg_card
from services.tcgdex import get_card_details

PRICE_MESSAGE = "Referência do exterior. A conversão não confirma o valor da carta no Brasil, seu idioma ou conservação."


def prices_are_fresh(prices):
    try:
        if prices.get("pricing_version") != PRICING_VERSION:
            return False
        checked = datetime.fromisoformat(prices["checked_at"])
        return 0 <= (datetime.now(timezone.utc) - checked).total_seconds() < 3600
    except (ValueError, TypeError, KeyError):
        return False


def get_market_prices(item, force=False):
    if item.get("game") == "magic":
        return _mtg_market_prices(item)
    quotes = []
    catalog_message = "Referência internacional indisponível."
    card = None
    if item.get("game") == "pokemon" and item.get("provider") == "tcgdex":
        try:
            card = get_card_details(item["external_id"], item["catalog_language"])
            if card:
                quotes = get_international_prices(card, item.get("variant") or "", item["catalog_language"])
            catalog_message = PRICE_MESSAGE if quotes else "Preço internacional indisponível para esta carta/variante."
        except (requests.RequestException, ValueError, KeyError, TypeError):
            pass

    # A Liga é conferida por link; o número completo vem dos dados confirmados no cadastro.
    if card:
        liga = liga_link_for_card(card)
    else:
        local_id = str(item.get("collector_number") or "").split("/")[0]
        liga = liga_link(item.get("set_id"), local_id, item.get("set_total"), item["name"])
    return _result(quotes, catalog_message, liga)


def _mtg_market_prices(item):
    quotes = []
    catalog_message = "Referência internacional indisponível."
    card = None
    if item.get("provider") == "scryfall":
        try:
            card = get_mtg_card(item["external_id"])
            if card:
                quotes = get_mtg_international_prices(card, item.get("variant") or "")
            catalog_message = PRICE_MESSAGE if quotes else "Preço internacional indisponível para esta carta/acabamento."
        except (requests.RequestException, ValueError, KeyError, TypeError):
            pass
    liga = liga_magic_link_for_card(card) if card else liga_magic_link(
        item.get("english_name") or item["name"], item.get("set_id"), item.get("collector_number"))
    return _result(quotes, catalog_message, liga)


def _result(quotes, catalog_message, liga):
    return {
        "status": "ok" if quotes else "unavailable",
        "quotes": quotes, "catalog_message": catalog_message, "liga": liga,
        "pricing_version": PRICING_VERSION,
        "checked_at": datetime.now(timezone.utc).isoformat()
    }
