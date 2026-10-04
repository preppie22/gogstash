import copy
import sqlite3
from unittest.mock import patch

import pytest

from gogstash import library_db, paths, settings
from tests.fakes import gog_product

FAKE_DOWNLOADS = {
    "installers": [
        {
            "id": "installer_windows_en",
            "name": "Fake Game",
            "os": "windows",
            "language": "en",
            "version": "1.0.2",
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
}

FAKE_PRODUCT = gog_product(111, "Fake Game", "fake-game", downloads=FAKE_DOWNLOADS)

FAKE_PRODUCT_2 = gog_product(222, "Second Fake Game", "second-fake-game", linux=True, osx=False, downloads={
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
})

# A base game and its DLC. GOG reuses group ids like installer_windows_en
# across them, so the DLC's files only stay apart under its own product id.
FAKE_DLC = gog_product(555, "Fake Game: Extra Hats", "fake-game-extra-hats", game_type="dlc", downloads={
    "installers": [
        {
            "id": "installer_windows_en",
            "name": "Fake Game: Extra Hats",
            "os": "windows",
            "language": "en",
            "total_size": 700,
            "files": [
                {"id": "en1installer0", "size": 700, "downlink": "https://example.com/hats"},
            ],
        }
    ],
})
FAKE_GAME_WITH_DLC = gog_product(333, "Hat Simulator", "hat-simulator", dlcs=[555, 556], downloads={
    "installers": [
        {
            "id": "installer_windows_en",
            "name": "Hat Simulator",
            "os": "windows",
            "language": "en",
            "total_size": 4000,
            "files": [
                {"id": "en1installer0", "size": 4000, "downlink": "https://example.com/hat_sim"},
            ],
        }
    ],
})

# Amazon Prime / Luna freebies show up in the owned list as products of their
# own. Free, plentiful, and not actually games.
FAKE_PACK = gog_product(999, "Prime Gaming Bundle", game_type="pack", downloads={
    "installers": [
        {
            "id": "installer_windows_en",
            "name": "Prime Gaming Bundle",
            "os": "windows",
            "language": "en",
            "total_size": 1,
            "files": [{"id": "pack_file", "size": 1, "downlink": "https://example.com/pack"}],
        }
    ],
})


@pytest.fixture(autouse=True)
def db():
    library_db._create_db(force=True)


def query_all(table):
    db_path = paths.config_file_path(paths.ConfigFile.DB_CACHE)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]


def user_version(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def test_create_db_creates_all_tables():
    db_path = paths.config_file_path(paths.ConfigFile.DB_CACHE)
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {"product", "download_group", "download_file"} <= tables


def test_create_db_stamps_the_schema_version():
    db_path = paths.config_file_path(paths.ConfigFile.DB_CACHE)
    assert user_version(db_path) == library_db.SCHEMA_VERSION


EXPECTED_FAKE_PRODUCT_ROW = {
    "product_id": 111,
    "parent_id": None,
    "title": "Fake Game",
    "slug": "fake-game",
    "product_type": "game",
    "product_url": "https://www.gog.com/game/fake-game",
    "image_uri": "//images.example.com/fake-game.png",
    "windows": 1,
    "linux": 0,
    "osx": 1,
}


def test_create_db_is_idempotent_without_force():
    library_db.update_cache([FAKE_PRODUCT])
    library_db._create_db()  # force=False: should be a no-op, not wipe the table
    assert query_all("product") == [EXPECTED_FAKE_PRODUCT_ROW]


def test_update_cache_inserts_product_row():
    library_db.update_cache([FAKE_PRODUCT])
    assert query_all("product") == [EXPECTED_FAKE_PRODUCT_ROW]


def test_update_cache_creates_db_if_missing():
    db_path = paths.config_file_path(paths.ConfigFile.DB_CACHE)
    db_path.unlink()

    library_db.update_cache([FAKE_PRODUCT])

    assert db_path.exists()
    assert query_all("product")[0]["product_id"] == 111
    assert {row["group_id"] for row in query_all("download_group")} == {"installer_windows_en", "6093"}


def test_update_cache_updates_an_existing_product():
    # GOG renames things. The cache used to cling to the first title it ever
    # saw like a grudge; now a refresh brings it up to date.
    library_db.update_cache([FAKE_PRODUCT])
    library_db.update_cache([dict(FAKE_PRODUCT, title="Fake Game: Director's Cut")])

    rows = query_all("product")
    assert len(rows) == 1
    assert rows[0]["title"] == "Fake Game: Director's Cut"


def test_update_cache_skips_packs_and_their_files():
    # 207 Prime Gaming bundles in a real library, zero of them welcome here.
    library_db.update_cache([FAKE_PRODUCT, FAKE_PACK])

    assert [row["product_id"] for row in query_all("product")] == [111]
    assert all(row["product_id"] != 999 for row in query_all("download_group"))
    assert all(row["product_id"] != 999 for row in query_all("download_file"))


def test_update_cache_skips_unknown_product_types():
    library_db.update_cache([gog_product(777, "Mystery Box", game_type="mystery")])

    assert query_all("product") == []


def test_update_cache_links_dlc_to_its_parent_even_when_the_dlc_comes_first():
    # Owned IDs come back as a set, so the DLC can easily show up before the
    # game that knows it's the parent. Order of arrival is not a family tree.
    library_db.update_cache([FAKE_DLC, FAKE_GAME_WITH_DLC])

    rows = {row["product_id"]: row for row in query_all("product")}
    assert rows[555]["parent_id"] == 333
    assert rows[555]["product_type"] == "dlc"
    assert rows[333]["parent_id"] is None


def test_update_cache_leaves_parent_empty_for_a_dlc_whose_game_is_not_owned():
    library_db.update_cache([FAKE_DLC])

    row = query_all("product")[0]
    assert row["product_id"] == 555
    assert row["parent_id"] is None


def test_update_cache_fills_in_a_parent_found_on_a_later_refresh():
    library_db.update_cache([FAKE_DLC])
    library_db.update_cache([FAKE_DLC, FAKE_GAME_WITH_DLC])

    row = next(r for r in query_all("product") if r["product_id"] == 555)
    assert row["parent_id"] == 333


def test_update_cache_keeps_dlc_files_under_the_dlc_not_the_parent():
    # Both products have an installer_windows_en group. Filed under the
    # parent's id, the DLC's installer would quietly overwrite the game's.
    library_db.update_cache([FAKE_GAME_WITH_DLC, FAKE_DLC])

    groups = {(row["product_id"], row["group_id"]): row for row in query_all("download_group")}
    assert groups[(333, "installer_windows_en")]["total_size"] == 4000
    assert groups[(555, "installer_windows_en")]["total_size"] == 700
    files = {(row["product_id"], row["file_id"]): row for row in query_all("download_file")}
    assert files[(333, "en1installer0")]["downlink"] == "https://example.com/hat_sim"
    assert files[(555, "en1installer0")]["downlink"] == "https://example.com/hats"


def test_update_cache_inserts_groups_and_files():
    library_db.update_cache([FAKE_PRODUCT])

    groups = query_all("download_group")
    group_ids = {row["group_id"] for row in groups}
    assert group_ids == {"installer_windows_en", "6093"}

    installer_group = next(r for r in groups if r["group_id"] == "installer_windows_en")
    assert installer_group["category"] == "installers"
    assert installer_group["name"] == "Fake Game"
    assert installer_group["os"] == "windows"
    assert installer_group["version"] == "1.0.2"
    assert installer_group["total_size"] == 2000

    bonus_group = next(r for r in groups if r["group_id"] == "6093")
    assert bonus_group["category"] == "bonus_content"
    assert bonus_group["content_type"] == "manuals"
    assert bonus_group["name"] == "manual (33 pages)"
    assert bonus_group["version"] is None  # extras don't do version numbers

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


def test_update_cache_upsert_updates_existing_rows_not_duplicates():
    library_db.update_cache([FAKE_PRODUCT])

    updated = copy.deepcopy(FAKE_PRODUCT)
    updated["downloads"]["installers"][0]["total_size"] = 9999999
    updated["downloads"]["installers"][0]["version"] = "1.0.3"
    updated["downloads"]["installers"][0]["files"][0]["size"] = 12345
    library_db.update_cache([updated])

    groups = query_all("download_group")
    files = query_all("download_file")

    assert len(groups) == 2  # still 2, not 4: upsert not duplicate, we're not that sloppy
    assert len(files) == 3  # still 3 files, not 6

    installer_group = next(r for r in groups if r["group_id"] == "installer_windows_en")
    assert installer_group["total_size"] == 9999999
    assert installer_group["version"] == "1.0.3"

    file1 = next(f for f in files if f["file_id"] == "file1")
    assert file1["size"] == 12345


def test_update_cache_handles_missing_categories_gracefully():
    library_db.update_cache([gog_product(111, "Fake Game", downloads={"installers": []})])

    assert len(query_all("product")) == 1
    assert query_all("download_group") == []
    assert query_all("download_file") == []


def test_update_cache_handles_a_product_with_no_downloads_key():
    product = gog_product(111, "Fake Game")
    del product["downloads"]

    library_db.update_cache([product])

    assert len(query_all("product")) == 1
    assert query_all("download_group") == []


def test_verify_schema_version_passes_when_there_is_no_cache_yet():
    db_path = paths.config_file_path(paths.ConfigFile.DB_CACHE)
    db_path.unlink()

    assert library_db.verify_schema_version() is True
    assert not db_path.exists()  # checking the version is not a reason to make a cache


def test_verify_schema_version_leaves_a_current_cache_alone():
    library_db.update_cache([FAKE_PRODUCT])

    assert library_db.verify_schema_version() is True
    assert query_all("product") == [EXPECTED_FAKE_PRODUCT_ROW]
    assert not paths.config_file_backup(paths.ConfigFile.DB_CACHE).exists()


def _write_cache_with_version(version):
    db_path = paths.config_file_path(paths.ConfigFile.DB_CACHE)
    db_path.unlink()
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE product(product_id BIGINT PRIMARY KEY, title TEXT)")
    conn.execute("INSERT INTO product VALUES (111, 'Fake Game')")
    conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()
    conn.close()
    return db_path


def test_verify_schema_version_rebuilds_a_cache_from_before_versioning():
    # beta2 caches never set user_version, so they read as 0 and have no
    # parent_id column. Left alone, get_product_listing faceplants at startup
    # before the main window even gets to say hello.
    db_path = _write_cache_with_version(0)

    assert library_db.verify_schema_version() is False

    assert user_version(db_path) == library_db.SCHEMA_VERSION
    assert query_all("product") == []
    backup_path = paths.config_file_backup(paths.ConfigFile.DB_CACHE)
    with sqlite3.connect(backup_path) as conn:
        assert conn.execute("SELECT product_id FROM product").fetchall() == [(111,)]


def test_verify_schema_version_rebuilds_a_cache_from_a_newer_version_too():
    # Going back to an older GogStash shouldn't mean squinting at columns
    # from the future. Any mismatch is a rebuild, in either direction.
    db_path = _write_cache_with_version(library_db.SCHEMA_VERSION + 1)

    assert library_db.verify_schema_version() is False
    assert user_version(db_path) == library_db.SCHEMA_VERSION


def test_get_product_listing_works_right_after_a_schema_rebuild():
    _write_cache_with_version(0)
    library_db.verify_schema_version()

    assert library_db.get_product_listing() == []


def test_get_product_listing_returns_empty_list_when_db_missing():
    paths.config_file_path(paths.ConfigFile.DB_CACHE).unlink()
    assert library_db.get_product_listing() == []


def test_get_product_listing_with_no_downloads():
    library_db.update_cache([gog_product(111, "Fake Game", "fake-game")])

    listing = library_db.get_product_listing()

    assert listing == [
        {
            "product_id": 111,
            "parent_id": None,
            "title": "Fake Game",
            "slug": "fake-game",
            "download_size": 0,
        }
    ]


def test_get_product_listing_sums_download_size_across_groups():
    # Product 111 has TWO download groups (installer + bonus_content), with
    # the installer split across two files. Every one of them has to make
    # it into the total, not just whichever file got there first.
    settings.update_setting("bonus_content", True)
    library_db.update_cache([FAKE_PRODUCT])  # files: 1000 + 1000 + 500

    listing = library_db.get_product_listing()

    assert listing[0]["download_size"] == 2500


def test_get_product_listing_size_follows_the_download_filters():
    # The list used to quote the whole buffet while the queue only served
    # what you ordered (#5). Bonus content is off by default, so the
    # 500-byte manual stays off the bill.
    library_db.update_cache([FAKE_PRODUCT])

    listing = library_db.get_product_listing()

    assert listing[0]["download_size"] == 2000


def test_get_product_listing_size_counts_only_the_extras_with_installers_unticked():
    # #13: two 1000-byte installer files leave the bill, the 500-byte
    # manual is all that's left on it.
    settings.update_setting("installers", False)
    settings.update_setting("bonus_content", True)
    library_db.update_cache([FAKE_PRODUCT])

    listing = library_db.get_product_listing()

    assert listing[0]["download_size"] == 500


def test_get_product_listing_shows_zero_when_the_filters_leave_nothing():
    # A Windows-only game on a Linux-only setup has nothing left to
    # download. That's a zero in the size column, not a KeyError that
    # takes the whole game list down with it.
    settings.update_setting("platform_filter", ["Linux"])
    library_db.update_cache([FAKE_PRODUCT, FAKE_PRODUCT_2])

    listing = library_db.get_product_listing()

    assert [p["download_size"] for p in listing] == [0, 0]


def test_get_product_listing_filters_by_product_id():
    library_db.update_cache([FAKE_PRODUCT, FAKE_PRODUCT_2])

    listing = library_db.get_product_listing((222,))

    assert len(listing) == 1
    assert listing[0]["product_id"] == 222
    assert listing[0]["title"] == "Second Fake Game"


def test_get_product_listing_includes_dlcs_with_their_parent():
    library_db.update_cache([FAKE_GAME_WITH_DLC, FAKE_DLC])

    listing = {p["product_id"]: p for p in library_db.get_product_listing()}

    assert listing[555]["parent_id"] == 333
    assert listing[333]["parent_id"] is None


def test_get_product_listing_moves_a_dlc_in_with_its_base_game():
    # The slug is the download folder, and a DLC has no business living
    # alone in "fake-game-extra-hats" when its game has a perfectly good room.
    library_db.update_cache([FAKE_GAME_WITH_DLC, FAKE_DLC])

    listing = {p["product_id"]: p for p in library_db.get_product_listing()}

    assert listing[555]["slug"] == "hat-simulator"
    assert listing[333]["slug"] == "hat-simulator"


def test_get_product_listing_for_just_the_dlc_still_finds_the_parents_folder():
    # The worker asks about one product at a time. The ID filter must not
    # filter out the parent row the folder name comes from.
    library_db.update_cache([FAKE_GAME_WITH_DLC, FAKE_DLC])

    [dlc] = library_db.get_product_listing((555,))

    assert dlc["slug"] == "hat-simulator"


def test_get_product_listing_lets_an_orphan_dlc_keep_its_own_folder():
    # Own the DLC, not the game: no parent to move in with, so it gets its own
    # place rather than a folder called None.
    library_db.update_cache([FAKE_DLC])

    [dlc] = library_db.get_product_listing()

    assert dlc["slug"] == "fake-game-extra-hats"


def test_platform_helper_maps_settings_labels_to_gog_os_values():
    assert library_db._platform_helper(["Linux", "Windows", "MacOS"]) == [
        "linux",
        "windows",
        "mac",
    ]
    assert library_db._platform_helper(["Linux"]) == ["linux"]


def test_platform_helper_falls_back_to_the_defaults_for_a_mangled_config():
    # Someone hand-edited settings.json and left platform_filter as null.
    # Better to download everything than to crash the game list before it
    # even loads.
    assert library_db._platform_helper(None) == ["linux", "windows", "mac"]


def test_platform_helper_takes_an_empty_filter_at_its_word():
    # Unticking every platform in Settings is a choice, not a typo. No
    # platforms means no platforms, not "surprise, all three".
    assert library_db._platform_helper([]) == []


def test_get_downloadables_returns_empty_list_when_db_missing():
    paths.config_file_path(paths.ConfigFile.DB_CACHE).unlink()
    assert library_db.get_downloadables() == []


def test_get_downloadables_returns_files_with_category():
    library_db.update_cache([FAKE_PRODUCT])

    downloadables = library_db.get_downloadables()

    assert len(downloadables) == 3
    by_file_id = {d["file_id"]: d for d in downloadables}
    assert by_file_id["file1"]["category"] == "installers"
    assert by_file_id["file1"]["group_id"] == "installer_windows_en"
    assert by_file_id["file1"]["downlink"] == "https://example.com/file1"
    assert by_file_id["file1"]["language"] == "en"
    assert by_file_id["bonus1"]["category"] == "bonus_content"
    assert by_file_id["bonus1"]["language"] is None


def test_get_downloadables_filters_by_product_id():
    library_db.update_cache([FAKE_PRODUCT, FAKE_PRODUCT_2])

    downloadables = library_db.get_downloadables((222,))

    assert len(downloadables) == 1
    assert downloadables[0]["product_id"] == 222
    assert downloadables[0]["file_id"] == "file3"


def test_get_cache_size_returns_zero_when_db_missing():
    paths.config_file_path(paths.ConfigFile.DB_CACHE).unlink()
    assert library_db.get_cache_size() == 0


def test_get_cache_size_matches_db_file_size_on_disk():
    db_path = paths.config_file_path(paths.ConfigFile.DB_CACHE)
    assert library_db.get_cache_size() == db_path.stat().st_size


def test_clear_cache_is_noop_when_db_missing():
    db_path = paths.config_file_path(paths.ConfigFile.DB_CACHE)
    db_path.unlink()

    library_db.clear_cache()  # should not raise

    assert not db_path.exists()
    assert not paths.config_file_backup(paths.ConfigFile.DB_CACHE).exists()


def test_clear_cache_renames_active_db_to_backup():
    db_path = paths.config_file_path(paths.ConfigFile.DB_CACHE)
    library_db.update_cache([FAKE_PRODUCT])
    backup_path = paths.config_file_backup(paths.ConfigFile.DB_CACHE)

    library_db.clear_cache()

    assert not db_path.exists()
    assert backup_path.exists()


def test_clear_cache_keeps_only_the_most_recently_cleared_backup():
    db_path = paths.config_file_path(paths.ConfigFile.DB_CACHE)
    backup_path = paths.config_file_backup(paths.ConfigFile.DB_CACHE)

    library_db.update_cache([FAKE_PRODUCT])
    library_db.clear_cache()
    with sqlite3.connect(backup_path) as conn:
        assert conn.execute("SELECT product_id FROM product").fetchall() == [(111,)]

    library_db._create_db(force=True)
    library_db.update_cache([FAKE_PRODUCT_2])
    library_db.clear_cache()  # a second clear should replace, not sit alongside, the first backup

    assert len(list(db_path.parent.glob(f"{db_path.name}*.bak"))) == 1
    with sqlite3.connect(backup_path) as conn:
        assert conn.execute("SELECT product_id FROM product").fetchall() == [(222,)]


# --- LibraryFetchThread ---

@patch("gogstash.library_db.fetch_downloadables")
@patch("gogstash.library_db.fetch_owned_ids")
def test_library_fetch_thread_bootstraps_when_db_empty(mock_fetch_owned_ids, mock_fetch_downloadables):
    mock_fetch_owned_ids.return_value = {111}
    mock_fetch_downloadables.return_value = [FAKE_PRODUCT]
    thread = library_db.LibraryFetchThread()
    received = []
    thread.succeeded.connect(lambda result: received.append(result))
    thread.failed.connect(lambda msg: pytest.fail(f"failed signal should not have fired: {msg}"))

    thread.run()

    mock_fetch_owned_ids.assert_called_once_with()
    # A list, not the set: fetch_downloadables slices its input into batches,
    # and sets have never once agreed to be sliced.
    mock_fetch_downloadables.assert_called_once_with([111], thread.update_progress)
    assert len(received) == 1
    # 2000, not 2500: bonus content is off by default, so the manual
    # doesn't count toward the size.
    assert received[0] == [
        {"product_id": 111, "parent_id": None, "title": "Fake Game", "slug": "fake-game", "download_size": 2000}
    ]


@patch("gogstash.library_db.fetch_downloadables")
@patch("gogstash.library_db.fetch_owned_ids")
def test_library_fetch_thread_reads_cache_without_hitting_network(mock_fetch_owned_ids, mock_fetch_downloadables):
    library_db.update_cache([FAKE_PRODUCT])
    thread = library_db.LibraryFetchThread()
    received = []
    thread.succeeded.connect(lambda result: received.append(result))
    thread.failed.connect(lambda msg: pytest.fail(f"failed signal should not have fired: {msg}"))

    thread.run()

    mock_fetch_owned_ids.assert_not_called()
    mock_fetch_downloadables.assert_not_called()
    assert received[0][0]["product_id"] == 111


@patch("gogstash.library_db.fetch_downloadables")
@patch("gogstash.library_db.fetch_owned_ids")
def test_library_fetch_thread_force_refreshes_a_full_cache(mock_fetch_owned_ids, mock_fetch_downloadables):
    # The Refresh button. A cache full of stale titles is not an excuse to
    # skip asking GOG what you actually own.
    library_db.update_cache([FAKE_PRODUCT])
    mock_fetch_owned_ids.return_value = {111, 222}
    mock_fetch_downloadables.return_value = [FAKE_PRODUCT, FAKE_PRODUCT_2]
    thread = library_db.LibraryFetchThread(force=True)
    received = []
    thread.succeeded.connect(lambda result: received.append(result))

    thread.run()

    mock_fetch_owned_ids.assert_called_once_with()
    assert {p["product_id"] for p in received[0]} == {111, 222}


@patch("gogstash.library_db.fetch_owned_ids")
def test_library_fetch_thread_emits_failed_on_exception(mock_fetch_owned_ids):
    mock_fetch_owned_ids.side_effect = RuntimeError("network exploded")
    thread = library_db.LibraryFetchThread()
    errors = []
    succeeded = []
    thread.failed.connect(lambda msg: errors.append(msg))
    thread.succeeded.connect(lambda result: succeeded.append(result))

    thread.run()

    assert errors == ["network exploded"]
    assert succeeded == []


@patch("gogstash.library_db.fetch_owned_ids")
def test_library_fetch_thread_emits_auth_failure_instead_of_failed_on_permission_error(mock_fetch_owned_ids):
    # PermissionError means "not logged in", a distinct case from a generic
    # network/data failure. The UI needs to tell them apart to show the
    # right message and reset itself correctly.
    mock_fetch_owned_ids.side_effect = PermissionError("Authentication failed. Login again.")
    thread = library_db.LibraryFetchThread()
    auth_failures = []
    failed = []
    thread.auth_failure.connect(lambda: auth_failures.append(True))
    thread.failed.connect(lambda msg: failed.append(msg))

    thread.run()

    assert auth_failures == [True]
    assert failed == []


def test_get_downloadables_hands_back_each_files_installer_version():
    product = copy.deepcopy(FAKE_PRODUCT)
    product["downloads"]["installers"][0]["version"] = "2025.8.f.4"
    library_db.update_cache([product])

    versions = {d["category"]: d["version"] for d in library_db.get_downloadables((111,))}

    assert versions["installers"] == "2025.8.f.4"
    assert versions["bonus_content"] is None  # GOG doesn't version manuals
