import argparse
import getpass
import os

from yt_downloader_api.db.session import get_session_factory
from yt_downloader_api.services.auth import create_user


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a yt-downloader user.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--admin", action="store_true")
    parser.add_argument(
        "--password-env",
        default="YT_DOWNLOADER_ADMIN_PASSWORD",
        help="Environment variable containing the password.",
    )
    parser.add_argument("--password", action="store_true", help="Prompt for password.")
    args = parser.parse_args(argv)

    password = os.environ.get(args.password_env)
    if password is None:
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords do not match.")
            return 1
    session_factory = get_session_factory()
    with session_factory() as session:
        user = create_user(
            session,
            args.username,
            args.display_name,
            password,
            is_admin=args.admin,
        )
    print(f"Created user {user.username}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
