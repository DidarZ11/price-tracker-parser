import asyncio
import csv
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
import aiohttp
from bs4 import BeautifulSoup

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
            scraped_at=datetime.utcnow().isoformat(),
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


async def main():
    base = "https://books.toscrape.com/catalogue/"
    urls = [
        f"{base}a-light-in-the-attic_1000/index.html",
        f"{base}tipping-the-velvet_999/index.html",
        f"{base}soumission_998/index.html",
        f"{base}sharp-objects_997/index.html",
        f"{base}sapiens-a-brief-history-of-humankind_996/index.html",
    ]
    parser = Parser(concurrency=5)
    products = await parser.scrape(urls)
    save_csv(products, "products.csv")
    log.info("scraped %d products", len(products))


if __name__ == "__main__":
    asyncio.run(main())
