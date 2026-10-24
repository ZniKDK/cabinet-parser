"""Проход по списку артикулов: повторы, продолжение после сбоя, снимки ошибок."""

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError

from cabinet_parser.browser import CabinetBrowser, SessionExpired
from cabinet_parser.config import SiteConfig
from cabinet_parser.excel_io import ResultWriter, read_rows

log = logging.getLogger(__name__)

SAVE_EVERY = 10   # сохранять Excel каждые N товаров, чтобы при сбое не потерять работу


@dataclass
class RunReport:
    total: int = 0
    skipped: int = 0
    ok: int = 0
    not_found: int = 0
    errors: int = 0


def _short(error: Exception) -> str:
    """Первая строка ошибки Playwright без простыни логов."""
    return str(error).strip().splitlines()[0][:150] if str(error).strip() else type(error).__name__


def run(cfg: SiteConfig, input_path: Path, output_path: Path, state_path: Path,
        username: str, password: str, headless: bool = True, progress=None) -> RunReport:
    """Собирает данные по всем артикулам из input_path в output_path.

    progress — необязательная функция (номер, всего, артикул, статус) для вывода хода работы.
    """
    rows = read_rows(input_path, cfg.input_column, cfg.input_sheet, keep=list(cfg.input_keep))
    extras = dict(rows)
    skus = [sku for sku, _ in rows]
    writer = ResultWriter(output_path, [(f.name, f.title) for f in cfg.fields], input_columns=list(cfg.input_keep))
    report = RunReport(total=len(skus))
    todo = [sku for sku in skus if sku not in writer.done]
    report.skipped = len(skus) - len(todo)
    if not todo:
        return report

    errors_dir = Path(output_path).parent / "errors"
    with CabinetBrowser(cfg, state_path, headless) as browser:
        browser.ensure_logged_in(username, password)
        try:
            for number, sku in enumerate(todo, 1):
                status, url, values = _scrape_with_retries(browser, cfg, sku, username, password, errors_dir)
                writer.add(sku, values, status, url, extra=extras.get(sku))
                if status == "ok":
                    report.ok += 1
                elif status == "не найден":
                    report.not_found += 1
                else:
                    report.errors += 1
                if progress:
                    progress(number, len(todo), sku, status)
                if number % SAVE_EVERY == 0:
                    writer.save()
                if number < len(todo):
                    time.sleep(cfg.delay_sec)
        finally:
            # Даже при Ctrl+C или падении уже собранное сохраняется
            writer.save()
    return report


def _scrape_with_retries(browser: CabinetBrowser, cfg: SiteConfig, sku: str,
                         username: str, password: str, errors_dir: Path) -> tuple[str, str, dict]:
    relogged = False
    last_error = "неизвестная ошибка"
    for attempt in range(cfg.retries + 1):
        try:
            result = browser.scrape(sku)
            return result.status, result.url, result.values
        except SessionExpired:
            # Вход «слетел» — входим заново один раз и пробуем ещё
            if relogged:
                return "ошибка: сайт сбрасывает вход", browser.page.url, {}
            log.warning("Сессия истекла на %s — вхожу заново", sku)
            browser.login(username, password)
            relogged = True
        except PlaywrightError as error:
            last_error = _short(error)
            log.warning("%s, попытка %s: %s", sku, attempt + 1, last_error)
            safe_name = re.sub(r"[^\w.-]", "_", sku)
            browser.screenshot(errors_dir / f"{safe_name}.png")
            time.sleep(cfg.delay_sec)
    return f"ошибка: {last_error}", browser.page.url, {}
