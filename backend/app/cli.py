"""Operational CLI; secrets entered via hidden prompt, never arguments."""

import argparse
import getpass

from app.auth.passwords import create_user


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin")
    admin.add_argument("--username", required=True)
    release = commands.add_parser("register-release")
    release.add_argument("path")
    commands.add_parser("prepare-model")
    commands.add_parser("register-profile")
    args = parser.parse_args()
    if args.command == "create-admin":
        password = getpass.getpass("Password (12–256 characters): ")
        if password != getpass.getpass("Confirm password: "):
            parser.error("Passwords do not match")
        print(create_user(args.username, password))
    elif args.command == "register-release":
        from pathlib import Path

        from app.ingestion.releases import register_release

        print(register_release(Path(args.path)))
    elif args.command == "prepare-model":
        from app.providers.local_e5 import prepare_model

        print(prepare_model())
    elif args.command == "register-profile":
        from app.providers.embedding import default_profile, register_profile

        print(register_profile(default_profile()))


if __name__ == "__main__":
    main()
