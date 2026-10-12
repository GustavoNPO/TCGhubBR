from services.firebase import get_firestore_client


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