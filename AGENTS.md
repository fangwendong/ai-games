# Agent Notes

## Browser Playtesting

- Do not assume a browser is unavailable just because `firefox`, `chromium`, or `google-chrome` is missing from `PATH`.
- Check Playwright's cached browsers as well. In this environment, Firefox has been found at:

```bash
/home/fwd/.cache/ms-playwright/firefox-1532/firefox/firefox
```

- If the Playwright MCP defaults to Chrome and fails with a missing `/opt/google/chrome/chrome`, run Playwright manually and pass Firefox via `executablePath`.
- A known usable Node module path for ad hoc Playwright scripts is:

```bash
NODE_PATH=/home/fwd/.npm/_npx/e41f203b7505f1fb/node_modules
```

Example:

```bash
NODE_PATH=/home/fwd/.npm/_npx/e41f203b7505f1fb/node_modules node <<'NODE'
const { firefox } = require('playwright');

(async () => {
  const browser = await firefox.launch({
    executablePath: '/home/fwd/.cache/ms-playwright/firefox-1532/firefox/firefox',
    headless: true
  });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await page.goto('http://127.0.0.1:4174/', { waitUntil: 'networkidle' });
  await page.screenshot({ path: '/tmp/playtest-desktop.png', fullPage: true });
  await browser.close();
})();
NODE
```

## Web Game Test Flow

- For static web games, start a local server from the game directory, for example:

```bash
python3 -m http.server 4174
```

- Verify the server with `curl -I http://127.0.0.1:4174/`.
- Prefer real browser testing for UI layering, pointer interception, responsive layout, and screenshots.
- Use `jsdom` only as a fallback or supplement for fast state-machine checks. It can execute the page script and simulate clicks, but it will not reliably catch real layout and pointer-event bugs.
- When using real Playwright, capture at least:
  - desktop screenshot
  - mobile viewport screenshot
  - console/page errors
  - core interaction path results

## Garden Logic Playtest Checklist

For `games/garden-logic`, verify these paths:

- Initial render: title, level 1, 5x5 board, 3 lives, readable status message.
- More panel opens and closes.
- Guide modal opens and closes from realistic user paths.
- `H` highlights one correct hint cell and updates the message.
- Bloom plants one correct flower and decrements the bloom counter.
- Correct solution completes the level, shows the result modal, enables next level, and advances to level 2.
- Wrong clicks decrement lives; exhausting lives shows failure and restarting the segment restores lives.
- Mobile viewport around `390x844` has no horizontal overflow.

Regression to remember: real Firefox found a bug that `jsdom` missed. Opening `玩法` from inside the `更多` side panel caused `#sideBackdrop` to sit above the guide modal and intercept clicks on the guide close button. Always use a real browser for overlay and z-index behavior.
