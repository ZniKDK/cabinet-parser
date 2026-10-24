"""Тесты загрузки описания сайта (YAML)."""

from pathlib import Path

import pytest

from cabinet_parser.config import ConfigError, load_config, parse_interval

EXAMPLE = Path(__file__).parent.parent / "examples" / "demo_shop.yaml"


def write(tmp_path, text):
    path = tmp_path / "site.yaml"
    path.write_text(text, encoding="utf-8")
    return path


MINIMAL = """
base_url: https://example.com
search:
  url: /search?q={sku}
fields:
  price: {selector: .price, type: money}
"""


def test_example_loads():
    cfg = load_config(EXAMPLE)
    assert cfg.base_url == "http://127.0.0.1:8765"
    assert cfg.login is not None and cfg.login.username == "#login"
    assert [f.name for f in cfg.fields] == ["name", "price", "stock", "qty", "delivery"]
    assert cfg.fields[1].type == "money" and cfg.fields[1].wait


def test_minimal_defaults(tmp_path):
    cfg = load_config(write(tmp_path, MINIMAL))
    assert cfg.login is None
    assert cfg.delay_sec == 1.5
    assert cfg.retries == 2
    assert cfg.input_column == "Артикул"
    assert cfg.fields[0].title == "price"


def test_search_url_needs_placeholder(tmp_path):
    with pytest.raises(ConfigError, match="{sku}"):
        load_config(write(tmp_path, MINIMAL.replace("{sku}", "")))


def test_unknown_field_type(tmp_path):
    with pytest.raises(ConfigError, match="type"):
        load_config(write(tmp_path, MINIMAL.replace("money", "color")))


def test_delay_too_small(tmp_path):
    with pytest.raises(ConfigError, match="delay_sec"):
        load_config(write(tmp_path, MINIMAL + "delay_sec: 0.1\n"))


@pytest.mark.parametrize("text, seconds", [("30m", 1800), ("6h", 21600), ("1d", 86400), (" 2 h ", 7200)])
def test_parse_interval(text, seconds):
    assert parse_interval(text) == seconds


@pytest.mark.parametrize("text", ["90", "5m", "час", ""])
def test_parse_interval_bad(text):
    with pytest.raises(ConfigError):
        parse_interval(text)


def test_schedule_and_keep_columns(tmp_path):
    cfg = load_config(write(tmp_path, MINIMAL + "schedule: 6h\ninput:\n  column: Код\n  keep: [Название, Бренд]\n"))
    assert cfg.schedule_sec == 21600
    assert cfg.input_column == "Код"
    assert cfg.input_keep == ["Название", "Бренд"]


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="не найден"):
        load_config(tmp_path / "nope.yaml")
