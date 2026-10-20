
"""Vincula o inventário do demo-user a uma conta real do Firebase Authentication.

Copia users/<origem>/cards e folders para users/<uid da conta>, preservando os IDs
(as pastas continuam valendo) e colocando as cartas depois das que a conta já tem.
A origem não é apagada: fica marcada com migrated_to e não pode ser vinculada de novo.

Antes, a conta precisa ter entrado uma vez no TCG Hub (para existir o perfil).

    python -m scripts.claim_demo_user --email voce@exemplo.com            # só simula
    python -m scripts.claim_demo_user --email voce@exemplo.com --apply    # grava
"""
import argparse
import sys

from services.accounts import AccountError, claim_legacy_portfolio
from services.firebase import FirebaseUnavailable, get_firebase_app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--email", help="e-mail da conta real que vai receber as cartas")
    target.add_argument("--uid", help="uid da conta real (alternativa ao e-mail)")
    parser.add_argument("--source", default="demo-user", help="uid de origem (padrão: demo-user)")
    parser.add_argument("--apply", action="store_true", help="grava no Firestore (sem isso, só simula)")
    args = parser.parse_args(argv)

    try:
        uid = args.uid
        if args.email:
            from firebase_admin import auth
            uid = auth.get_user_by_email(args.email, app=get_firebase_app()).uid
        summary = claim_legacy_portfolio(args.source, uid, apply=args.apply)
    except (AccountError, FirebaseUnavailable) as error:
        print(f"Não vinculado: {error}", file=sys.stderr)
        return 1
    except Exception as error:  # e-mail inexistente, credenciais, rede
        print(f"Não vinculado: {error}", file=sys.stderr)
        return 1

    action = "Copiadas" if summary["applied"] else "Seriam copiadas"
    print(f"{action} {summary['cards']} carta(s) e {summary['folders']} pasta(s) de {args.source} para {uid}"
          f"{' (retomando cópia interrompida)' if summary['resumed'] else ''}.")
    if not summary["applied"]:
        print("Nada foi gravado. Rode novamente com --apply para vincular.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
