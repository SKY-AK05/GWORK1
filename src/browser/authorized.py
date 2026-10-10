"""Safe browser research boundary.

The helper intentionally exposes page text and URLs only. It does not expose
cookies, storage state, passwords, or browser profiles to the research graph.
"""
from __future__ import annotations

import os
from typing import Any

from src.utils.url_utils import is_safe_public_url


class BrowserConsentRequired(PermissionError):
    """Raised when browser research is requested without explicit consent."""


class AuthorizedBrowserResearch:
    """Temporary browser context requiring explicit user consent.

    The caller must direct the user to the platform's normal login UI. This
    class never accepts credentials and never persists storage state by default.
    """

    LOGIN_URLS = {
        "linkedin": "https://www.linkedin.com/login",
        "instagram": "https://www.instagram.com/accounts/login/",
    }

    def __init__(self, *, consent: bool, headless: bool | None = None, persistent: bool = False):
        if not consent:
            raise BrowserConsentRequired("Explicit user consent is required before browser research")
        if persistent and os.getenv("BROWSER_PERSISTENT_SESSION", "false").lower() != "true":
            raise BrowserConsentRequired("Persistent browser state requires explicit configuration consent")
        self.headless = bool(os.getenv("BROWSER_HEADLESS", "false").lower() == "true") if headless is None else headless
        self.persistent = persistent
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None

    async def __aenter__(self):
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("Browser research requires playwright; install it and its browser separately") from exc
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context()
        return self

    async def open_login(self, platform: str):
        url = self.LOGIN_URLS.get(platform.lower())
        if not url:
            raise ValueError(f"Unsupported login platform: {platform}")
        page = await self._context.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        return page

    async def read_page(self, url: str) -> dict[str, str]:
        if not is_safe_public_url(url):
            raise ValueError("Unsafe or non-public browser URL")
        page = await self._context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded")
            return {"url": page.url, "title": await page.title(), "content": await page.locator("body").inner_text()}
        finally:
            await page.close()

    async def __aexit__(self, exc_type, exc, tb):
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        return False
