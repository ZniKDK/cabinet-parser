"""Тесты командной строки без браузера."""

from cabinet_parser.cli import main, rotate_previous


def test_rotate_previous(tmp_path):
    out = tmp_path / "result.xlsx"
    assert rotate_previous(out) is None
    out.write_text("старое")
    prev = rotate_previous(out)
    assert prev.name == "result_prev.xlsx" and prev.read_text() == "старое"
    assert not out.exists()


def test_bad_schedule_is_reported(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    site = tmp_path / "s.yaml"
    site.write_text("base_url: https://x.ru\nsearch: {url: '/s?q={sku}'}\nfields: {p: {selector: .p}}\n", encoding="utf-8")
    code = main(["run", "--site", str(site), "--input", "in.xlsx", "--output", "o.xlsx", "--every", "5m"])
    assert code == 2
    assert "10 минут" in capsys.readouterr().err
