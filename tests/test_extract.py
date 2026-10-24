"""Тесты очистки текста и разбора чисел."""

from decimal import Decimal

import pytest

from cabinet_parser.extract import clean_text, convert, parse_money, parse_int


def test_clean_text_spaces():
    assert clean_text("  Дрель\n  Berger 18 В ") == "Дрель Berger 18 В"


@pytest.mark.parametrize("text, expected", [
    ("6 420,5 ₽", Decimal("6420.5")),
    ("12 345.00 руб.", Decimal("12345.00")),
    ("Цена: 702 ₽", Decimal("702")),
    ("Войдите, чтобы увидеть цену", None),
    ("", None),
])
def test_parse_money(text, expected):
    assert parse_money(text) == expected


def test_parse_int():
    assert parse_int("12 шт.") == 12
    assert parse_int("нет") is None


def test_convert_with_regex():
    assert convert("Артикул: BG-1001 (новинка)", "text", r"BG-\d+") == "BG-1001"
    assert convert("Срок: 3 дня", "text", r"Срок: (.+)") == "3 дня"


def test_convert_types():
    assert convert("4 380 ₽", "money", None) == Decimal("4380")
    assert convert("40 шт.", "int", None) == 40
    assert convert(" В магазине ", "text", None) == "В магазине"
