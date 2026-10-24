"""Командная строка: python -m cabinet_parser <команда>."""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from openpyxl import Workbook

from cabinet_parser.browser import CabinetBrowser, LoginError
from cabinet_parser.config import ConfigError, load_config, parse_interval
from cabinet_parser.excel_io import ExcelError
from cabinet_parser.runner import run

DATA = Path("data")


def _session_path(site: Path) -> Path:
    """Сессия хранится отдельно для каждого сайта: data/sessions/<имя yaml>.json."""
    return DATA / "sessions" / f"{Path(site).stem}.json"


def _print_progress(number: int, total: int, sku: str, status: str) -> None:
    print(f"[{number}/{total}] {sku}: {status}", flush=True)


def _print_report(report, output: Path) -> None:
    print(f"\nГотово. Всего артикулов: {report.total}, уже были: {report.skipped}, "
          f"собрано: {report.ok}, не найдено: {report.not_found}, ошибок: {report.errors}")
    print(f"Результат: {output.resolve()}")
    if report.errors:
        print("Снимки страниц с ошибками — в папке errors рядом с результатом. "
              "Повторный запуск доберёт только недостающие артикулы.")


def rotate_previous(output: Path) -> Path | None:
    """Перед плановым запуском прошлый результат становится «…_prev.xlsx», новый собирается заново."""
    if not output.exists():
        return None
    previous = output.with_name(f"{output.stem}_prev{output.suffix}")
    output.replace(previous)
    return previous


def cmd_run(args) -> int:
    cfg = load_config(args.site)
    load_dotenv(Path(".env"))
    interval = parse_interval(args.every) if args.every else (cfg.schedule_sec if args.scheduled else None)

    def once() -> None:
        report = run(cfg, args.input, args.output, _session_path(args.site),
                     os.getenv("CABINET_LOGIN", ""), os.getenv("CABINET_PASSWORD", ""),
                     headless=not args.headed, progress=_print_progress)
        _print_report(report, args.output)

    if interval is None:
        once()
        return 0
    # Режим по расписанию: окно можно свернуть, работает до Ctrl+C
    while True:
        rotate_previous(args.output)
        once()
        next_at = datetime.now() + timedelta(seconds=interval)
        print(f"Следующий запуск: {next_at:%d.%m %H:%M}", flush=True)
        time.sleep(interval)


def cmd_login(args) -> int:
    """Ручной вход: окно браузера открывается, человек входит сам, сессия сохраняется."""
    cfg = load_config(args.site)
    print(f"Откроется браузер. Войдите в кабинет (до 5 минут), дальше всё сделаю сам.")
    with CabinetBrowser(cfg, _session_path(args.site), headless=False) as browser:
        browser.manual_login()
    print(f"Сессия сохранена: {_session_path(args.site)}")
    return 0


def cmd_demo(args) -> int:
    """Полный прогон на встроенном демо-магазине — без настроек и паролей."""
    from demo_shop.server import DEMO_LOGIN, DEMO_PASSWORD, start

    server = start(8765)
    DATA.mkdir(exist_ok=True)
    source = DATA / "demo_input.xlsx"
    wb = Workbook()
    wb.active.append(["Артикул", "Комментарий"])
    for sku in ["BG1001", "BG1002", "BG1003", "BG1004", "BG1005", "BG7777"]:
        wb.active.append([sku, "демо"])
    wb.save(source)
    output = DATA / "demo_result.xlsx"
    output.unlink(missing_ok=True)
    site = Path(__file__).resolve().parent.parent / "examples" / "demo_shop.yaml"
    try:
        report = run(load_config(site), source, output, DATA / "sessions" / "demo.json",
                     DEMO_LOGIN, DEMO_PASSWORD, headless=not args.headed, progress=_print_progress)
    finally:
        server.shutdown()
    _print_report(report, output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cabinet_parser",
                                     description="Сбор цен и наличия из личного кабинета сайта по артикулам из Excel")
    commands = parser.add_subparsers(dest="command", required=True)

    p_run = commands.add_parser("run", help="собрать данные по артикулам")
    p_run.add_argument("--site", type=Path, required=True, help="описание сайта (YAML)")
    p_run.add_argument("--input", type=Path, required=True, help="Excel с артикулами")
    p_run.add_argument("--output", type=Path, required=True, help="куда записать результат")
    p_run.add_argument("--headed", action="store_true", help="показывать окно браузера")
    p_run.add_argument("--every", help="повторять по расписанию: 30m, 6h, 1d")
    p_run.add_argument("--scheduled", action="store_true", help="повторять с интервалом schedule из YAML")
    p_run.set_defaults(func=cmd_run)

    p_login = commands.add_parser("login", help="войти вручную (капча, код из SMS)")
    p_login.add_argument("--site", type=Path, required=True)
    p_login.add_argument("--manual", action="store_true", required=True)
    p_login.set_defaults(func=cmd_login)

    p_demo = commands.add_parser("demo", help="прогон на встроенном демо-магазине")
    p_demo.add_argument("--headed", action="store_true")
    p_demo.set_defaults(func=cmd_demo)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")   # консоль Windows и символы вроде «₽»
    DATA.mkdir(exist_ok=True)
    logging.basicConfig(filename=DATA / "cabinet-parser.log", encoding="utf-8", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, ExcelError, LoginError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nОстановлено. Собранное сохранено, повторный запуск продолжит с того же места.")
        return 130
