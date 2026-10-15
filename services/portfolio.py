from services.firebase import get_firestore_client


class PortfolioNotFound(ValueError):
    pass


def _user_ref(user_id):
    return get_firestore_client().collection("users").document(user_id)


def _require(snapshot, message):
    if not snapshot.exists:
        raise PortfolioNotFound(message)
    return snapshot.to_dict()


def add_portfolio_card(user_id, card):
    db = get_firestore_client()
    from firebase_admin import firestore

    user_ref = db.collection("users").document(user_id)
    # ID próprio: duas cópias da mesma carta são dois itens do inventário.
    card_ref = user_ref.collection("cards").document()

    @firestore.transactional
    def save(transaction):
        user = user_ref.get(transaction=transaction)
        position = (user.to_dict() or {}).get("next_position", 0)

        # Contador e carta são gravados juntos; inclusões simultâneas
        # recebem posições diferentes. Não reutilizamos posições removidas.
        transaction.set(user_ref, {"next_position": position + 1}, merge=True)
        transaction.set(card_ref, {
            **card,
            "position": position,
            "created_at": firestore.SERVER_TIMESTAMP
        })

    save(db.transaction())
    return card_ref.id


def list_portfolio_cards(user_id):
    db = get_firestore_client()
    documents = (
        db.collection("users").document(user_id).collection("cards")
        .order_by("position").stream()
    )
    return [{**document.to_dict(), "id": document.id} for document in documents]


def get_portfolio_card(user_id, card_id):
    document = _user_ref(user_id).collection("cards").document(card_id).get()
    return {**_require(document, "Carta não encontrada no seu portfólio."), "id": document.id}


def list_portfolio_folders(user_id):
    documents = _user_ref(user_id).collection("folders").stream()
    return sorted(
        [{**doc.to_dict(), "id": doc.id} for doc in documents],
        key=lambda folder: folder["name"].casefold()
    )


def create_portfolio_folder(user_id, name):
    from firebase_admin import firestore

    ref = _user_ref(user_id).collection("folders").document()
    ref.set({"name": name, "created_at": firestore.SERVER_TIMESTAMP})
    return ref.id


def rename_portfolio_folder(user_id, folder_id, name):
    from firebase_admin import firestore

    db = get_firestore_client()
    ref = _user_ref(user_id).collection("folders").document(folder_id)

    @firestore.transactional
    def save(transaction):
        _require(ref.get(transaction=transaction), "Pasta não encontrada.")
        transaction.update(ref, {"name": name})

    save(db.transaction())


def delete_portfolio_folder(user_id, folder_id):
    """Remover uma pasta devolve suas cartas ao inventário sem pasta."""
    from firebase_admin import firestore

    db = get_firestore_client()
    user = _user_ref(user_id)
    ref = user.collection("folders").document(folder_id)

    @firestore.transactional
    def remove(transaction):
        _require(ref.get(transaction=transaction), "Pasta não encontrada.")
        cards = list(user.collection("cards").where(
            filter=firestore.FieldFilter("folder_id", "==", folder_id)
        ).stream(transaction=transaction))
        if len(cards) > 450:
            raise ValueError("Mova as cartas em grupos antes de excluir esta pasta.")
        for card in cards:
            transaction.update(card.reference, {"folder_id": None})
        transaction.delete(ref)

    remove(db.transaction())


def mutate_portfolio_cards(user_id, card_ids, action, folder_id=None):
    """A mesma manutenção serve para qualquer jogo/provedor e é atômica."""
    from firebase_admin import firestore

    db = get_firestore_client()
    user = _user_ref(user_id)
    refs = [user.collection("cards").document(card_id) for card_id in card_ids]

    @firestore.transactional
    def save(transaction):
        # Todos os documentos são lidos antes de qualquer escrita.
        if action == "move" and folder_id:
            _require(user.collection("folders").document(folder_id).get(
                transaction=transaction
            ), "Pasta não encontrada.")
        cards = [_require(ref.get(transaction=transaction),
                          "Uma das cartas não existe no seu portfólio.") for ref in refs]
        if action == "reorder":
            # Reordena os itens visíveis entre suas posições atuais. Cartas
            # fora da pasta/busca mantêm suas posições; cópias usam IDs próprios.
            positions = sorted(card["position"] for card in cards)
            for ref, card, position in zip(refs, cards, positions):
                if card["position"] != position:
                    transaction.update(ref, {"position": position})
        elif action == "move":
            for ref in refs:
                transaction.update(ref, {"folder_id": folder_id})
        elif action == "delete":
            for ref in refs:
                transaction.delete(ref)
        else:
            raise ValueError("Operação inválida.")

    save(db.transaction())


def save_portfolio_prices(user_id, card_id, prices):
    from firebase_admin import firestore

    db = get_firestore_client()
    ref = _user_ref(user_id).collection("cards").document(card_id)

    @firestore.transactional
    def save(transaction):
        # Uma consulta de preço pendente não pode recriar uma carta excluída.
        _require(ref.get(transaction=transaction), "Carta não encontrada no seu portfólio.")
        transaction.update(ref, {"market_prices": prices})

    save(db.transaction())
    