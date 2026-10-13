
import math
import time
from datetime import date

import requests


_exchange_rates = {}


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
    for finish in ("normal", "holo", "reverse"):
        if variant and variant != finish:
            continue
        amount = (tcgplayer.get(finish) or {}).get("marketPrice")
        if amount is not None and tcgplayer.get("unit", "USD") == "USD":
            quotes.append({
                "source": "TCGplayer", "variant": finish,
                "amount": amount, "currency": "USD", "updated_at": tcgplayer.get("updated")
            })

    # Cardmarket não separa reverse de outras variantes nesta referência.
    if not quotes and variant != "reverse":
        cardmarket = pricing.get("cardmarket") or {}
        finishes = [variant] if variant else ["normal", "holo"]
        for finish in finishes:
            field = "trend-holo" if finish == "holo" else "trend"
            amount = cardmarket.get(field)
            if amount is not None and cardmarket.get("unit", "EUR") == "EUR":
                quotes.append({
                    "source": "Cardmarket", "variant": finish,
                    "amount": amount, "currency": "EUR", "updated_at": cardmarket.get("updated")
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

