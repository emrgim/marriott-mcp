# BUG-002 — curl su marriott.com = 403 Akamai

**Quando:** 2026-09-05  
**Sintomo:** `GET https://www.marriott.com/` anche con UA Chrome → HTTP 403, `server: AkamaiGHost`, body Access Denied.

**Ricerca:** Akamai Bot Manager; TLS/IP datacenter + mancanza JS sensor. Workaround 2026: browser reale (Playwright/Chrome), `launch_persistent_context`, `channel="chrome"`. Fonte: playwright.dev launchPersistentContext; Decodo Akamai 2026 (browser engine per JS challenge).

**Soluzione:** Chrome di sistema (`channel=chrome`) + user data dir persistente, non curl.

**Esito:** **risolto** con Chrome persistente (`channel=chrome`, `headless=False`).
Probe `src/probe_home.py` 2026-09-05: URL `https://www.marriott.com/default.mi`,
title "Marriott Bonvoy Hotels | Book Directly & Get Exclusive Rates", `denied=false`.
Screenshot: `.session/shots/home.png`.
