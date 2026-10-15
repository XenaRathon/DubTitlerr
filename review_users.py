#!/usr/bin/env python3
"""Recovery for a locked-out sole admin: `python3 review_users.py reset-admin <name>` inside the container.

Prints a one-time password for that admin and ends its sessions. The web UI is the way to manage accounts otherwise.
If users.json is unreadable the file is set aside (users.json.corrupt-<unix time>) and <name> is created as an admin."""

import argparse
import os
import secrets
import sys
import time

import review_auth


def _set_password(name: str, new: str) -> int:
    if hasattr(review_auth, "set_password"):
        return review_auth.set_password(name, new)
    problem = review_auth.validate_password(new)
    if problem:
        raise review_auth.Invalid(problem)
    stored = review_auth.hash_password(new)
    with review_auth._locked(review_auth.users_path()):
        users = review_auth.read_users()
        row = review_auth.find_user(users, name)
        if row is None:
            raise review_auth.NotFound("no such user")
        row["hash"], row["pw_changed_at"] = stored, review_auth.CLOCK()
        row["session_epoch"] = int(row.get("session_epoch", 0)) + 1
        review_auth._write_json(review_auth.users_path(), {"version": 1, "users": users})
        canonical, epoch = row["name"], row["session_epoch"]
    review_auth.sessions().revoke_user(canonical)
    return epoch


def reset_admin(name: str) -> int:
    try:
        users = review_auth.read_users()
    except review_auth.Unreadable:
        path = review_auth.users_path()
        aside = f"{path}.corrupt-{int(time.time())}"
        os.replace(path, aside)
        print(f"users.json was unreadable and is set aside as {aside}")
        users = []
    password = secrets.token_urlsafe(12)
    if not users:
        review_auth.create_user(name, "admin", password)
    else:
        row = review_auth.find_user(users, name)
        if row is None:
            print(f"no account named {name}", file=sys.stderr)
            return 1
        if row["role"] != "admin":
            print(f"{row['name']} is not an admin; promote it from Settings, Accounts", file=sys.stderr)
            return 2
        _set_password(row["name"], password)
        name = row["name"]
    print(f"New one-time password for {name}: {password}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="review_users.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("reset-admin", help="print a new one-time password for an admin").add_argument("name")
    args = parser.parse_args(argv)
    try:
        return reset_admin(args.name)
    except review_auth.AuthError as e:
        print(e.message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
