import argparse
import asyncio
import csv
import html
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import aiohttp
from bs4 import BeautifulSoup
from config import BOT_TOKEN, CHAT_ID, DB_PATH
from notifier import TelegramNotifier
from storage import PriceStorage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


@dataclass
class Product:
    title: str
    price: float
    currency: str
    url: str
    scraped_at: str


class Parser:
    def __init__(self, concurrency: int = 5, timeout: int = 15):
        self.sem = asyncio.Semaphore(concurrency)
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (compatible; PriceTracker/1.0)"
        }

    async def fetch(self, session: aiohttp.ClientSession, url: str) -> str | None:
        async with self.sem:
            try:
                async with session.get(url, headers=self.headers) as resp:
                    resp.raise_for_status()
                    return await resp.text()
            except Exception as e:
                log.warning("fetch failed %s: %s", url, e)
                return None

    def parse_book(self, html: str, url: str) -> Product | None:
        soup = BeautifulSoup(html, "html.parser")
        title_tag = soup.find("h1")
        price_tag = soup.find("p", class_="price_color")
        if not title_tag or not price_tag:
            return None
        raw_price = price_tag.text.strip()
        price = float("".join(c for c in raw_price if c.isdigit() or c == "."))
        return Product(
            title=title_tag.text.strip(),
            price=price,
            currency="GBP",
            url=url,
            scraped_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    async def scrape(self, urls: list[str]) -> list[Product]:
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            htmls = await asyncio.gather(*(self.fetch(session, u) for u in urls))
            products = []
            for url, html in zip(urls, htmls):
                if html is None:
                    continue
                prod = self.parse_book(html, url)
                if prod:
                    products.append(prod)
            return products


def save_csv(products: list[Product], path: str):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["title", "price", "currency", "url", "scraped_at"])
        writer.writeheader()
        for p in products:
            writer.writerow(asdict(p))


URLS = [
    f"https://books.toscrape.com/catalogue/{slug}/index.html"
    for slug in (
        "a-light-in-the-attic_1000",
        "tipping-the-velvet_999",
        "soumission_998",
        "sharp-objects_997",
        "sapiens-a-brief-history-of-humankind_996",
    )
]


@dataclass
class PriceChange:
    product: Product
    old_price: float

    @property
    def percent(self) -> float:
        return (self.product.price - self.old_price) / self.old_price * 100


def track(products: list[Product], storage: PriceStorage) -> tuple[list[PriceChange], list[Product]]:
    """Сравнивает с последней сохранённой ценой и пишет новую точку в историю."""
    changes, new = [], []
    for p in products:
        old = storage.last_price(p.url)
        if old is None:
            new.append(p)
        elif old != p.price:
            changes.append(PriceChange(p, old))
        storage.add(p)
    return changes, new


def format_report(changes: list[PriceChange], new: list[Product]) -> str:
    lines = []
    if changes:
        lines.append("<b>Изменились цены:</b>")
        for c in changes:
            arrow = "📉" if c.percent < 0 else "📈"
            lines.append(
                f'{arrow} <a href="{c.product.url}">{html.escape(c.product.title)}</a>: '
                f"{c.old_price:.2f} → {c.product.price:.2f} {c.product.currency} ({c.percent:+.1f}%)"
            )
    if new:
        if lines:
            lines.append("")
        lines.append(f"<b>Начал отслеживать {len(new)} товаров:</b>")
        lines += [f"• {html.escape(p.title)} — {p.price:.2f} {p.currency}" for p in new]
    return "\n".join(lines)


async def run_once(parser: Parser, storage: PriceStorage, notifier: TelegramNotifier | None):
    products = await parser.scrape(URLS)
    save_csv(products, "products.csv")
    changes, new = track(products, storage)
    log.info("scraped %d products: %d price changes, %d new", len(products), len(changes), len(new))
    if notifier and (changes or new):
        await notifier.send(format_report(changes, new), document="products.csv")


async def main():
    ap = argparse.ArgumentParser(description="Трекер цен с уведомлениями в Telegram")
    ap.add_argument("--every", type=int, metavar="MIN", help="повторять проверку каждые MIN минут")
    args = ap.parse_args()

    parser = Parser(concurrency=5)
    storage = PriceStorage(DB_PATH)
    notifier = TelegramNotifier(BOT_TOKEN, CHAT_ID) if BOT_TOKEN else None
    if notifier is None:
        log.warning("BOT_TOKEN не задан — уведомления в Telegram отключены")
    try:
        while True:
            await run_once(parser, storage, notifier)
            if not args.every:
                break
            log.info("следующая проверка через %d мин", args.every)
            await asyncio.sleep(args.every * 60)
    finally:
        storage.close()


if __name__ == "__main__":
    asyncio.run(main())
