import argparse

from yt_downloader_api.db.session import get_session_factory
from yt_downloader_api.services.db_profiles import upsert_library_profile
from yt_downloader_api.services.profiles import load_profiles_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import library profiles from JSON.")
    parser.add_argument("--profiles-json", required=True)
    args = parser.parse_args(argv)

    config = load_profiles_config(args.profiles_json)
    session_factory = get_session_factory()
    imported = 0
    with session_factory() as session:
        for profile in config.profiles:
            upsert_library_profile(
                session,
                profile.id,
                profile.display_name,
                profile.root_path,
                profile.enabled,
            )
            imported += 1
    print(f"Imported or updated {imported} profile(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
