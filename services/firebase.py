import os
from threading import Lock

from dotenv import load_dotenv


load_dotenv()
_client = None
_client_lock = Lock()


class FirebaseUnavailable(RuntimeError):
    pass


def get_firestore_client():
    """Conecta somente quando o inventário é usado, preservando o scanner."""
    global _client

    with _client_lock:
        if _client is not None:
            return _client

        try:
            import firebase_admin
            from firebase_admin import firestore

            try:
                firebase_app = firebase_admin.get_app("tcg-hub")
            except ValueError:
                project_id = os.getenv("FIREBASE_PROJECT_ID")
                options = {"projectId": project_id} if project_id else None
                # ADC lê o arquivo apontado por GOOGLE_APPLICATION_CREDENTIALS.
                firebase_app = firebase_admin.initialize_app(
                    options=options, name="tcg-hub"
                )

            _client = firestore.client(app=firebase_app)
        except ImportError as error:
            raise FirebaseUnavailable(
                "Instale as dependências do projeto para usar o inventário. Consulte o README."
            ) from error
        except Exception as error:
            raise FirebaseUnavailable(
                "Firebase não configurado. Consulte o README para conectar o Firestore."
            ) from error

        return _client