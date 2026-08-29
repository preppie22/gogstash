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

    

