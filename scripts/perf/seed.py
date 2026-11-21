"""
Create a seeded benchmark database and print shell variables (used by ab.sh).

  python scripts/perf/seed.py --db /tmp/x/bench.db [--users 20] [--tasks-per-user 20]

Prints SECRET_KEY=... and TOKEN=... (a token for user 1), so the caller can
start uvicorn with the same key and authenticate without logging in.
"""

import argparse
import asyncio
import secrets
from pathlib import Path

from common import make_settings, migrate, seed, token


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--tasks-per-user", type=int, default=20)
    args = parser.parse_args()
    if args.db.exists():
        parser.error(f"{args.db} already exists; use a fresh path")

    secret_key = secrets.token_urlsafe(48)
    settings = make_settings(args.db, secret_key=secret_key)
    asyncio.run(migrate(settings))
    seed(args.db, settings, args.users, args.tasks_per_user)
    print(f"SECRET_KEY={secret_key}")
    print(f"TOKEN={token(1, settings)}")


if __name__ == "__main__":
    main()
