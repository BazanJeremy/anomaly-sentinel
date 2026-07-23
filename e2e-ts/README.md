# e2e-ts — TypeScript end-to-end tests

Self-contained Playwright (TypeScript) harness added as part of the series-wide
Claude Code tooling setup. It exercises a canonical login journey on Sauce Labs'
public practice application ([saucedemo.com](https://www.saucedemo.com)) and
establishes the TypeScript page-object conventions for future UI journeys.

The existing dashboard end-to-end tests in `tests/e2e/` remain pytest-playwright;
this folder is intentionally isolated (own `package.json`, no impact on the
Python toolchain or CI).

## Structure

- `pages/` — page objects (`*.page.ts`): locators + user actions, no assertions.
- `tests/` — specs (`*.spec.ts`): scenarios and assertions only.
- `playwright.config.ts` — Chromium, tracing on first retry, HTML report.

## Run locally

```bash
cd e2e-ts
npm install
npx playwright install chromium
npm test
```
