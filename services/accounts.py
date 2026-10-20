"""Contas, perfis e identidade pública.

Estrutura no Firestore (o servidor grava; o navegador nunca escolhe o dono):
- users/{uid}                 dados privados da conta (e-mail, último acesso, next_position)
- users/{uid}/cards|folders   inventário, como antes
- profiles/{uid}              perfil público: handle, nome, bio, visibilidade
- handles/{handle}            reserva única do @handle -> {uid}

O uid do Firebase Authentication é o identificador estável para o chat e
o compartilhamento; o handle é só o endereço legível (/u/<handle>) e pode mudar.
"""
import re
import secrets
import unicodedata

from services.firebase import get_firestore_client


HANDLE_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9_]{1,22}[a-z0-9])")
RESERVED_HANDLES = {
    "admin", "api", "app", "entrar", "sair", "perfil", "portfolio", "u", "static",
    "suporte", "ajuda", "tcghub", "tcg", "demo", "demo_user", "sistema", "moderacao"
}
VISIBILITY = {"private", "public"}
PROFILE_FIELDS = {"display_name", "handle", "bio", "profile_visibility", "portfolio_visibility"}


class AccountError(ValueError):
    pass


def slugify_handle(value):
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text[:24].strip("_")


def validate_handle(handle):
    handle = str(handle or "").strip().lower().lstrip("@")
    if not HANDLE_PATTERN.fullmatch(handle):
        raise AccountError("Use de 3 a 24 caracteres: letras minúsculas, números e _ (sem começar ou terminar com _).")
    if handle in RESERVED_HANDLES:
        raise AccountError("Este @ é reservado. Escolha outro.")
    return handle


def handle_candidates(display_name, email, uid):
    """Sugestões em ordem: nome, parte local do e-mail e variações com sufixo."""
    bases = [slugify_handle(display_name), slugify_handle((email or "").split("@")[0])]
    seen = []
    for base in bases:
        base = base[:20].strip("_")
        if len(base) < 3 or base in RESERVED_HANDLES or not HANDLE_PATTERN.fullmatch(base):
            continue
        for candidate in (base, f"{base}_{uid[:4].lower()}", f"{base}_{secrets.token_hex(2)}"):
            if candidate not in seen and HANDLE_PATTERN.fullmatch(candidate):
                seen.append(candidate)
    seen.append(f"colecionador_{secrets.token_hex(3)}")
    return seen


def clean_profile_update(data):
    """Valida os campos editáveis do perfil; ignora nada silenciosamente."""
    if not isinstance(data, dict) or not data or set(data) - PROFILE_FIELDS:
        raise AccountError("Campos de perfil inválidos.")
    update = {}
    if "display_name" in data:
        name = data["display_name"]
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
            raise AccountError("Informe um nome de exibição com até 60 caracteres.")
        update["display_name"] = " ".join(name.split())
    if "handle" in data:
        update["handle"] = validate_handle(data["handle"])
    if "bio" in data:
        bio = data["bio"]
        if not isinstance(bio, str) or len(bio) > 280:
            raise AccountError("A bio pode ter até 280 caracteres.")
        update["bio"] = bio.strip()
    for field in ("profile_visibility", "portfolio_visibility"):
        if field in data:
            if data[field] not in VISIBILITY:
                raise AccountError("Visibilidade inválida.")
            update[field] = data[field]
    return update


def ensure_account(claims):
    """Cria conta e perfil no primeiro login; atualiza o último acesso nos seguintes."""
    from firebase_admin import firestore

    db = get_firestore_client()
    uid = claims["uid"]
    user_ref = db.collection("users").document(uid)
    profile_ref = db.collection("profiles").document(uid)
    candidates = handle_candidates(claims.get("name"), claims.get("email"), uid)

    @firestore.transactional
    def save(transaction):
        profile = profile_ref.get(transaction=transaction)
        handle = None
        if not profile.exists:
            # Leituras antes das escritas: procura o primeiro @ livre.
            for candidate in candidates:
                if not db.collection("handles").document(candidate).get(transaction=transaction).exists:
                    handle = candidate
                    break
            if handle is None:
                raise AccountError("Não foi possível reservar um @. Tente novamente.")
        account = {
            "email": claims.get("email"), "email_verified": bool(claims.get("email_verified")),
            "sign_in_provider": (claims.get("firebase") or {}).get("sign_in_provider"),
            "last_login_at": firestore.SERVER_TIMESTAMP
        }
        if handle:
            account["created_at"] = firestore.SERVER_TIMESTAMP
        # Uma escrita por documento na transação.
        transaction.set(user_ref, account, merge=True)
        if handle:
            transaction.set(db.collection("handles").document(handle), {"uid": uid})
            transaction.set(profile_ref, {
                "uid": uid, "handle": handle,
                "display_name": (claims.get("name") or handle)[:60], "bio": "",
                "avatar_url": claims.get("picture"),
                # Privado por padrão: a pessoa decide o que mostrar.
                "profile_visibility": "private", "portfolio_visibility": "private",
                "created_at": firestore.SERVER_TIMESTAMP, "updated_at": firestore.SERVER_TIMESTAMP
            })

    save(db.transaction())
    return get_profile(uid)


def get_profile(uid):
    snapshot = get_firestore_client().collection("profiles").document(uid).get()
    return {**snapshot.to_dict(), "uid": uid} if snapshot.exists else None


def update_profile(uid, update):
    """Atualiza o perfil; trocar o @ libera o anterior na mesma transação."""
    from firebase_admin import firestore

    db = get_firestore_client()
    profile_ref = db.collection("profiles").document(uid)

    @firestore.transactional
    def save(transaction):
        profile = profile_ref.get(transaction=transaction)
        if not profile.exists:
            raise AccountError("Perfil não encontrado. Entre novamente.")
        current = profile.to_dict()
        new_handle = update.get("handle")
        if new_handle and new_handle != current.get("handle"):
            owner = db.collection("handles").document(new_handle).get(transaction=transaction)
            if owner.exists and owner.to_dict().get("uid") != uid:
                raise AccountError("Este @ já está em uso.")
            transaction.set(db.collection("handles").document(new_handle), {"uid": uid})
            if current.get("handle"):
                transaction.delete(db.collection("handles").document(current["handle"]))
        transaction.update(profile_ref, {**update, "updated_at": firestore.SERVER_TIMESTAMP})

    save(db.transaction())
    return get_profile(uid)


def find_profile_by_handle(handle):
    try:
        handle = validate_handle(handle)
    except AccountError:
        return None
    db = get_firestore_client()
    owner = db.collection("handles").document(handle).get()
    if not owner.exists:
        return None
    return get_profile(owner.to_dict()["uid"])


def public_view(profile, cards, folders, viewer_uid=None):
    """O que um visitante pode ver: perfil público e cartas do portfólio ou de pastas públicas.

    O dono sempre vê a própria página como os outros a veem, mais um aviso
    quando está privada. Pastas com visibility "public" ficam visíveis mesmo
    com o portfólio privado: é a base para compartilhar uma coleção específica.
    """
    if not profile:
        return None
    owner = viewer_uid == profile["uid"]
    if profile.get("profile_visibility") != "public" and not owner:
        return None
    public_folders = [folder for folder in folders if folder.get("visibility") == "public"]
    if profile.get("portfolio_visibility") == "public":
        visible = cards
    else:
        ids = {folder["id"] for folder in public_folders}
        visible = [card for card in cards if card.get("folder_id") in ids]
    fields = ("id", "name", "set_name", "collector_number", "image_url", "variant", "language",
              "condition", "folder_id", "for_trade", "for_sale")
    return {
        "profile": {key: profile.get(key) for key in ("uid", "handle", "display_name", "bio", "avatar_url",
                                                       "profile_visibility", "portfolio_visibility", "created_at")},
        "cards": [{key: card.get(key) for key in fields} for card in visible],
        "folders": [{"id": folder["id"], "name": folder["name"]} for folder in public_folders],
        "is_owner": owner
    }


def plan_legacy_claim(source_cards, source_folders, target_next_position, target_card_ids=(), target_folder_ids=()):
    """Plano puro para copiar o inventário do demo-user para uma conta real.

    IDs de cartas e pastas são preservados (folder_id continua válido). As
    posições são deslocadas para depois das cartas que a conta já tem.
    """
    clashes = {card["id"] for card in source_cards} & set(target_card_ids)
    clashes |= {folder["id"] for folder in source_folders} & set(target_folder_ids)
    if clashes:
        raise AccountError(f"IDs já existentes na conta de destino: {sorted(clashes)[:5]}")
    ordered = sorted(source_cards, key=lambda card: card.get("position", 0))
    cards = []
    for offset, card in enumerate(ordered):
        data = {key: value for key, value in card.items() if key != "id"}
        cards.append((card["id"], {**data, "position": target_next_position + offset}))
    folders = [(folder["id"], {key: value for key, value in folder.items() if key != "id"}) for folder in source_folders]
    return {"cards": cards, "folders": folders, "next_position": target_next_position + len(cards)}


def claim_legacy_portfolio(source_uid, target_uid, apply=False):
    """Copia users/{source}/cards e folders para users/{target} e marca a origem como migrada."""
    from firebase_admin import firestore

    if source_uid == target_uid:
        raise AccountError("Origem e destino são a mesma conta.")
    db = get_firestore_client()
    source = db.collection("users").document(source_uid)
    target = db.collection("users").document(target_uid)
    source_data = source.get().to_dict() or {}
    if source_data.get("migrated_to"):
        raise AccountError(f"{source_uid} já foi vinculado a {source_data['migrated_to']}.")
    if not db.collection("profiles").document(target_uid).get().exists:
        raise AccountError("A conta de destino ainda não entrou no TCG Hub. Faça o primeiro login antes.")
    read = lambda ref, name: [{**doc.to_dict(), "id": doc.id} for doc in ref.collection(name).stream()]
    target_data = target.get().to_dict() or {}
    existing_cards = {doc.id for doc in target.collection("cards").stream()}
    existing_folders = {doc.id for doc in target.collection("folders").stream()}
    # Uma cópia interrompida pode ser retomada: os itens já copiados são pulados.
    resuming = target_data.get("claim_in_progress") == source_uid
    plan = plan_legacy_claim(
        read(source, "cards"), read(source, "folders"), target_data.get("next_position", 0),
        () if resuming else existing_cards, () if resuming else existing_folders
    )
    summary = {"cards": len(plan["cards"]), "folders": len(plan["folders"]), "applied": apply, "resumed": resuming}
    if not apply:
        return summary
    target.set({"claim_in_progress": source_uid}, merge=True)
    writes = [(target.collection("folders").document(id), data) for id, data in plan["folders"] if id not in existing_folders or not resuming]
    writes += [(target.collection("cards").document(id), data) for id, data in plan["cards"] if id not in existing_cards or not resuming]
    # Lotes abaixo do limite de 500 escritas do Firestore; os marcadores vão por último.
    for start in range(0, len(writes), 400):
        batch = db.batch()
        for ref, data in writes[start:start + 400]:
            batch.set(ref, data)
        batch.commit()
    batch = db.batch()
    batch.set(target, {"next_position": plan["next_position"], "claimed_from": source_uid,
                       "claim_in_progress": firestore.DELETE_FIELD}, merge=True)
    batch.set(source, {"migrated_to": target_uid, "migrated_at": firestore.SERVER_TIMESTAMP}, merge=True)
    batch.commit()
    return summary