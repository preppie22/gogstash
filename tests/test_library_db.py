import copy
import sqlite3

import pytest

from gogstash import library_db

FAKE_PRODUCT = {
    "id": 111,
    "title": "Fake Game",
    "slug": "fake-game",
    "isMovie": False,
    "url": "/en/game/fake_game",
    "image": "//images.example.com/fake_game",
    "worksOn": {"Windows": True, "Linux": False, "Mac": True},
}

FAKE_DOWNLOADABLE = {
    "id": 111,
    "downloads": {
        "installers": [
            {
                "id": "installer_windows_en",
                "name": "Fake Game",
                "os": "windows",
                "language": "en",
                "total_size": 2000,
                "files": [
                    {"id": "file1", "size": 1000, "downlink": "https://example.com/file1"},
                    {"id": "file2", "size": 1000, "downlink": "https://example.com/file2"},
                ],
            }
        ],
        "bonus_content": [
            {
                "id": 6093,
                "name": "manual (33 pages)",
                "type": "manuals",
                "total_size": 500,
                "files": [
                    {"id": "bonus1", "size": 500, "downlink": "https://example.com/bonus1"},
                ],
            }
        ],
        # patches / language_packs intentionally omitted, to exercise the
        # defensive .get(category, []) fallback.
    },
}


@pytest.fixture(autouse=True)
def db():
    library_db._create_db(force=True)


def query_all(table):
    db_path = library_db._db_path_helper()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]


def test_create_db_creates_all_tables():
    db_path = library_db._db_path_helper()
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {"product", "download_group", "download_file", "fetched_files"} <= tables


def test_create_db_is_idempotent_without_force():
    library_db.update_products([FAKE_PRODUCT])
    library_db._create_db()  # force=False: should be a no-op, not wipe the table
    assert query_all("product") == [
        {
            "product_id": 111,
            "title": "Fake Game",
            "slug": "fake-game",
            "product_type": "game",
            "product_url": "https://www.gog.com/en/game/fake_game",
            "image_uri": "//images.example.com/fake_game",
            "windows": 1,
            "linux": 0,
            "osx": 1,
        }
    ]


def test_update_products_inserts_row():
    library_db.update_products([FAKE_PRODUCT])
    rows = query_all("product")
    assert rows == [
        {
            "product_id": 111,
            "title": "Fake Game",
            "slug": "fake-game",
            "product_type": "game",
            "product_url": "https://www.gog.com/en/game/fake_game",
            "image_uri": "//images.example.com/fake_game",
            "windows": 1,
            "linux": 0,
            "osx": 1,
        }
    ]


def test_update_products_marks_movies():
    movie = dict(FAKE_PRODUCT, id=222, isMovie=True)
    library_db.update_products([movie])
    row = next(r for r in query_all("product") if r["product_id"] == 222)
    assert row["product_type"] == "movie"


def test_update_products_does_not_overwrite_existing():
    library_db.update_products([FAKE_PRODUCT])
    library_db.update_products([dict(FAKE_PRODUCT, title="Changed Title")])
    rows = query_all("product")
    assert len(rows) == 1
    assert rows[0]["title"] == "Fake Game"


def test_update_downloadables_creates_db_if_missing():
    db_path = library_db._db_path_helper()
    db_path.unlink()

    library_db.update_downloadables([FAKE_DOWNLOADABLE])

    assert db_path.exists()
    groups = query_all("download_group")
    assert {row["group_id"] for row in groups} == {"installer_windows_en", "6093"}


def test_update_products_creates_db_if_missing():
    db_path = library_db._db_path_helper()
    db_path.unlink()

    library_db.update_products([FAKE_PRODUCT])

    assert db_path.exists()
    assert query_all("product")[0]["product_id"] == 111


def test_update_downloadables_inserts_groups_and_files():
    library_db.update_products([FAKE_PRODUCT])
    library_db.update_downloadables([FAKE_DOWNLOADABLE])

    groups = query_all("download_group")
    group_ids = {row["group_id"] for row in groups}
    assert group_ids == {"installer_windows_en", "6093"}

    installer_group = next(r for r in groups if r["group_id"] == "installer_windows_en")
    assert installer_group["category"] == "installers"
    assert installer_group["name"] == "Fake Game"
    assert installer_group["os"] == "windows"
    assert installer_group["total_size"] == 2000

    bonus_group = next(r for r in groups if r["group_id"] == "6093")
    assert bonus_group["category"] == "bonus_content"
    assert bonus_group["content_type"] == "manuals"
    assert bonus_group["name"] == "manual (33 pages)"

    files = query_all("download_file")
    assert len(files) == 3
    installer_file_ids = {f["file_id"] for f in files if f["group_id"] == "installer_windows_en"}
    assert installer_file_ids == {"file1", "file2"}
    bonus_files = [f for f in files if f["group_id"] == "6093"]
    assert bonus_files[0] == {
        "product_id": 111,
        "file_id": "bonus1",
        "group_id": "6093",
        "size": 500,
        "downlink": "https://example.com/bonus1",
    }


def test_update_downloadables_upsert_updates_existing_rows_not_duplicates():
    library_db.update_products([FAKE_PRODUCT])
    library_db.update_downloadables([FAKE_DOWNLOADABLE])

    updated = copy.deepcopy(FAKE_DOWNLOADABLE)
    updated["downloads"]["installers"][0]["total_size"] = 9999999
    updated["downloads"]["installers"][0]["files"][0]["size"] = 12345
    library_db.update_downloadables([updated])

    groups = query_all("download_group")
    files = query_all("download_file")

    assert len(groups) == 2  # still 2 groups, not 4 -- upsert, not duplicate insert
    assert len(files) == 3  # still 3 files, not 6

    installer_group = next(r for r in groups if r["group_id"] == "installer_windows_en")
    assert installer_group["total_size"] == 9999999

    file1 = next(f for f in files if f["file_id"] == "file1")
    assert file1["size"] == 12345


def test_update_downloadables_handles_missing_categories_gracefully():
    library_db.update_products([FAKE_PRODUCT])
    payload = {"id": 111, "downloads": {"installers": []}}

    library_db.update_downloadables([payload])

    assert query_all("download_group") == []
    assert query_all("download_file") == []
