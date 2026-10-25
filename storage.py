import sqlite3
from dataclasses import asdict


class PriceStorage:
    """История цен: каждая проверка добавляет строку, последняя строка по url — текущая цена."""

    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                price REAL NOT NULL,
                currency TEXT NOT NULL,
                scraped_at TEXT NOT NULL
            )"""
        )
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_prices_url ON prices(url)")

    def last_price(self, url: str) -> float | None:
        row = self.conn.execute(
            "SELECT price FROM prices WHERE url = ? ORDER BY id DESC LIMIT 1", (url,)
        ).fetchone()
        return row[0] if row else None

    def add(self, product) -> None:
        self.conn.execute(
            "INSERT INTO prices (url, title, price, currency, scraped_at) "
            "VALUES (:url, :title, :price, :currency, :scraped_at)",
            asdict(product),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
