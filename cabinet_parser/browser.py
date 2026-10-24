"""Работа с браузером: вход в кабинет, сохранение сессии, сбор полей со страницы товара.

Используется Playwright (настоящий Chromium), поэтому работают сайты, где цена
дорисовывается скриптом или видна только после входа.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from cabinet_parser.config import SiteConfig
from cabinet_parser.extract import convert

log = logging.getLogger(__name__)

MANUAL_LOGIN_MIN = 5   # сколько минут ждать ручного входа


class LoginError(Exception):
    """Не удалось войти в кабинет; текст подсказывает, что делать."""


class SessionExpired(Exception):
    """Сайт «забыл» вход посреди работы — нужно войти заново."""


@dataclass
class ScrapeResult:
    status: str                       # ok | не найден
    url: str
    values: dict = field(default_factory=dict)


class CabinetBrowser:
    """Браузер с одной вкладкой. Используется через with: браузер закроется сам."""

    def __init__(self, cfg: SiteConfig, state_path: Path, headless: bool = True) -> None:
        self.cfg = cfg
        self.state_path = Path(state_path)
        self.headless = headless

    def __enter__(self) -> "CabinetBrowser":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        # Сохранённая сессия (куки) — чтобы не входить каждый раз и не ловить капчу
        state = str(self.state_path) if self.state_path.exists() else None
        self._context = self._browser.new_context(storage_state=state, locale="ru-RU")
        self._context.set_default_timeout(self.cfg.timeout_sec * 1000)
        self.page = self._context.new_page()
        return self

    def __exit__(self, *exc) -> None:
        self._context.close()
        self._browser.close()
        self._pw.stop()

    # --- вход ---

    def _save_session(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._context.storage_state(path=str(self.state_path))

    def is_logged_in(self) -> bool:
        return self.cfg.login is None or self.page.locator(self.cfg.login.logged_in).count() > 0

    def ensure_logged_in(self, username: str, password: str) -> None:
        """Проверяет сохранённую сессию, при необходимости входит по логину и паролю."""
        if self.cfg.login is None:
            return
        self.page.goto(self.cfg.base_url, wait_until="domcontentloaded")
        if self.is_logged_in():
            log.info("Сохранённая сессия действует")
            return
        self.login(username, password)

    def login(self, username: str, password: str) -> None:
        login = self.cfg.login
        if not username or not password:
            raise LoginError("Нет логина или пароля: заполните CABINET_LOGIN и CABINET_PASSWORD в .env "
                             "или войдите вручную командой login --manual")
        self.page.goto(self.cfg.absolute(login.url), wait_until="domcontentloaded")
        self.page.fill(login.username, username)
        self.page.fill(login.password, password)
        self.page.click(login.submit)
        try:
            self.page.locator(login.logged_in).first.wait_for()
        except PlaywrightTimeout:
            raise LoginError("Вход не удался: неверный логин или пароль, либо сайт просит капчу или код. "
                             "Попробуйте войти вручную: login --manual") from None
        self._save_session()
        log.info("Вход выполнен, сессия сохранена в %s", self.state_path)

    def manual_login(self) -> None:
        """Открывает страницу входа и ждёт, пока человек войдёт сам (капча, SMS и т. п.)."""
        if self.cfg.login is None:
            raise LoginError("В описании сайта нет раздела login")
        self.page.goto(self.cfg.absolute(self.cfg.login.url))
        try:
            self.page.locator(self.cfg.login.logged_in).first.wait_for(
                timeout=MANUAL_LOGIN_MIN * 60 * 1000)
        except PlaywrightTimeout:
            raise LoginError(f"За {MANUAL_LOGIN_MIN} минут вход не выполнен") from None
        self._save_session()

    # --- сбор ---

    def scrape(self, sku: str) -> ScrapeResult:
        """Ищет товар по артикулу и собирает поля. Ошибки Playwright пробрасывает."""
        cfg = self.cfg
        search_url = cfg.absolute(cfg.search_url.format(sku=quote(sku)))
        self.page.goto(search_url, wait_until="domcontentloaded")

        if cfg.first_result:
            # Ждём либо ссылку на товар, либо надпись «ничего не найдено»
            targets = ", ".join(s for s in (cfg.first_result, cfg.not_found) if s)
            self.page.locator(targets).first.wait_for()
            if cfg.not_found and self.page.locator(cfg.not_found).count() > 0:
                return ScrapeResult("не найден", self.page.url)
            href = self.page.locator(cfg.first_result).first.get_attribute("href")
            self.page.goto(cfg.absolute(href), wait_until="domcontentloaded")
        elif cfg.not_found and self.page.locator(cfg.not_found).count() > 0:
            return ScrapeResult("не найден", self.page.url)

        if not self.is_logged_in():
            raise SessionExpired()

        values = {}
        for fld in cfg.fields:
            if fld.wait:
                # Поле заполняет скрипт страницы: ждём, пока в нём появится текст
                self.page.locator(f"{fld.selector}:not(:empty)").first.wait_for()
            element = self.page.locator(fld.selector).first
            if element.count() == 0:
                values[fld.name] = None
                continue
            raw = element.get_attribute(fld.attr) if fld.attr else element.inner_text()
            values[fld.name] = convert(raw, fld.type, fld.regex)
        return ScrapeResult("ok", self.page.url, values)

    def screenshot(self, path: Path) -> None:
        """Снимок страницы при ошибке — по нему видно, что пошло не так."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(path), full_page=True)
        except PlaywrightError:
            log.warning("Не удалось сохранить снимок %s", path)
