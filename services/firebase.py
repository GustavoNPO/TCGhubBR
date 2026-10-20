import os
from threading import Lock

from dotenv import load_dotenv


load_dotenv()
_client = None
_client_lock = Lock()


class FirebaseUnavailable(RuntimeError):
    pass


def get_firebase_app():
    """App Admin compartilhado por Firestore e Authentication."""
    try:
        import firebase_admin
    except ImportError as error:
        raise FirebaseUnavailable(
            "Instale as dependências do projeto para usar o inventário. Consulte o README."
        ) from error
    try:
        return firebase_admin.get_app("tcg-hub")
    except ValueError:
        pass
    try:
        project_id = os.getenv("FIREBASE_PROJECT_ID")
        options = {"projectId": project_id} if project_id else None
        # ADC lê o arquivo apontado por GOOGLE_APPLICATION_CREDENTIALS.
        return firebase_admin.initialize_app(options=options, name="tcg-hub")
    except ValueError:
        # Outra thread inicializou no intervalo.
        return firebase_admin.get_app("tcg-hub")
    except Exception as error:
        raise FirebaseUnavailable(
            "Firebase não configurado. Consulte o README para conectar o Firestore."
        ) from error


def get_firestore_client():
    """Conecta somente quando o inventário é usado, preservando o scanner."""
    global _client

    with _client_lock:
        if _client is not None:
            return _client
        firebase_app = get_firebase_app()
        try:
            
            from firebase_admin import firestore
            
            _client = firestore.client(app=firebase_app)
            
        except Exception as error:
            raise FirebaseUnavailable(
                "Firebase não configurado. Consulte o README para conectar o Firestore."
            ) from error
            
        return _client