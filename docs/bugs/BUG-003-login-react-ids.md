# BUG-003 — ID React instabili sul form login

**Quando:** 2026-09-05, `src/probe_signin.py`  
**Sintomo:** campi login hanno id tipo `:Rrad6H1:-email` / `:Rrad6H1:-password` (React). Si rompono a ogni render.

**Ricerca:** selettori Playwright su SPA: preferire `getByLabel` / `aria-label` / `getByRole`, non id generati. Playwright locators docs.

**Campi verificati live:**

- text input `aria-label="email or member number"`
- password `aria-label="sign in password"`
- submit `aria-label="Sign In"` (role=button)

**Soluzione:** login usa aria-label, non id.

**Esito:** applicata in `src/server.py`.
