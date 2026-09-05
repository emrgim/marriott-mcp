# BUG-010 — signed_in false on My Account

**Symptom:** After password step-up the header reads `Hello, <name>` (not `Sign In, <name>`), so a naive “Sign In,” check reported signed_in=false.

**Fix:** Treat `Hello, Name`, `Sign Out`, and Lifetime Elite copy as signed-in.
