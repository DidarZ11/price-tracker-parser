import logging
from pathlib import Path
import aiohttp

log = logging.getLogger(__name__)
API = "https://api.telegram.org/bot{token}/{method}"


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str = ""):
        self.token = token
        self.chat_id = chat_id

    async def _call(self, session: aiohttp.ClientSession, method: str, **params) -> dict:
        async with session.post(API.format(token=self.token, method=method), json=params) as resp:
            data = await resp.json()
            if not data.get("ok"):
                raise RuntimeError(f"Telegram {method}: {data.get('description')}")
            return data["result"]

    async def resolve_chat_id(self, session: aiohttp.ClientSession, env_path: str = ".env") -> bool:
        """Бот не может писать первым: берём chat_id из последнего /start и запоминаем в .env."""
        if self.chat_id:
            return True
        updates = await self._call(session, "getUpdates")
        chats = [u["message"]["chat"]["id"] for u in updates if "message" in u]
        if not chats:
            log.warning("CHAT_ID не задан: напиши боту /start и запусти парсер ещё раз")
            return False
        self.chat_id = str(chats[-1])
        with open(env_path, "a", encoding="utf-8") as f:
            f.write(f"CHAT_ID={self.chat_id}\n")
        log.info("CHAT_ID=%s сохранён в %s", self.chat_id, env_path)
        return True

    async def send(self, text: str, document: str | None = None) -> None:
        async with aiohttp.ClientSession() as session:
            if not await self.resolve_chat_id(session):
                return
            await self._call(session, "sendMessage", chat_id=self.chat_id, text=text,
                             parse_mode="HTML", disable_web_page_preview=True)
            if document:
                form = aiohttp.FormData()
                form.add_field("chat_id", self.chat_id)
                form.add_field("document", Path(document).read_bytes(), filename=Path(document).name)
                async with session.post(API.format(token=self.token, method="sendDocument"), data=form) as resp:
                    if not (await resp.json()).get("ok"):
                        log.warning("не удалось отправить %s", document)
