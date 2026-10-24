"""Описание сайта в YAML: где вход, где поиск, какие поля собирать.

Под новый сайт код не меняется — пишется только новый YAML с CSS-селекторами.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from cabinet_parser.extract import FIELD_TYPES


class ConfigError(Exception):
    """Ошибка в описании сайта; текст понятен человеку."""


@dataclass(frozen=True)
class LoginConfig:
    """Как войти в кабинет."""

    url: str              # страница входа (можно относительно base_url)
    username: str         # селектор поля логина
    password: str         # селектор поля пароля
    submit: str           # селектор кнопки «Войти»
    logged_in: str        # селектор, который есть на странице только после входа


@dataclass(frozen=True)
class FieldConfig:
    """Одно поле, которое собираем со страницы товара."""

    name: str
    selector: str
    title: str            # заголовок колонки в Excel
    type: str = "text"    # text | money | int
    attr: str | None = None   # взять атрибут (например, href), а не текст
    regex: str | None = None  # вырезать часть текста
    wait: bool = False    # ждать, пока скрипт страницы заполнит поле


@dataclass(frozen=True)
class SiteConfig:
    base_url: str
    search_url: str                   # шаблон с {sku}
    fields: list[FieldConfig]
    login: LoginConfig | None = None
    first_result: str | None = None   # ссылка на товар в выдаче; None — поиск сразу ведёт на товар
    not_found: str | None = None      # селектор «ничего не найдено»
    input_column: str = "Артикул"
    input_sheet: str | None = None
    input_keep: tuple[str, ...] | list[str] = ()   # колонки входного файла, которые перенести в результат
    schedule_sec: int | None = None                 # запуск по расписанию: раз в N секунд
    delay_sec: float = 1.5
    timeout_sec: float = 20
    retries: int = 2

    def absolute(self, url: str) -> str:
        """Относительный адрес → полный, с base_url."""
        return url if url.startswith("http") else self.base_url.rstrip("/") + "/" + url.lstrip("/")


MIN_SCHEDULE_SEC = 10 * 60
_UNITS = {"m": 60, "h": 3600, "d": 86400}


def parse_interval(text: str) -> int:
    """«30m», «6h», «1d» → секунды. Не чаще раза в 10 минут."""
    match = re.fullmatch(r"\s*(\d+)\s*([mhd])\s*", str(text or ""))
    if not match:
        raise ConfigError(f"Интервал «{text}»: нужно число и единица — 30m, 6h или 1d")
    seconds = int(match.group(1)) * _UNITS[match.group(2)]
    if seconds < MIN_SCHEDULE_SEC:
        raise ConfigError("Интервал расписания — не меньше 10 минут (10m)")
    return seconds


def _require(data: dict, key: str, where: str):
    if key not in data or data[key] in (None, ""):
        raise ConfigError(f"В разделе {where} нет обязательного параметра «{key}»")
    return data[key]


def load_config(path: Path) -> SiteConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Файл описания сайта не найден: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        raise ConfigError(f"Ошибка в YAML: {error}") from error

    search = _require(data, "search", "верхнего уровня")
    search_url = _require(search, "url", "search")
    if "{sku}" not in search_url:
        raise ConfigError("search.url должен содержать {sku} — туда подставляется артикул")

    login = None
    if data.get("login"):
        raw = data["login"]
        login = LoginConfig(**{key: _require(raw, key, "login")
                               for key in ("url", "username", "password", "submit", "logged_in")})

    fields = []
    for name, raw in (_require(data, "fields", "верхнего уровня") or {}).items():
        raw = raw or {}
        field_type = raw.get("type", "text")
        if field_type not in FIELD_TYPES:
            raise ConfigError(f"Поле «{name}»: type должен быть одним из {', '.join(FIELD_TYPES)}")
        fields.append(FieldConfig(
            name=name,
            selector=_require(raw, "selector", f"fields.{name}"),
            title=raw.get("title", name),
            type=field_type,
            attr=raw.get("attr"),
            regex=raw.get("regex"),
            wait=bool(raw.get("wait", False)),
        ))

    input_cfg = data.get("input") or {}
    cfg = SiteConfig(
        base_url=_require(data, "base_url", "верхнего уровня"),
        search_url=search_url,
        fields=fields,
        login=login,
        first_result=search.get("first_result"),
        not_found=search.get("not_found"),
        input_column=input_cfg.get("column", "Артикул"),
        input_sheet=input_cfg.get("sheet"),
        input_keep=list(input_cfg.get("keep") or []),
        schedule_sec=parse_interval(data["schedule"]) if data.get("schedule") else None,
        delay_sec=float(data.get("delay_sec", 1.5)),
        timeout_sec=float(data.get("timeout_sec", 20)),
        retries=int(data.get("retries", 2)),
    )
    # Вежливость к чужому сайту: слишком частые запросы ведут к блокировке
    if cfg.delay_sec < 0.5:
        raise ConfigError("delay_sec — не меньше 0.5 секунды между товарами")
    if cfg.retries < 0:
        raise ConfigError("retries не может быть отрицательным")
    return cfg
