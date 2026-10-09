"""Render Mermaid diagram code to a PNG file via the mermaid.ink public API.

The diagram code is base64url-encoded and sent as a URL path segment.
No API key required; requires internet access.
"""

from __future__ import annotations

import base64

import httpx


async def mermaid_to_png(mermaid_code: str, output_path: str) -> bool:
    """Fetch a PNG render of *mermaid_code* and write it to *output_path*.

    Returns True on success, False if the request failed (non-fatal).
    """
    encoded = base64.urlsafe_b64encode(mermaid_code.strip().encode()).decode()
    url = f"https://mermaid.ink/img/{encoded}?type=png"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, follow_redirects=True)
        if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image/"):
            with open(output_path, "wb") as fh:
                fh.write(resp.content)
            return True
    except Exception:
        pass
    return False
