"""Link para conferir a carta na Liga Pokémon.

A Liga bloqueia consultas automáticas (Cloudflare/HTTP 403), então o TCGHub
não lê preços de lá. Montamos um link que a própria Liga resolve para a carta:
"(025/165) ed=MEW" filtra edição e número e abre direto a página da carta
quando há uma só correspondência. Sem o código da edição, o link é uma busca
por nome e número e a interface pede para conferir a edição.
"""
import re
from urllib.parse import urlencode

from services.liga_editions import LIGA_EDITIONS, LIGA_PROMO_SETS


CARD_CONDITIONS = {"NM", "SP", "MP", "HP", "DM"}
LIGA_URL = "https://www.ligapokemon.com.br/"


def liga_number(set_id, local_id, official):
    """Numeração impressa no formato da Liga: 025/165, TG08/TG30, 085/∞."""
    local_id = str(local_id or "").strip()
    if not local_id:
        return None
    if set_id in LIGA_PROMO_SETS:
        return f"{local_id}/∞"
    if not official:
        return None
    # Subconjuntos repetem o prefixo no total: TG08/TG30, GG01/GG70, SV107/SV122.
    prefix = re.match(r"[A-Za-z]*", local_id)[0]
    return f"{local_id}/{prefix}{official}"


def liga_link(set_id, local_id, official, name):
    code = LIGA_EDITIONS.get(set_id or "")
    number = liga_number(set_id, local_id, official)
    if code and number:
        query, exact = f"({number}) ed={code}", True
    else:
        query, exact = (f"{name} ({number})" if number else name), False
    return {
        "url": LIGA_URL + "?" + urlencode({"view": "cards/search", "card": query}),
        "exact": exact, "edition_code": code, "number": number, "query": query
    }


def liga_link_for_card(card):
    """Link a partir dos detalhes confirmados no TCGdex."""
    set_info = card.get("set") or {}
    set_id = set_info.get("id") or str(card.get("id", "")).rsplit("-", 1)[0]
    official = (set_info.get("cardCount") or {}).get("official")
    return liga_link(set_id, card.get("localId"), official, card.get("name", ""))