# BUG-006 — placeholder login non visibile in 20s

**Quando:** 2026-09-05, `probe_login_verify.py` su Chrome headed (`channel=chrome`)
**Sintomo:** `get_by_placeholder("Email or Member Number")` timeout 20s.

**Ricerca:** overlay cookie / pagina diversa / placeholder vs aria-label. Il probe precedente vedeva `aria-label="email or member number"`.

**Soluzione:** dump input + screenshot al timeout; fill via aria-label se placeholder assente.
