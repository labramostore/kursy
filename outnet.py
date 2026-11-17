"""Сборщик THE OUTNET (раздел Sale, США, доллары). Без ИИ, без обхода защиты.

Открывает страницу распродажи в обычном браузере, листает кнопкой «Load more» и берёт карточки товаров:
название, бренд, цена сейчас, старая цена. В файл попадают только товары, где цена сейчас ниже старой.
Размеры пока не собираем (у сайта нет открытого списка размеров на карточке); это отметим в итоге.

Запуск:  venv/bin/python outnet.py            (весь Sale, до MAX_PAGES порций)
         venv/bin/python outnet.py 1          (только первая порция, для проверки)
Результат: данные/sale_outnet.json
"""
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

import правила_отбора
from универсальный import write_top_csv

DIR = Path(__file__).parent
OUT = DIR / "данные"
BASE = "https://theoutnet.com"
PATH = "/en-us/collections/sale"
MAX_PAGES = 40        # потолок: 40 нажатий «Load more»
PAUSE = 2.0           # пауза между нажатиями, секунды

PRICE = re.compile(r"\$\s?([\d,]+(?:\.\d{2})?)")


def parse_card(text):
    """Из текста карточки достаёт цену сейчас и старую цену. Возвращает (now, was) или None."""
    prices = [float(p.replace(",", "")) for p in PRICE.findall(text)]
    if len(prices) < 2:
        return None
    now, was = prices[0], prices[1]
    if not (was > now > 0):
        return None
    return now, was


EXTRACT = """() => {
  // Ссылка на картинку идёт первой, текст (название, цены) лежит в соседнем блоке той же карточки.
  // Поднимаемся от ссылки, пока не найдём блок с ценой и разумной длиной текста.
  const seen = new Map();
  document.querySelectorAll('a[href*="/en-us/products/"]').forEach(a => {
    const href = a.href.split('?')[0];
    let el = a, text = '';
    for (let i = 0; i < 6 && el; i++) {
      const t = (el.textContent || '').replace(/\\s+/g, ' ').trim();
      if (t.includes('$') && t.length < 400) { text = t; break; }
      el = el.parentElement;
    }
    const existing = seen.get(href);
    if (existing && existing.text) return;
    const img = a.querySelector('img') || (el ? el.querySelector('img') : null);
    seen.set(href, { href, text, img: img ? (img.currentSrc || img.src) : '' });
  });
  return [...seen.values()];
}"""


def collect(limit_pages=MAX_PAGES):
    rows, seen_links = [], set()
    stat = {"сайт": "THE OUTNET", "страниц": 0, "карточек": 0, "со_скидкой": 0}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)  # как в универсальный.py: настоящий Chrome
        ctx = browser.new_context(locale="en-US", viewport={"width": 1366, "height": 900})
        pg = ctx.new_page()
        try:
            resp = pg.goto(BASE + PATH, wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(3000)
            stat["ответ_страницы"] = resp.status if resp else None
            for n in range(1, limit_pages + 1):
                cards = pg.evaluate(EXTRACT)
                stat["страниц"] = n
                for c in cards:
                    if c["href"] in seen_links:
                        continue
                    seen_links.add(c["href"])
                    stat["карточек"] += 1
                    pr = parse_card(c["text"])
                    if not pr:
                        continue
                    now, was = pr
                    # Текст вида «Zimmermann Crepe de Chine Button-Down Shirt $113 $450 -75%»:
                    # убираем цены и проценты, остальное — бренд и название вместе (разделить без разметки нельзя)
                    name = re.sub(r"\s*\$[\d,\.]+\s*", " ", c["text"])
                    name = re.sub(r"-?\d+%", "", name).strip()
                    brand = ""
                    rows.append({
                        "магазин": "THE OUTNET",
                        "артикул": c["href"].rsplit("/", 1)[-1],
                        "название": name,
                        "бренд": brand,
                        "цена_сейчас": now,
                        "цена_была": was,
                        "скидка_%": round((was - now) / was * 100),
                        "валюта": "USD",
                        "ссылка": c["href"],
                        "картинка": c["img"],
                        "размеры": [],
                        "дата_сбора": date.today().isoformat(),
                    })
                more = pg.get_by_text(re.compile(r"Load more", re.I))  # кнопка «Load more ↓», тег не важен
                if more.count() == 0:
                    break
                if n == limit_pages:
                    stat["потолок"] = f"достигнут предел {limit_pages} порций, возможно, это не весь Sale"
                    break
                more.first.click()
                pg.wait_for_timeout(int(PAUSE * 1000))
        finally:
            browser.close()
    stat["со_скидкой"] = len(rows)
    rows.sort(key=lambda r: (-r["скидка_%"], r["цена_сейчас"]))
    return rows, stat


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else MAX_PAGES
    rows, stat = collect(limit)
    OUT.mkdir(exist_ok=True)
    out = OUT / "sale_outnet.json"
    out.write_text(json.dumps({"сайт": "THE OUTNET", "дата": date.today().isoformat(), "валюта": "USD",
                               "товаров": len(rows), "rows": rows}, ensure_ascii=False), encoding="utf-8")
    # top_outnet.csv для таблицы: лучшие по скидке, без детского по правилам отбора
    top = [dict(r, тип=r.get("тип", ""), цвет=r.get("цвет", "")) for r in rows
           if not правила_отбора.причина_отказа(r["название"] + " " + r["артикул"], "")]
    write_top_csv("outnet", top)
    print(json.dumps(stat, ensure_ascii=False))
    print(f"Записано: {out} ({len(rows)} товаров с реальной скидкой)")


if __name__ == "__main__":
    main()
