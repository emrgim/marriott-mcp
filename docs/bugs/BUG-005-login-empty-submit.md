# BUG-005 — login submit with empty fields

**Symptom:** HTTP 200 but still on the guest home; screenshot showed empty email/password.

**Causes:**

1. Screenshot ran before fill.
2. `get_by_role("button", name="Sign In")` can hit the header button instead of the form.
3. Label locators may not match the visible "Email or Member Number" placeholder.

**Fix:** `do_login()` in `src/browser.py` fills by label, submits the form that contains “Forgot password”, screenshots after fill.
