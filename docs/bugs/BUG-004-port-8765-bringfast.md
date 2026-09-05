# BUG-004 — assumed port already in use

**Symptom:** Health check on the first guessed port returned a different local app.

**Fix:** Do not assume a port is free. Default `MARRIOTT_PORT=8876`. Health JSON includes `"service":"marriott-dash"`.
