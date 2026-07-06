import importlib.util
from pathlib import Path
from types import ModuleType

from sqlalchemy import Column
from sqlalchemy.dialects import mysql


def test_download_batches_migration_uses_mysql_unsigned_integer(
    monkeypatch,
) -> None:
    module = load_migration_module("20260706_0005_add_download_batches.py")
    created_tables: dict[str, tuple[object, ...]] = {}

    def capture_create_table(table_name: str, *elements: object) -> None:
        created_tables[table_name] = elements

    monkeypatch.setattr(module.op, "create_table", capture_create_table)
    monkeypatch.setattr(module.op, "create_index", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.op, "add_column", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.op, "create_foreign_key", lambda *args, **kwargs: None)

    module.upgrade()

    total_items = next(
        element
        for element in created_tables["download_batches"]
        if isinstance(element, Column) and element.name == "total_items"
    )
    assert isinstance(total_items.type, mysql.INTEGER)
    assert total_items.type.unsigned is True


def load_migration_module(filename: str) -> ModuleType:
    migration_path = Path(__file__).parents[1] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(
        "migration_under_test", migration_path
    )
    if spec is None or spec.loader is None:
        raise AssertionError(f"Could not load migration {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
