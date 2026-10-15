
import math
import time
from datetime import date

import requests


_exchange_rates = {}
PRICING_VERSION = 3


def _positive_amount(value):
    try:
        amount = float(value)
        return amount if not isinstance(value, bool) and math.isfinite(amount) and amount > 0 else None
    except (TypeError, ValueError):
        return None


def get_brl_rate(currency):
    """Reutiliza o câmbio por uma hora, com a data informada pela fonte."""
    cached = _exchange_rates.get(currency)
    if cached and time.monotonic() - cached[0] < 3600:
        return cached[1]
    response = requests.get(
        f"https://api.frankfurter.dev/v2/rate/{currency.lower()}/brl", timeout=4
    )
    response.raise_for_status()
    data = response.json()
    rate = float(data["rate"])
    rate_date = date.fromisoformat(data["date"]).isoformat()
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("Câmbio inválido.")
    result = {"rate": rate, "date": rate_date, "source": "Frankfurter"}
    _exchange_rates[currency] = (time.monotonic(), result)
    return result


def get_catalog_prices(card, variant=""):
    """Referências internacionais por variante, sem desconto por conservação."""
    pricing = card.get("pricing") or {}
    quotes = []
    tcgplayer = pricing.get("tcgplayer") or {}
    variants = card.get("variants") or {}
    provider_finishes = {"normal": ("normal",), "holo": ("holofoil", "holo"),
                         "reverse": ("reverse-holofoil", "reverse")}
    for finish in ("normal", "holo", "reverse"):
        if (variant and variant != finish) or variants.get(finish) is False:
            continue
        reference = next((tcgplayer[key] for key in provider_finishes[finish]
                          if isinstance(tcgplayer.get(key), dict)), {})
        amount = _positive_amount(reference.get("marketPrice"))
        if amount and tcgplayer.get("unit", "USD") == "USD":
            quotes.append({
                "source": "TCGplayer", "variant": finish,
                "amount": amount, "currency": "USD", "updated_at": tcgplayer.get("updated"),
                "price_type": "market", "product_id": reference.get("productId"),
                "price_scope": "international_reference", "physical_language_matched": False,
                "condition_matched": False
            })
        # O trend geral não identifica uma reverse. Cada variante tem seu
        # fallback próprio, sem substituir uma holo por preço de carta normal.
        elif finish != "reverse":
            cardmarket = pricing.get("cardmarket") or {}
            field = "trend-holo" if finish == "holo" else "trend"
            amount = _positive_amount(cardmarket.get(field))
            if amount and cardmarket.get("unit", "EUR") == "EUR":
                quotes.append({
                    "source": "Cardmarket", "variant": finish,
                    "amount": amount, "currency": "EUR", "updated_at": cardmarket.get("updated"),
                    "price_type": "trend", "product_id": cardmarket.get("idProduct"),
                    "price_scope": "international_reference", "physical_language_matched": False,
                    "condition_matched": False
                })

    valid_quotes = []
    exchanges = {}
    for quote in quotes:
        try:
            amount = float(quote["amount"])
            if not math.isfinite(amount) or amount <= 0:
                continue
        except (TypeError, ValueError):
            continue
        quote.update(amount=amount, estimated_brl=None, exchange_rate=None)
        currency = quote["currency"]
        if currency not in exchanges:
            try:
                exchanges[currency] = get_brl_rate(currency)
            except (requests.RequestException, ValueError, KeyError, TypeError):
                exchanges[currency] = None
        exchange = exchanges[currency]
        if exchange:
            quote.update(
                estimated_brl=round(amount * exchange["rate"], 2), exchange_rate=exchange
            )
        # O valor original continua disponível se a conversão falhar.
        valid_quotes.append(quote)
    return valid_quotes


def get_international_prices(card, variant="", catalog_language="en"):
    quotes = get_catalog_prices(card, variant)
    if not quotes and catalog_language != "en":
        from services.tcgdex import get_card_details
        try:
            english = get_card_details(card["id"], "en")
            if english:
                quotes = get_catalog_prices(english, variant)
        except (requests.RequestException, ValueError):
            pass
    return quotes