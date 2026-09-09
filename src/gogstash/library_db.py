import sqlite3
from gogstash import paths

def _create_db(force: bool = False) -> None:
    db_path = paths.config_file_path(paths.ConfigFile.DB_CACHE)
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
                product_url TEXT,
                image_uri TEXT,
                windows INT2,
                linux INT2,
                osx INT2
            );
            CREATE TABLE download_group(
                product_id BIGINT,
                group_id TEXT,
                name TEXT,
                category TEXT,
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
                checksum TEXT,
                timestamp DATETIME,
                PRIMARY KEY (product_id, group_id, file_id),
                FOREIGN KEY (product_id, group_id) REFERENCES download_group(product_id, group_id)
            );
        """)

def update_products(products: list[dict]) -> None:
    db_path = paths.config_file_path(paths.ConfigFile.DB_CACHE)
    if not db_path.exists():
        _create_db()
    rows = [
        (
            product["id"],
            product["title"],
            product["slug"],
            "movie" if product["isMovie"] else "game",
            f"https://www.gog.com{product['url']}",
            product['image'],
            product["worksOn"]["Windows"],
            product["worksOn"]["Linux"],
            product["worksOn"]["Mac"],
        )
        for product in products
    ]
    with sqlite3.connect(db_path) as conn:
        conn.executemany("INSERT OR IGNORE INTO product VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)

def update_downloadables(downloadables: list[dict]) -> None:
    db_path = paths.config_file_path(paths.ConfigFile.DB_CACHE)
    if not db_path.exists():
        _create_db()
    group_rows = []
    file_rows = []
    categories = ['installers', 'patches', 'language_packs', 'bonus_content']
    for content in downloadables:
        downloads: dict = content.get('downloads', [])
        for category in categories:
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
                    category=excluded.category,
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

def get_product_listing(product_id: tuple[int] = ()) -> list[dict]:
    db_path = paths.config_file_path(paths.ConfigFile.DB_CACHE)
    if not db_path.exists():
        return []
    query_result = None
    with sqlite3.connect(db_path) as conn:
        where_block = ""
        if product_id:
            where_block = f"WHERE p.product_id IN ({','.join("?" * len(product_id))})"
        query_result = conn.execute(f"""
            SELECT
                p.product_id,
                p.title,
                p.slug,
                COALESCE(dg.download_size, 0) as download_size,
                COALESCE(ff.fetched_size, 0) as fetched_size,
                CASE WHEN ff.fetched_size IS NOT NULL THEN 1 ELSE 0 END AS fetched
            FROM product p
            LEFT JOIN (
                SELECT product_id, SUM(total_size) AS download_size
                FROM download_group
                GROUP BY product_id
            ) dg ON dg.product_id = p.product_id
            LEFT JOIN (
                SELECT product_id, SUM(size) AS fetched_size
                FROM fetched_files
                GROUP BY product_id
            ) ff ON ff.product_id = p.product_id
            {where_block}
        """, product_id)
    products = [{
        'product_id': p[0],
        'title': p[1],
        'slug': p[2],
        'download_size': p[3],
        'fetched_size': p[4],
        'fetched': p[5]
    } for p in query_result]
    return products

def get_downloadables(product_id: tuple[int] = ()) -> list[dict]:
    db_path = paths.config_file_path(paths.ConfigFile.DB_CACHE)
    if not db_path.exists():
        return []
    query_result = None
    with sqlite3.connect(db_path) as conn:
        where_block = ""
        if product_id:
            where_block = f"WHERE df.product_id IN ({','.join("?" * len(product_id))})"
        query_result = conn.execute(f"""
            SELECT
                dg.product_id,
                dg.category,
                df.group_id,
                df.file_id,
                df.size,
                dg.os,
                df.downlink
            FROM download_file df
            LEFT JOIN download_group dg ON
                df.product_id = dg.product_id AND
                df.group_id = dg.group_id
            {where_block}
        """, product_id)
       
    downloadables = [{
        'product_id': p[0],
        'category': p[1],
        'group_id': p[2],
        'file_id': p[3],
        'file_size': p[4],
        'os': p[5],
        'downlink': p[6]
    } for p in query_result]
    return downloadables

def get_cache_size() -> int:
    db_file = paths.config_file_path(paths.ConfigFile.DB_CACHE)
    if not db_file.exists():
        return 0
    else:
        return db_file.stat().st_size

def clear_cache() -> None:
    db_file = paths.config_file_path(paths.ConfigFile.DB_CACHE)
    if not db_file.exists():
        return
    backup_file = paths.config_file_backup(paths.ConfigFile.DB_CACHE)
    backup_file.unlink(missing_ok=True)
    db_file.rename(paths.config_file_backup(paths.ConfigFile.DB_CACHE))


if __name__ == "__main__":
    clear_cache()