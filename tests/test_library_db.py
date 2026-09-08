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


FAKE_PRODUCT_2 = {
    "id": 222,
    "title": "Second Fake Game",
    "slug": "second-fake-game",
    "isMovie": False,
    "url": "/en/game/second_fake_game",
    "image": "//images.example.com/second_fake_game",
    "worksOn": {"Windows": True, "Linux": True, "Mac": False},
}

FAKE_DOWNLOADABLE_2 = {
    "id": 222,
    "downloads": {
        "installers": [
            {
                "id": "installer_windows_en_2",
                "name": "Second Fake Game",
                "os": "windows",
                "language": "en",
                "total_size": 3000,
                "files": [
                    {"id": "file3", "size": 3000, "downlink": "https://example.com/file3"},
                ],
            }
        ],
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


def insert_fetched_file(product_id, group_id, file_id, size, checksum=None):
    db_path = library_db._db_path_helper()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO fetched_files VALUES (?, ?, ?, ?, ?, ?)",
            (product_id, file_id, group_id, size, checksum, "2026-01-01T00:00:00"),
        )


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

    assert len(groups) == 2  # still 2, not 4: upsert not duplicate, we're not that sloppy
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


def test_get_product_listing_returns_empty_list_when_db_missing():
    library_db._db_path_helper().unlink()
    assert library_db.get_product_listing() == []


def test_get_product_listing_with_no_downloads_or_fetched_files():
    library_db.update_products([FAKE_PRODUCT])

    listing = library_db.get_product_listing()

    assert listing == [
        {
            "product_id": 111,
            "title": "Fake Game",
            "slug": "fake-game",
            "download_size": 0,
            "fetched_size": 0,
            "fetched": 0,
        }
    ]


def test_get_product_listing_sums_download_size_across_groups():
    library_db.update_products([FAKE_PRODUCT])
    library_db.update_downloadables([FAKE_DOWNLOADABLE])  # groups: 2000 + 500

    listing = library_db.get_product_listing()

    assert listing[0]["download_size"] == 2500
    assert listing[0]["fetched"] == 0
    assert listing[0]["fetched_size"] == 0


def test_get_product_listing_reflects_fetched_files():
    library_db.update_products([FAKE_PRODUCT])
    library_db.update_downloadables([FAKE_DOWNLOADABLE])
    insert_fetched_file(111, "installer_windows_en", "file1", 1000)

    listing = library_db.get_product_listing()

    assert listing[0]["fetched"] == 1
    assert listing[0]["fetched_size"] == 1000


def test_get_product_listing_join_does_not_fan_out_sums():
    # Regression: product 111 has TWO download_group rows (installer +
    # bonus_content, totaling 2500) and gets TWO fetched_files rows below.
    # A naive `LEFT JOIN download_group ... LEFT JOIN fetched_files ...` in
    # one query cross-multiplies these into 4 rows before SUM() runs, so
    # both totals would silently come back doubled if this regresses.
    library_db.update_products([FAKE_PRODUCT])
    library_db.update_downloadables([FAKE_DOWNLOADABLE])
    insert_fetched_file(111, "installer_windows_en", "file1", 100)
    insert_fetched_file(111, "installer_windows_en", "file2", 100)

    listing = library_db.get_product_listing()

    assert listing[0]["download_size"] == 2500
    assert listing[0]["fetched_size"] == 200


def test_get_product_listing_filters_by_product_id():
    library_db.update_products([FAKE_PRODUCT, FAKE_PRODUCT_2])

    listing = library_db.get_product_listing((222,))

    assert len(listing) == 1
    assert listing[0]["product_id"] == 222
    assert listing[0]["title"] == "Second Fake Game"


def test_get_downloadables_returns_empty_list_when_db_missing():
    library_db._db_path_helper().unlink()
    assert library_db.get_downloadables() == []


def test_get_downloadables_returns_files_with_category():
    library_db.update_products([FAKE_PRODUCT])
    library_db.update_downloadables([FAKE_DOWNLOADABLE])

    downloadables = library_db.get_downloadables()

    assert len(downloadables) == 3
    by_file_id = {d["file_id"]: d for d in downloadables}
    assert by_file_id["file1"]["category"] == "installers"
    assert by_file_id["file1"]["group_id"] == "installer_windows_en"
    assert by_file_id["file1"]["downlink"] == "https://example.com/file1"
    assert by_file_id["bonus1"]["category"] == "bonus_content"


def test_get_downloadables_filters_by_product_id():
    library_db.update_products([FAKE_PRODUCT, FAKE_PRODUCT_2])
    library_db.update_downloadables([FAKE_DOWNLOADABLE, FAKE_DOWNLOADABLE_2])

    downloadables = library_db.get_downloadables((222,))

    assert len(downloadables) == 1
    assert downloadables[0]["product_id"] == 222
    assert downloadables[0]["file_id"] == "file3"


def test_get_cache_size_returns_zero_when_db_missing():
    library_db._db_path_helper().unlink()
    assert library_db.get_cache_size() == 0


def test_get_cache_size_matches_db_file_size_on_disk():
    db_path = library_db._db_path_helper()
    assert library_db.get_cache_size() == db_path.stat().st_size


def test_clear_cache_is_noop_when_db_missing():
    db_path = library_db._db_path_helper()
    db_path.unlink()

    library_db.clear_cache()  # should not raise

    assert not db_path.exists()
    assert not library_db._db_path_helper(f"{db_path.name}.bak").exists()


def test_clear_cache_renames_active_db_to_backup():
    db_path = library_db._db_path_helper()
    library_db.update_products([FAKE_PRODUCT])
    backup_path = library_db._db_path_helper(f"{db_path.name}.bak")

    library_db.clear_cache()

    assert not db_path.exists()
    assert backup_path.exists()


def test_clear_cache_keeps_only_the_most_recently_cleared_backup():
    db_path = library_db._db_path_helper()
    backup_path = library_db._db_path_helper(f"{db_path.name}.bak")

    library_db.update_products([FAKE_PRODUCT])
    library_db.clear_cache()
    with sqlite3.connect(backup_path) as conn:
        assert conn.execute("SELECT product_id FROM product").fetchall() == [(111,)]

    library_db._create_db(force=True)
    library_db.update_products([FAKE_PRODUCT_2])
    library_db.clear_cache()  # a second clear should replace, not sit alongside, the first backup

    assert len(list(db_path.parent.glob(f"{db_path.name}*.bak"))) == 1
    with sqlite3.connect(backup_path) as conn:
        assert conn.execute("SELECT product_id FROM product").fetchall() == [(222,)]
