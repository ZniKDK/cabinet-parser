"""Очистка текста со страницы и перевод в числа."""

import re
from decimal import Decimal, InvalidOperation

# Число с пробелами-разделителями тысяч и дробной частью через точку или запятую
_NUMBER_RE = re.compile(r"\d[\d\s  ]*(?:[.,]\d+)?")

FIELD_TYPES = ("text", "money", "int")


def clean_text(text: str | None) -> str:
    """Схлопывает переводы строк и неразрывные пробелы в обычные одиночные пробелы."""
    return re.sub(r"\s+", " ", (text or "").replace(" ", " ")).strip()


def _number(text: str) -> str | None:
    match = _NUMBER_RE.search(text or "")
    if not match:
        return None
    return re.sub(r"[\s  ]", "", match.group()).replace(",", ".")


def parse_money(text: str | None) -> Decimal | None:
    """«6 420,5 ₽» → Decimal("6420.5"); нет числа → None. Decimal — чтобы не терять копейки."""
    raw = _number(text or "")
    if raw is None:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def parse_int(text: str | None) -> int | None:
    """«12 шт.» → 12; нет числа → None."""
    raw = _number(text or "")
    return int(Decimal(raw)) if raw is not None else None


def convert(text: str | None, field_type: str, regex: str | None) -> str | Decimal | int | None:
    """Готовит значение поля: сначала регулярное выражение (если задано), потом тип.

    В regex можно указать группу в скобках — тогда берётся она, иначе всё совпадение.
    """
    value = clean_text(text)
    if regex:
        match = re.search(regex, value)
        if not match:
            return None
        value = match.group(1) if match.groups() else match.group()
    if field_type == "money":
        return parse_money(value)
    if field_type == "int":
        return parse_int(value)
    return value
