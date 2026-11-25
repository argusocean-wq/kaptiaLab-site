"""Real Chromium viewport and locale smoke tests for the public landing page."""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "index.html"
LOCALES = ("zh-TW", "zh-CN", "en", "ja", "ko", "fr", "de", "es", "pt-BR", "it", "ru", "ar", "th", "vi", "id")
VIEWPORTS = (320, 375, 390, 430, 768, 1024, 1440)


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.route("https://**/*", lambda route: route.abort())
        page.goto(PAGE.as_uri(), wait_until="load", timeout=30000)
        page.locator("#overview .card").first.wait_for()
        assert page.locator("#overview .card").count() == 6, "Expected six ecosystem cards"

        measurements = []
        for width in VIEWPORTS:
            page.set_viewport_size({"width": width, "height": 900})
            page.wait_for_timeout(80)
            result = page.evaluate("""() => ({
              viewport: window.innerWidth,
              document: document.documentElement.scrollWidth,
              body: document.body.scrollWidth,
              navDisplay: getComputedStyle(document.querySelector('.nav')).display,
              navWidth: document.querySelector('.nav').getBoundingClientRect().width,
              cards: [...document.querySelectorAll('#overview .card')].length
            })""")
            assert result["document"] <= width, f"Horizontal page overflow at {width}px: {result}"
            if width <= 800:
                assert result["navDisplay"] != "none", f"Mobile navigation hidden at {width}px"
            measurements.append(result)

        language = page.locator("#languageTag")
        for locale in LOCALES:
            language.select_option(locale)
            page.wait_for_timeout(20)
            state = page.evaluate("""() => ({
              lang: document.documentElement.lang,
              dir: document.documentElement.dir,
              hero: document.querySelector('.hero h1').innerText,
              cards: [...document.querySelectorAll('#overview .card h3')].map(n => n.innerText)
            })""")
            assert state["lang"] == locale, f"Locale switch failed: {locale} -> {state['lang']}"
            assert all(label.strip() for label in state["cards"]), f"Empty ecosystem labels for {locale}"
            if locale == "ar":
                assert state["dir"] == "rtl", "Arabic layout must use RTL direction"
            else:
                assert state["dir"] == "ltr", f"Unexpected RTL direction for {locale}"

        page.set_viewport_size({"width": 390, "height": 844})
        language.select_option("zh-TW")
        page.screenshot(path=str(ROOT / "mobile-layout-validation.png"), full_page=True)
        print(json.dumps({"status": "PASS", "viewports": measurements, "locales": len(LOCALES)}, ensure_ascii=False))
        browser.close()


if __name__ == "__main__":
    main()
