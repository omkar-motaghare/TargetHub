"""Server-side administration commands (run inside the API container).

  docker compose exec api python -m app.manage list-users
  docker compose exec api python -m app.manage create-admin alice
  docker compose exec api python -m app.manage reset-password alice
  docker compose exec api python -m app.manage enable-user alice

Passwords are generated randomly (printed once) unless --password-stdin is
given. Every change is written to the audit log as action "manage.*".
"""

from __future__ import annotations

import argparse
import secrets
import sys

from app.db.session import SessionLocal
from app.repositories.audit_repository import AuditRepository
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService


def _password(args: argparse.Namespace) -> tuple[str, bool]:
    if getattr(args, "password_stdin", False):
        return sys.stdin.readline().rstrip("\n"), False
    return secrets.token_urlsafe(12), True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.manage", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list-users", help="list users with roles and status")
    for name, help_text in (
        ("create-admin", "create a new admin user"),
        ("reset-password", "set a new password (signs the user out everywhere)"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("username")
        command.add_argument("--password-stdin", action="store_true")
    for name, help_text in (("enable-user", "re-enable a disabled user"), ("make-admin", "grant the admin role")):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("username")
    args = parser.parse_args(argv)

    db = SessionLocal()
    auth = AuthService(db)
    audit = AuditService(AuditRepository(db))
    try:
        if args.command == "list-users":
            for user in auth.list_users():
                state = "active" if user.is_active else "DISABLED"
                print(f"{user.id:>4}  {user.username:<32} {','.join(user.role_list):<20} {state}")
            return 0

        if args.command == "create-admin":
            password, generated = _password(args)
            user = auth.create_user(args.username, password, ["admin"])
            audit.record(action="manage.create_admin", user_id="server-console", detail=user.username)
            print(f"Created admin '{user.username}'.")
        else:
            user = auth.repo.get_by_username(args.username)
            if user is None:
                print(f"error: user '{args.username}' not found", file=sys.stderr)
                return 1
            if args.command == "reset-password":
                password, generated = _password(args)
                auth.update_user(user.id, password=password)
                audit.record(action="manage.reset_password", user_id="server-console", detail=user.username)
                print(f"Password reset for '{user.username}'; existing logins were signed out.")
            elif args.command == "enable-user":
                auth.update_user(user.id, is_active=True)
                audit.record(action="manage.enable_user", user_id="server-console", detail=user.username)
                print(f"Enabled '{user.username}'.")
                return 0
            else:
                roles = sorted(set(user.role_list) | {"admin"})
                auth.update_user(user.id, roles=roles)
                audit.record(action="manage.make_admin", user_id="server-console", detail=user.username)
                print(f"'{user.username}' is now an admin.")
                return 0
        if generated:
            print(f"Temporary password: {password}")
            print("Ask the user to change it after signing in (Account -> Change password).")
        return 0
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
