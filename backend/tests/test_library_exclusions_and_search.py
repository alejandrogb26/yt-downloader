import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from yt_downloader_api.core.config import get_settings
from yt_downloader_api.main import app
from yt_downloader_api.services.library_exclusions import load_library_excluded_names


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as async_client:
        yield async_client


def configure_profiles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, root_path: Path
) -> None:
    config_path = tmp_path / "profiles.json"
    config_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "pepe",
                        "display_name": "Pepe",
                        "root_path": str(root_path),
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROFILES_CONFIG_PATH", str(config_path))
    monkeypatch.setenv(
        "LIBRARY_EXCLUSIONS_CONFIG_PATH",
        str(tmp_path / "missing-library-exclusions.json"),
    )
    get_settings.cache_clear()


def configure_exclusions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, names: list[object]
) -> Path:
    config_path = tmp_path / "library-exclusions.json"
    config_path.write_text(json.dumps({"excluded_names": names}), encoding="utf-8")
    monkeypatch.setenv("LIBRARY_EXCLUSIONS_CONFIG_PATH", str(config_path))
    get_settings.cache_clear()
    return config_path


@pytest.mark.anyio
async def test_missing_exclusions_config_uses_empty_list(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / "@eaDir").mkdir()
    configure_profiles(monkeypatch, tmp_path, library_root)

    response = await client.get("/api/v1/profiles/pepe/entries")

    assert response.status_code == 200
    assert [entry["name"] for entry in response.json()["entries"]] == ["@eaDir"]


def test_valid_exclusions_config_deduplicates_with_casefold(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = configure_exclusions(monkeypatch, tmp_path, [" @eaDir ", "@EADIR"])

    assert load_library_excluded_names(str(config_path)) == frozenset({"@eadir"})


@pytest.mark.anyio
@pytest.mark.parametrize(
    "excluded_names",
    [
        [],
        [""],
        ["   "],
        ["bad/name"],
        [r"bad\name"],
        ["bad\x00name"],
        ["bad\x1fname"],
        ["."],
        [".."],
    ],
)
async def test_invalid_exclusions_config_returns_safe_error(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    excluded_names: list[str],
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, library_root)
    if excluded_names == []:
        config_path = tmp_path / "library-exclusions.json"
        config_path.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("LIBRARY_EXCLUSIONS_CONFIG_PATH", str(config_path))
    else:
        configure_exclusions(monkeypatch, tmp_path, excluded_names)
    get_settings.cache_clear()

    response = await client.get("/api/v1/profiles/pepe/entries")

    assert response.status_code == 503
    assert response.json() == {"detail": "Library exclusions configuration is invalid."}
    assert str(library_root) not in response.text


@pytest.mark.anyio
async def test_exclusions_apply_to_listing_navigation_and_search(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    excluded = library_root / "@eaDir"
    visible = library_root / "Rock"
    excluded.mkdir(parents=True)
    visible.mkdir()
    (excluded / "song.mp3").write_bytes(b"hidden")
    (visible / "song.mp3").write_bytes(b"visible")
    configure_profiles(monkeypatch, tmp_path, library_root)
    configure_exclusions(monkeypatch, tmp_path, ["@eaDir"])

    list_response = await client.get("/api/v1/profiles/pepe/entries")
    navigate_response = await client.get(
        "/api/v1/profiles/pepe/entries",
        params={"path": "@eadir"},
    )
    search_response = await client.get(
        "/api/v1/profiles/pepe/search",
        params={"q": "song"},
    )

    assert list_response.status_code == 200
    assert [entry["name"] for entry in list_response.json()["entries"]] == ["Rock"]
    assert navigate_response.status_code == 422
    assert navigate_response.json() == {"detail": "Requested entry is not allowed."}
    assert search_response.status_code == 200
    assert [entry["path"] for entry in search_response.json()["results"]] == [
        "Rock/song.mp3"
    ]
    assert "@eaDir" not in search_response.text


@pytest.mark.anyio
async def test_operations_on_excluded_paths_are_blocked(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    excluded = library_root / "@eaDir"
    visible = library_root / "Visible"
    excluded.mkdir(parents=True)
    visible.mkdir()
    (library_root / "song.mp3").write_bytes(b"song")
    (excluded / "song.mp3").write_bytes(b"hidden")
    configure_profiles(monkeypatch, tmp_path, library_root)
    configure_exclusions(monkeypatch, tmp_path, ["@eaDir"])

    create_response = await client.post(
        "/api/v1/profiles/pepe/directories",
        json={"name": "@eadir"},
    )
    rename_response = await client.patch(
        "/api/v1/profiles/pepe/entries/rename",
        json={"path": "song.mp3", "new_name": "@eaDir"},
    )
    move_response = await client.post(
        "/api/v1/profiles/pepe/entries/move",
        json={"source_path": "song.mp3", "target_directory_path": "@eaDir"},
    )
    trash_response = await client.request(
        "DELETE",
        "/api/v1/profiles/pepe/entries",
        json={"path": "@eaDir/song.mp3"},
    )

    assert create_response.status_code == 422
    assert rename_response.status_code == 422
    assert move_response.status_code == 422
    assert trash_response.status_code == 422
    assert all(
        response.json() == {"detail": "Requested entry is not allowed."}
        for response in [
            create_response,
            rename_response,
            move_response,
            trash_response,
        ]
    )
    assert (library_root / "song.mp3").is_file()
    assert (excluded / "song.mp3").is_file()


@pytest.mark.anyio
async def test_search_returns_nested_items_sorted_without_absolute_paths(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    (library_root / "z Song Folder").mkdir(parents=True)
    (library_root / "Alpha Song Folder").mkdir()
    (library_root / "Nested" / "Beta Song Folder").mkdir(parents=True)
    (library_root / "Nested" / "z song.mp3").write_bytes(b"123")
    (library_root / "alpha song.mp3").write_bytes(b"1")
    configure_profiles(monkeypatch, tmp_path, library_root)

    response = await client.get("/api/v1/profiles/pepe/search", params={"q": "song"})

    assert response.status_code == 200
    assert response.json()["truncated"] is False
    assert response.json()["results"] == [
        {
            "name": "Alpha Song Folder",
            "path": "Alpha Song Folder",
            "type": "directory",
            "size_bytes": None,
        },
        {
            "name": "Beta Song Folder",
            "path": "Nested/Beta Song Folder",
            "type": "directory",
            "size_bytes": None,
        },
        {
            "name": "z Song Folder",
            "path": "z Song Folder",
            "type": "directory",
            "size_bytes": None,
        },
        {
            "name": "alpha song.mp3",
            "path": "alpha song.mp3",
            "type": "file",
            "size_bytes": 1,
        },
        {
            "name": "z song.mp3",
            "path": "Nested/z song.mp3",
            "type": "file",
            "size_bytes": 3,
        },
    ]
    assert str(library_root) not in response.text
    assert "root_path" not in response.text


@pytest.mark.anyio
async def test_search_limit_truncated_validation_hidden_and_symlink_exclusion(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    for index in range(3):
        (library_root / f"song-{index}.mp3").write_bytes(b"x")
    (library_root / ".hidden-song.mp3").write_bytes(b"hidden")
    external = tmp_path / "external-song.mp3"
    external.write_bytes(b"external")
    symlink_path = library_root / "linked-song.mp3"
    try:
        symlink_path.symlink_to(external)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Symlinks are not available on this platform: {exc}")
    configure_profiles(monkeypatch, tmp_path, library_root)

    response = await client.get(
        "/api/v1/profiles/pepe/search",
        params={"q": "song", "limit": "2"},
    )
    empty_query_response = await client.get(
        "/api/v1/profiles/pepe/search",
        params={"q": "   "},
    )
    too_large_limit_response = await client.get(
        "/api/v1/profiles/pepe/search",
        params={"q": "song", "limit": "101"},
    )

    assert response.status_code == 200
    assert response.json()["truncated"] is True
    assert len(response.json()["results"]) == 2
    assert ".hidden-song.mp3" not in response.text
    assert "linked-song.mp3" not in response.text
    assert empty_query_response.status_code == 422
    assert empty_query_response.json() == {"detail": "Invalid search query."}
    assert too_large_limit_response.status_code == 422
    assert too_large_limit_response.json() == {"detail": "Invalid search query."}


@pytest.mark.anyio
async def test_search_stops_after_confirming_truncation(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    later_directory = library_root / "zzz-later"
    library_root.mkdir()
    later_directory.mkdir()
    for index in range(3):
        (library_root / f"song-{index}.mp3").write_bytes(b"x")
    (later_directory / "song-late.mp3").write_bytes(b"late")
    configure_profiles(monkeypatch, tmp_path, library_root)
    original_iterdir = Path.iterdir
    visited: list[Path] = []

    def observed_iterdir(path: Path):
        visited.append(path)
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", observed_iterdir)

    response = await client.get(
        "/api/v1/profiles/pepe/search",
        params={"q": "song", "limit": "2"},
    )

    assert response.status_code == 200
    assert response.json()["truncated"] is True
    assert [item["path"] for item in response.json()["results"]] == [
        "song-0.mp3",
        "song-1.mp3",
    ]
    assert later_directory not in visited


@pytest.mark.anyio
async def test_search_exact_limit_is_not_truncated(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    for index in range(2):
        (library_root / f"song-{index}.mp3").write_bytes(b"x")
    configure_profiles(monkeypatch, tmp_path, library_root)

    response = await client.get(
        "/api/v1/profiles/pepe/search",
        params={"q": "song", "limit": "2"},
    )

    assert response.status_code == 200
    assert response.json()["truncated"] is False
    assert [item["path"] for item in response.json()["results"]] == [
        "song-0.mp3",
        "song-1.mp3",
    ]
