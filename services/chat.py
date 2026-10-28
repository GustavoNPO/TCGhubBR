"""Chat entre colecionadores.

Estrutura no Firestore (só o servidor grava; o navegador apenas escuta):
- conversations/{id}                participants [uid, uid], people {uid: perfil resumido},
                                    last_message, read_at {uid: data}, updated_at
- conversations/{id}/messages/{id}  sender, text, created_at

O id da conversa é derivado do par de uids: a mesma dupla sempre cai na mesma
conversa, sem consulta prévia. O navegador entra no Firestore com o token de
/api/auth/client-token e lê em tempo real; as regras (firestore.rules) liberam
a leitura só para os participantes e bloqueiam qualquer escrita do cliente.
"""
import hashlib
import re

from services.firebase import get_firestore_client
from services.ratelimit import RateLimiter


MAX_MESSAGE_LENGTH = 1000
CONVERSATION_ID = re.compile(r"[0-9a-f]{32}")
# Controles invisíveis (exceto quebra de linha e tab) e inversões de direção do texto.
INVISIBLE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u202a-\u202e\u2066-\u2069]")
# Contra envio em massa: N mensagens por minuto por pessoa.
message_limit = RateLimiter(20, 60, "Muitas mensagens em pouco tempo. Aguarde um instante.")


class ChatError(ValueError):
    pass


class ChatNotFound(ChatError):
    pass


def conversation_id(uid_a, uid_b):
    pair = "\n".join(sorted((uid_a, uid_b)))
    return hashlib.sha256(pair.encode()).hexdigest()[:32]


def valid_conversation_id(value):
    if not isinstance(value, str) or not CONVERSATION_ID.fullmatch(value):
        raise ChatNotFound("Conversa não encontrada.")
    return value


def clean_message(text):
    if not isinstance(text, str):
        raise ChatError("Escreva uma mensagem.")
    # Mantém quebras de linha, mas não blocos de linhas vazias.
    text = INVISIBLE.sub("", text.replace("\r\n", "\n"))
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if not text:
        raise ChatError("Escreva uma mensagem.")
    if len(text) > MAX_MESSAGE_LENGTH:
        raise ChatError(f"A mensagem pode ter até {MAX_MESSAGE_LENGTH} caracteres.")
    return text


def read_path(uid):
    # uids com "-" (ou outros símbolos) precisam de crase no caminho do campo.
    from google.cloud.firestore_v1.field_path import FieldPath
    return FieldPath("read_at", uid).to_api_repr()


def person(profile):
    """O que a outra pessoa vê de você na conversa."""
    return {key: profile.get(key) for key in ("handle", "display_name", "avatar_url")}


def open_conversation(profile, other):
    """Cria ou reabre a conversa entre dois perfis; atualiza nomes e @ guardados."""
    from firebase_admin import firestore

    if profile["uid"] == other["uid"]:
        raise ChatError("Você não pode conversar com você mesmo.")
    ref = get_firestore_client().collection("conversations").document(conversation_id(profile["uid"], other["uid"]))
    people = {profile["uid"]: person(profile), other["uid"]: person(other)}

    @firestore.transactional
    def save(transaction):
        if ref.get(transaction=transaction).exists:
            transaction.update(ref, {"people": people})
        else:
            transaction.set(ref, {
                "participants": sorted(people), "people": people, "last_message": None,
                "read_at": {}, "created_at": firestore.SERVER_TIMESTAMP, "updated_at": firestore.SERVER_TIMESTAMP
            })

    save(get_firestore_client().transaction())
    return ref.id


def send_message(uid, conversation, text):
    """Grava a mensagem e o resumo da conversa juntos."""
    from firebase_admin import firestore

    db = get_firestore_client()
    ref = db.collection("conversations").document(valid_conversation_id(conversation))
    message_ref = ref.collection("messages").document()
    text = clean_message(text)
    message_limit.hit(uid)

    @firestore.transactional
    def save(transaction):
        snapshot = ref.get(transaction=transaction)
        # Conversa alheia e inexistente respondem igual.
        if not snapshot.exists or uid not in (snapshot.to_dict().get("participants") or []):
            raise ChatNotFound("Conversa não encontrada.")
        transaction.set(message_ref, {"sender": uid, "text": text, "created_at": firestore.SERVER_TIMESTAMP})
        transaction.update(ref, {
            "last_message": {"sender": uid, "text": text[:140], "at": firestore.SERVER_TIMESTAMP},
            "updated_at": firestore.SERVER_TIMESTAMP,
            # Quem envia já leu tudo até aqui.
            read_path(uid): firestore.SERVER_TIMESTAMP
        })

    save(db.transaction())
    return message_ref.id


def mark_read(uid, conversation):
    from firebase_admin import firestore

    db = get_firestore_client()
    ref = db.collection("conversations").document(valid_conversation_id(conversation))

    @firestore.transactional
    def save(transaction):
        snapshot = ref.get(transaction=transaction)
        if not snapshot.exists or uid not in (snapshot.to_dict().get("participants") or []):
            raise ChatNotFound("Conversa não encontrada.")
        transaction.update(ref, {read_path(uid): firestore.SERVER_TIMESTAMP})

    save(db.transaction())