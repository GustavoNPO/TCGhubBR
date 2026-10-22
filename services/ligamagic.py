"""Link para conferir a carta na Liga Magic.

Como a Liga Pokémon, a Liga Magic bloqueia consultas automáticas (HTTP 403),
então só montamos o link. A página da carta lista todas as edições; a
interface informa a edição e o número para o usuário escolher a cópia certa.
"""
from urllib.parse import urlencode


LIGA_MAGIC_URL = "https://www.ligamagic.com.br/"


def liga_magic_link(english_name, set_code, number):
    name = str(english_name or "").split(" // ")[0]
    edition = str(set_code or "").upper() or None
    details = " · ".join(part for part in (f"edição {edition}" if edition else "", f"nº {number}" if number else "") if part)
    return {
        "url": LIGA_MAGIC_URL + "?" + urlencode({"view": "cards/card", "card": name}),
        "exact": False, "edition_code": edition, "number": number, "query": name,
        "label": "Conferir preço na Liga Magic",
        "note": f"Abre a carta na Liga Magic. Escolha a sua impressão na lista{': ' + details if details else ''}."
    }


def liga_magic_link_for_card(card):
    """Link a partir dos detalhes confirmados no Scryfall."""