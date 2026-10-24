"""Демо-магазин для проверки парсера: вход в кабинет и цены, которые видны только после входа.

Похож на настоящие сайты поставщиков:
- розничная цена есть в HTML всем;
- цена «для вас», остаток и срок доставки подгружаются скриптом и только с куки входа.
Запуск: python -m demo_shop.server  (адрес http://127.0.0.1:8765, вход demo / demo123)
"""

import html
import json
import secrets
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DEMO_LOGIN = "demo"
DEMO_PASSWORD = "demo123"

# Вымышленный каталог: артикул → данные товара
PRODUCTS = {
    "BG1001": {"name": "Дрель-шуруповёрт Berger 18 В", "retail": 7990, "price": 6420.5,
               "stock": "В магазине", "qty": 12, "delivery": "завтра"},
    "BG1002": {"name": "Болгарка Berger 125 мм", "retail": 5490, "price": 4380,
               "stock": "У поставщика", "qty": 40, "delivery": "3–5 дней"},
    "BG1003": {"name": "Перфоратор Berger SDS-plus", "retail": 11990, "price": 9870,
               "stock": "Под заказ", "qty": None, "delivery": "до 14 дней"},
    "BG1004": {"name": "Набор бит Berger, 32 шт.", "retail": 890, "price": 702,
               "stock": "Нет в наличии", "qty": 0, "delivery": "—"},
    "BG1005": {"name": "Лобзик Berger 650 Вт", "retail": 4290, "price": 3515,
               "stock": "В магазине", "qty": 3, "delivery": "сегодня"},
}

# Активные сессии: токен куки → логин
SESSIONS: dict[str, str] = {}

PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>{title}</title>
<style>body{{font-family:sans-serif;max-width:760px;margin:40px auto;padding:0 16px}}
header{{display:flex;justify-content:space-between;margin-bottom:24px}}
.price{{font-size:24px;font-weight:bold}} .error{{color:#b00}}</style></head>
<body><header><a href="/">Демо-инструмент</a>{user}</header>{body}</body></html>"""

PRODUCT_SCRIPT = """<script>
// Цена «для вас» приходит отдельным запросом и только вошедшим пользователям
setTimeout(async () => {
  const sku = document.body.dataset.sku;
  const r = await fetch('/api/offer?sku=' + encodeURIComponent(sku));
  if (r.status === 401) {
    document.querySelector('.price').textContent = 'Войдите, чтобы увидеть цену';
    return;
  }
  const o = await r.json();
  document.querySelector('.price').textContent = o.price.toLocaleString('ru-RU') + ' ₽';
  document.querySelector('.stock').textContent = o.stock;
  document.querySelector('.qty').textContent = o.qty === null ? '' : o.qty + ' шт.';
  document.querySelector('.delivery').textContent = o.delivery;
}, 300);
</script>"""


class Handler(BaseHTTPRequestHandler):
    """Обработчик запросов демо-магазина."""

    def log_message(self, format, *args):  # noqa: A002 — тихий режим для тестов
        pass

    # --- вспомогательное ---

    def _user(self) -> str | None:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        token = cookie.get("session")
        return SESSIONS.get(token.value) if token else None

    def _send(self, status: int, body: str, content_type="text/html; charset=utf-8",
              headers: dict | None = None) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _page(self, title: str, body: str, status: int = 200, body_attrs: str = "") -> None:
        user = self._user()
        user_html = (f'<span>{html.escape(user)} · <a class="logout" href="/logout">Выйти</a></span>'
                     if user else '<a href="/login">Войти</a>')
        page = PAGE.format(title=html.escape(title), user=user_html, body=body)
        if body_attrs:
            page = page.replace("<body>", f"<body {body_attrs}>", 1)
        self._send(status, page)

    # --- маршруты ---

    def do_GET(self):  # noqa: N802 — имя задаёт http.server
        url = urlparse(self.path)
        if url.path == "/":
            self._page("Главная", '<form action="/search"><input name="q" placeholder="Артикул">'
                                  '<button>Найти</button></form>')
        elif url.path == "/login":
            self._page("Вход", LOGIN_FORM.format(error=""))
        elif url.path == "/logout":
            self._send(302, "", headers={"Location": "/", "Set-Cookie": "session=; Max-Age=0; Path=/"})
        elif url.path == "/search":
            self._search(parse_qs(url.query).get("q", [""])[0].strip())
        elif url.path.startswith("/product/"):
            self._product(url.path.removeprefix("/product/"))
        elif url.path == "/api/offer":
            self._offer(parse_qs(url.query).get("sku", [""])[0])
        else:
            self._page("Нет такой страницы", "<p>404</p>", status=404)

    def do_POST(self):  # noqa: N802
        if urlparse(self.path).path != "/login":
            self._send(404, "")
            return
        length = int(self.headers.get("Content-Length", 0))
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        login = form.get("login", [""])[0]
        password = form.get("password", [""])[0]
        if login == DEMO_LOGIN and password == DEMO_PASSWORD:
            token = secrets.token_hex(16)
            SESSIONS[token] = login
            self._send(302, "", headers={"Location": "/",
                                         "Set-Cookie": f"session={token}; Path=/; HttpOnly"})
        else:
            self._page("Вход", LOGIN_FORM.format(
                error='<p class="error">Неверный логин или пароль</p>'), status=401)

    def _search(self, query: str) -> None:
        found = [sku for sku in PRODUCTS if query and query.upper() in sku]
        if not found:
            self._page("Поиск", f'<p class="empty">По запросу «{html.escape(query)}» ничего не найдено</p>')
            return
        items = "".join(
            f'<li><a class="product-link" href="/product/{sku}">{html.escape(PRODUCTS[sku]["name"])}</a></li>'
            for sku in found
        )
        self._page("Поиск", f"<ul>{items}</ul>")

    def _product(self, sku: str) -> None:
        product = PRODUCTS.get(sku)
        if not product:
            self._page("Нет товара", "<p>404</p>", status=404)
            return
        body = (
            f'<h1 class="title">{html.escape(product["name"])}</h1>'
            f'<p>Артикул: <span class="sku">{sku}</span></p>'
            f'<p>Розничная цена: <span class="retail">{product["retail"]} ₽</span></p>'
            '<p>Ваша цена: <span class="price"></span></p>'
            '<p>Наличие: <span class="stock"></span> <span class="qty"></span></p>'
            '<p>Доставка: <span class="delivery"></span></p>'
            + PRODUCT_SCRIPT
        )
        self._page(product["name"], body, body_attrs=f'data-sku="{sku}"')

    def _offer(self, sku: str) -> None:
        if not self._user():
            self._send(401, json.dumps({"error": "нужен вход"}), "application/json")
            return
        product = PRODUCTS.get(sku)
        if not product:
            self._send(404, json.dumps({"error": "нет товара"}), "application/json")
            return
        offer = {key: product[key] for key in ("price", "stock", "qty", "delivery")}
        self._send(200, json.dumps(offer, ensure_ascii=False), "application/json; charset=utf-8")


LOGIN_FORM = """<h1>Вход в кабинет</h1>{error}
<form method="post" action="/login">
<p><input id="login" name="login" placeholder="Логин"></p>
<p><input id="password" name="password" type="password" placeholder="Пароль"></p>
<button id="submit">Войти</button></form>"""


def start(port: int = 8765) -> ThreadingHTTPServer:
    """Запускает магазин в фоновом потоке (для тестов и демо)."""
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    print("Демо-магазин: http://127.0.0.1:8765  (вход demo / demo123), остановить — Ctrl+C")
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
