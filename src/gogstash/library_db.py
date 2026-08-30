import sqlite3
import platformdirs
from pathlib import Path


def _db_path_helper() -> Path:
    config_dir = platformdirs.user_config_dir(appname='gogstash')
    return Path(config_dir) / "goglibrary.db"

def _create_db(force: bool = False) -> None:
    db_path = _db_path_helper()
    if db_path.exists() and not force:
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(f"""
            CREATE TABLE product(
                product_id BIGINT PRIMARY KEY,
                title TEXT,
                slug TEXT,
                product_type TEXT,
                windows INT2,
                linux INT2,
                osx INT2
            );
            CREATE TABLE download_group(
                product_id BIGINT,
                group_id TEXT,
                name TEXT,
                group_type TEXT,
                content_type TEXT,
                os TEXT,
                language TEXT,
                total_size BIGINT,
                PRIMARY KEY (product_id, group_id),
                FOREIGN KEY(product_id) REFERENCES product(product_id)
            );                
            CREATE TABLE download_file(
                product_id BIGINT,
                file_id TEXT,
                group_id TEXT,
                size BIGINT,
                downlink TEXT,
                PRIMARY KEY (product_id, group_id, file_id),
                FOREIGN KEY (product_id, group_id) REFERENCES download_group(product_id, group_id)
            );
            CREATE TABLE fetched_files(
                product_id BIGINT,
                file_id TEXT,
                group_id TEXT,
                size BIGINT,
                timestamp DATETIME,
                PRIMARY KEY (product_id, group_id, file_id),
                FOREIGN KEY (product_id, group_id) REFERENCES download_group(product_id, group_id)
            );
        """)

def update_products(products: list[dict]) -> None:
    db_path = _db_path_helper()
    if not db_path.exists():
        raise FileNotFoundError
    rows = [
        (
            product["id"],
            product["title"],
            product["slug"],
            "movie" if product["isMovie"] else "game",
            product["worksOn"]["Windows"],
            product["worksOn"]["Linux"],
            product["worksOn"]["Mac"],
        )
        for product in products
    ]
    with sqlite3.connect(db_path) as conn:
        conn.executemany("INSERT OR IGNORE INTO product VALUES (?, ?, ?, ?, ?, ?, ?)", rows)

def update_downloadables(downloadables: list[dict]) -> None:
    db_path = _db_path_helper()
    if not db_path.exists():
        raise FileNotFoundError
    group_rows = []
    file_rows = []
    groups = ['installers', 'patches', 'language_packs', 'bonus_content']
    for content in downloadables:
        downloads: dict = content.get('downloads', [])
        for category in groups:
            group = downloads.get(category, [])
            for items in group:
                group_rows.append((
                    content.get('id'),
                    items.get('id'),
                    items.get('name'),
                    category,
                    items.get('type'),
                    items.get('os'),
                    items.get('language'),
                    items.get('total_size')
                ))
                for file in items.get('files', []):
                    file_rows.append((
                        content.get('id'),
                        file.get('id'),
                        items.get('id'),
                        file.get('size'),
                        file.get('downlink')
                    ))
    with sqlite3.connect(db_path) as conn:
        conn.executemany("""
            INSERT INTO download_group VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(product_id, group_id) DO UPDATE SET
                    name=excluded.name,
                    group_type=excluded.group_type,
                    content_type=excluded.content_type,
                    os=excluded.os,
                    language=excluded.language,
                    total_size=excluded.total_size
        """, group_rows)
        conn.executemany("""
            INSERT INTO download_file VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(product_id, group_id, file_id) DO UPDATE SET
                    size=excluded.size,
                    downlink=excluded.downlink
        """, file_rows)