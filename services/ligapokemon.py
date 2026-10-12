import html
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests


CARD_CONDITIONS = {"NM", "SP", "MP", "HP", "DM"}


def build_liga_search(name, collector_number=""):
    """Prepara a mesma consulta para o scanner e para a entrada manual."""
    name = name.strip()
    collector_number = collector_number.strip()
    if not name or len(name) > 120 or len(collector_number) > 30:
        raise ValueError("Informe um nome válido e um número de até 30 caracteres.")

    query = f"{name} ({collector_number})" if collector_number else name
    search_url = "https://www.ligapokemon.com.br/?" + urlencode({
        "view": "cards/search",
        "card": query
    })
    # É uma busca externa, não um match confirmado nem uma cotação.
    return {
        "status": "external_search",
        "source": "ligapokemon",
        "query": query,
        "search_url": search_url,
        "price": None
    }


def search_liga_card(name, collector_number, condition):
    if condition not in CARD_CONDITIONS:
        raise ValueError("Selecione NM, SP, MP, HP ou DM.")

    result = build_liga_search(name, collector_number)
    result.update(
        status="unavailable", condition=condition, currency="BRL",
        price_scope="general", checked_at=datetime.now(timezone.utc).isoformat(),
        message="Preço indisponível: não encontramos uma cotação geral confiável."
    )
    # Uma consulta à página da carta; nenhum retry ou navegador automatizado.
    card_url = "https://www.ligapokemon.com.br/?" + urlencode({
        "view": "cards/card", "card": result["query"]
    })
    try:
        response = requests.get(
            card_url, timeout=10, headers={"User-Agent": "TCGHub-MVP/0.1"}
        )
        result["upstream_status"] = response.status_code
        if response.status_code in (403, 429):
            result.update(
                status="blocked",
                message=f"Preço indisponível: a Liga bloqueou a consulta automática (HTTP {response.status_code})."
            )
            return result
        response.raise_for_status()
    except requests.RequestException:
        result["message"] = "Preço indisponível: não foi possível conectar à Liga."
        return result

    # Não extraímos qualquer 'R$' do HTML: pode pertencer a outra carta.
    # O formato cards_editions contém referências gerais, não ofertas
    # filtradas por condição. Se o formato mudar, não há cotação.
    title = re.search(r"<title[^>]*>(.*?)</title>", response.text, re.S | re.I)
    identity = " ".join(html.unescape(title[1]).casefold().split()) if title else ""
    expected_name = " ".join(name.strip().casefold().split())
    number = collector_number.strip().casefold()
    if not number or not re.search(
        rf"(?<!\w){re.escape(expected_name)}(?!\w)", identity
    ) or not re.search(rf"(?<![\w/]){re.escape(number)}(?![\w/])", identity):
        return result

    marker = re.search(r"\b(?:var|let|const)\s+cards_editions\s*=\s*", response.text)
    if not marker:
        return result
    try:
        editions, _ = json.JSONDecoder().raw_decode(response.text[marker.end():])
        # Várias edições exigem confirmação; não escolhemos a primeira.
        if not isinstance(editions, list) or len(editions) != 1:
            return result
        prices = editions[0].get("price", {})
        reference = prices.get("0") if isinstance(prices, dict) else prices[0]
        value = str(reference["p"])
        price = float(value.replace(".", "").replace(",", ".") if "," in value else value)
        if not 0 < price < float("inf"):
            return result
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return result

    result.update(
        status="ok", price=price, source_url=card_url,
        message="Menor preço geral informado pela Liga; sem filtro de condição, idioma ou variante."
    )
    return result