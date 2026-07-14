import argparse

from sqlalchemy import select

from yt_downloader_api.db.models import LibraryProfileRecord, User
from yt_downloader_api.db.session import get_session_factory
from yt_downloader_api.services.auth import normalize_username
from yt_downloader_api.services.db_profiles import grant_profile_access


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Grant a user access to a library profile."
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--profile", required=True, help="Library profile slug.")
    parser.add_argument(
        "--role",
        default="owner",
        choices=["owner", "read_write", "read_only"],
    )
    args = parser.parse_args(argv)

    session_factory = get_session_factory()
    with session_factory() as session:
        user = session.scalars(
            select(User).where(User.username == normalize_username(args.username))
        ).first()
        profile = session.scalars(
            select(LibraryProfileRecord).where(
                LibraryProfileRecord.slug == args.profile
            )
        ).first()
        if user is None:
            print("User not found.")
            return 1
        if profile is None:
            print("Profile not found.")
            return 1
        grant_profile_access(session, user, profile, args.role)
    print(f"Granted {args.role} access to {args.username} for {args.profile}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
