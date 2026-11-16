# Portal improvement roadmap

Proposed November 15, 2026. This complements ROADMAP.md and the historical
COPILOT-ROADMAP.md. Items below are planned work, not completed acceptance claims.

## Product direction

One page for configuring accounts, opening the AIOStreams player, copying a
manifest and managing self-hosted services. Keep primary setup fields visible.
Use dropdowns for long provider lists and one reusable side panel for logs,
diagnostics and maintenance. Service web UIs stay inside the portal through the
internal proxy. No additional bundled players or containers are needed for this work.

## 1. Simplify the page and establish consistent controls

- [ ] Compact top area: Open player, Copy manifest, Test setup, and a short status.
- [ ] Keep the manifest preview on one line with deliberate reveal/copy actions.
- [ ] Present configuration across the available width: streaming accounts,
      metadata and admin password. Stack these sections on smaller screens.
- [ ] Keep required inputs expanded; expose advanced fields only when relevant.
- [ ] Put device pairing, secondary manifest exports and downloads in one place.
- [ ] Use readable labels and help text, consistent spacing, clear keyboard focus
      and accessible contrast. Avoid oversized headings and tiny uppercase labels.
- [ ] Replace nested maintenance accordions with one tools panel.
- [ ] Audit every claim and label. Remove advice to publish service ports where
      the internal proxy is the intended route. Describe only verified tracking
      capabilities and distinguish account credentials from connected accounts.

Acceptance: new and returning users can find setup, player, manifest, password
and logs without opening nested menus. Verify desktop, narrow mobile and 200% zoom.

## 2. Make saving, applying and readiness understandable

- [ ] Use one authoritative state model for saved settings, unapplied edits,
      setup in progress, required dependencies, optional failures and test results.
- [ ] Provide a persistent action bar when fields change: Save & apply / Discard.
- [ ] Explain what will restart and which settings affect existing profiles.
- [ ] Preserve entered values on validation errors and lost connections; never
      store secret drafts in browser local storage.
- [ ] Show setup stages, elapsed time and the next useful action. Do not invent
      completion percentages when a service provides no progress information.
- [ ] Block tests against unapplied or incomplete configurations with an explicit
      reason. Optional failures should not invalidate a working core configuration.
- [ ] Keep separate labels for service reachable, account verified, streams found
      and playback verified. Include when and against which configuration a test ran.
- [ ] Resume progress after page reload and prevent duplicate apply operations.

Acceptance: test first install, invalid keys, partial startup, optional failure,
double-click, refresh during apply and network interruption without losing settings.

## 3. Unify account, Usenet and indexer management

- [ ] Give each account/server/indexer a name, enable switch, status and Test action.
- [ ] Use a provider dropdown with provider-specific fields and sensible defaults.
- [ ] Support multiple NNTP servers with priority, TLS, connection limits and
      optional user-assigned backbone labels. Explain priority according to the
      streaming backend's actual behavior rather than promising unsupported routing.
- [ ] Support multiple NZB indexers with independent validation and enable switches.
- [ ] Warn about duplicate endpoints without silently deleting an indexer or account.
- [ ] Make saved-secret behavior explicit: unchanged, replace, and remove.
- [ ] Show where the admin password applies and report per-service update failures.
- [ ] Preserve custom upstream settings when reapplying portal-managed values.

Acceptance: add, edit, disable, reorder where supported, and remove multiple
servers/indexers; repeat setup without duplicates or accidental credential removal.

## 4. Make embedded service management dependable

- [ ] Use a compact service list with name, purpose, state, Manage and Logs.
- [ ] Distinguish disabled, starting, healthy, degraded and unavailable states.
- [ ] Only offer Manage when the service actually provides a supported web UI.
- [ ] Provide clear loading, retry, authentication and proxy-error states.
- [ ] Preserve scroll position and keyboard focus when closing the embedded viewer.
- [ ] Keep login help in the viewer; never silently remove upstream authentication.
- [ ] Test redirected pages, assets, cookies and supported WebSocket connections
      through the proxy, including use behind an external reverse proxy.

Acceptance: each supported UI opens without exposing its internal port. Closing
the viewer returns to the same place; unavailable services have actionable errors.

## 5. Consolidate logs and performance diagnostics

- [ ] One log panel with service selector, search, time range, follow/pause,
      copy and sanitized download. Bound retained lines and response sizes.
- [ ] Link startup failures directly to relevant service logs and timestamps.
- [ ] Show movie/episode test stages and timings without mixing reachability
      checks with functional search results.
- [ ] Report first-observed versus repeat searches, playable candidate counts,
      timeouts and partial results. Claim cold-cache timings only when established.
- [ ] Trace measured routing, such as AIOStreams → Comet → Zilean/Search Broker
      → Prowlarr, with cached/shared requests distinguished where instrumented.
- [ ] Add a next-episode search toggle with a clear explanation of background
      requests, cache expiry and whether downloads or playback probes occur.
- [ ] Display effective timeout values and flag settings unsupported by the
      installed service version. Avoid claiming exact delay attribution from
      unrelated sequential probes.
- [ ] Offer a redacted support bundle with versions, deployment type, health,
      recent errors and test summaries. Exclude credentials and signed URLs.

Acceptance: diagnose an invalid key, unavailable indexer and Comet timeout from
the portal. Confirm secret redaction and bounded polling with the panel closed.

## 6. Refactor and release the interface safely

- [ ] Extract shared field, status, dialog and request-handling components from
      the large frontend files as the relevant sections change.
- [ ] Cancel obsolete requests, prevent overlapping polls, and reduce polling
      when the page is hidden. Keep a failed refresh from erasing useful state.
- [ ] Show installed version, available update, last successful backup and a
      concise update impact summary in the maintenance panel.
- [ ] Add browser coverage for the acceptance cases above, including keyboard
      access, mobile layout, proxy failures, password changes and dirty forms.
- [ ] Capture screenshots with fixture accounts only; update documentation after
      the new flows pass on both Compose and the all-in-one appliance.

Acceptance: release with dated evidence separating mocked browser checks, live
container checks and real playback. Preserve manifest identity and saved accounts.

## 7. Visual design, theming and aesthetics

- [ ] **Color token system:** Define a canonical set of CSS custom properties in one
      `:root` block and replace every magic hex value across the portal stylesheet.
      Required tokens: `--color-bg` (#0b0f19), `--color-surface` (#131b2e),
      `--color-surface-raised` (card-on-card), `--color-border`, `--color-accent`
      (#38bdf8), `--color-accent-hover`, `--color-accent-muted` (10 % alpha tint),
      `--color-text-primary`, `--color-text-secondary`, `--color-text-disabled`,
      `--color-text-on-accent`. No inline hex values or `rgb()` literals may remain
      in CSS after this item is complete.
- [ ] **Status color semantics:** Reserve five semantic color tokens and apply them
      consistently to every health badge, dot indicator, alert banner and log
      level in the portal:
      `--color-status-ok` (green), `--color-status-warn` (amber),
      `--color-status-error` (red), `--color-status-info` (blue),
      `--color-status-neutral` (gray / disabled).
      Each token maps to both a background tint (10 % alpha) and a full-saturation
      foreground so text-on-tint meets 4.5 : 1 contrast.
- [ ] **Dark / light mode toggle:** Add a theme toggle control (moon/sun icon) in
      the portal header. Default to `prefers-color-scheme`; on explicit toggle,
      write `data-theme="light"|"dark"` to `<html>` and persist the choice in
      `localStorage` under the key `aio-theme`. Light-mode tokens must be defined
      in `[data-theme="light"]` overrides; no JavaScript is permitted to swap hex
      strings directly.
- [ ] **Typography scale:** Define and apply size, weight and line-height tokens for
      every text role used in the portal. Minimum required tokens:
      `--text-heading-lg` (1.25 rem / 600 / 1.3), `--text-heading-md`
      (1.05 rem / 600 / 1.35), `--text-heading-sm` (0.9 rem / 600 / 1.4),
      `--text-body` (0.9 rem / 400 / 1.5), `--text-label` (0.78 rem / 500 / 1.4),
      `--text-caption` (0.72 rem / 400 / 1.5), `--text-code` (0.82 rem mono / 400 / 1.6).
      Audit existing headings and labels; remove all hard-coded `font-size`,
      `font-weight` and `line-height` values not referencing these tokens.
- [ ] **Icon system standardization:** Material Symbols is already loaded; apply
      consistent axis settings globally via a single CSS rule:
      `font-variation-settings: 'FILL' 0, 'wght' 300, 'GRAD' 0, 'opsz' 20;`
      on the `.material-symbols-rounded` class. Define size variants as utility
      classes: `--icon-sm` (16 px), `--icon-md` (20 px), `--icon-lg` (24 px).
      Audit every icon usage and tag each with exactly one size class. No inline
      `font-size` on icon elements.
- [ ] **Card / panel component tokens:** Define and apply structural tokens shared
      by every card, panel, dialog and embedded viewer:
      `--radius-sm` (6 px), `--radius-md` (10 px), `--radius-lg` (14 px),
      `--shadow-card` (`0 1px 3px rgba(0,0,0,.45), 0 4px 12px rgba(0,0,0,.3)`),
      `--shadow-elevated` (stronger version for modals / dropdowns),
      `--space-card-pad` (1 rem), `--space-card-gap` (0.75 rem).
      No card or panel may hard-code border-radius, padding or box-shadow values
      outside of these tokens.
- [ ] **Button / action visual hierarchy:** Distinguish three button tiers with
      explicit CSS classes:
      — `.btn-primary` (filled accent, `--color-accent` background) for Save, Apply,
        Open Player, Copy Manifest.
      — `.btn-secondary` (outlined, `--color-border` border, transparent background)
        for Test, Manage, Refresh, Download.
      — `.btn-destructive` (outlined with `--color-status-error` border, red text)
        for Remove, Reset, Revoke.
      Each tier must have a hover state, an active/pressed state and a disabled state
      defined entirely with tokens. No buttons may rely on browser default styling.
- [ ] **Focus and hover states:** Define and apply:
      `--focus-ring: 0 0 0 2px var(--color-bg), 0 0 0 4px var(--color-accent);`
      as a `box-shadow` on `:focus-visible` for every interactive element (buttons,
      inputs, selects, checkboxes, icon-buttons, links). Hover states for
      interactive surfaces use `--color-accent-muted` as a background tint.
      Remove any `outline: none` rule that is not accompanied by a visible
      `:focus-visible` replacement.
- [ ] **Motion policy and transition tokens:** Define:
      `--duration-fast` (100 ms), `--duration-base` (180 ms), `--duration-slow`
      (300 ms), `--easing-default` (cubic-bezier(0.4, 0, 0.2, 1)).
      Apply transitions only to: color, background-color, border-color, box-shadow,
      opacity and transform. Do not transition layout properties (width, height,
      padding). Wrap all transition declarations in
      `@media (prefers-reduced-motion: no-preference)` so that users who have
      requested reduced motion see instant state changes. Animated elements:
      button hover/active, status badge color change, side-panel slide-in/out,
      toast fade-in/out.
- [ ] **Brand identity in the portal header:** Add the AIOStreams wordmark or
      compact logomark (SVG, inlined, ≤ 2 KB) to the top-left of the header bar.
      The header background is `--color-surface` with a 1 px bottom border in
      `--color-border`. The wordmark color inherits `--color-text-primary`; the
      accent glyph (if any) uses `--color-accent`. No external image requests.
      The brand element must not overflow the header on narrow (320 px) viewports.
- [ ] **Audit and documentation:** After all tokens are applied, generate a
      `docs/DESIGN-TOKENS.md` listing every token, its default dark-mode value,
      its light-mode override and the UI locations where it is used. Include a
      `docs/MOTION-POLICY.md` table: element → property → duration → easing →
      reduced-motion behavior. Both documents are generated from the CSS source,
      not written by hand.

Acceptance: (a) `grep -R '#[0-9a-fA-F]\{3,6\}' portal_server.py static/` returns
zero results outside of the token definitions block; (b) toggling the theme control
in a browser with `prefers-color-scheme: light` and with `prefers-color-scheme: dark`
produces visually distinct and contrast-passing pages; (c) all interactive elements
show a visible focus ring when navigated by keyboard only (Tab / Shift-Tab), verified
with Chromium's accessibility tree; (d) `prefers-reduced-motion: reduce` produces
no CSS transitions or keyframe animations anywhere in the portal; (e) WCAG AA
contrast (4.5 : 1 text, 3 : 1 large text and UI components) passes for every
foreground/background token pair, verified with a contrast-checking script run in CI.

## 8. Navigation, information architecture and onboarding

### 8.1 Navigation structure

- [ ] Choose and document one navigation pattern for the portal: a persistent left sidebar on viewports ≥1024 px, collapsing to a top icon-only bar at 640–1023 px, and a bottom tab bar below 640 px. Record the decision in `docs/PORTAL-ARCHITECTURE.md` with the rationale for single-page scroll vs. tabbed routing.
- [ ] Assign each major section a stable slug: `#setup`, `#accounts`, `#services`, `#logs`, `#diagnostics`, `#maintenance`. All internal links, keyboard shortcuts, and history entries use these slugs consistently.
- [ ] Implement the nav using a `<nav>` landmark with `role="navigation"` and `aria-label="Portal sections"`. Each item is an `<a href="#slug">` so the browser's native hash navigation works without JavaScript for basic use.
- [ ] The active nav item reflects the section currently in the viewport (see §8.3), not just the last clicked link. It updates on scroll without layout shift.
- [ ] On first load with no hash, default to `#setup` and scroll it into view. If a hash is present and valid, scroll directly to that section; if the hash is unknown, fall back to `#setup` and show a one-line "Section not found" notice below the nav.

### 8.2 Section anchors and deep links

- [ ] Each major section heading carries an `id` matching its slug (`<h2 id="setup">`). Subsections carry compound ids (`accounts-nntp`, `accounts-indexers`).
- [ ] Clicking the section heading or a nav item pushes `location.hash` via `history.pushState` so the URL updates without a full page reload and the Back button returns to the previous section.
- [ ] A "Copy link to this section" icon (link-chain, 16 px) appears on heading hover / keyboard focus. Activating it copies the full URL with hash to the clipboard and shows a 2 s "Copied!" tooltip.
- [ ] The portal server must respond to any `/#<slug>` with the same `index.html`; this is already true for a single-page app but must be tested behind the existing reverse-proxy path.
- [ ] Pasting or navigating to `http://host:8088/#logs?service=comet&follow=true` opens the log panel, pre-selects the Comet service, and starts follow mode. Only these two query parameters are supported in v1; additional params are silently ignored.

### 8.3 Sticky section indicator

- [ ] A sticky header bar (height 40 px, below the top action bar) shows: breadcrumb of the section in view, e.g. **Portal › Accounts › NNTP Servers**, updated via `IntersectionObserver` as sections enter the viewport. The breadcrumb is plain text, not a nav itself.
- [ ] In the sidebar nav, the item for the section currently in view receives `aria-current="location"` and a visual indicator (3 px left accent, same color as the existing accent token). Only one item is active at a time.
- [ ] On scroll, the indicator transitions with a 150 ms ease so it does not flicker when two sections are simultaneously partially in view — use a debounce of 80 ms before updating.
- [ ] At 200% browser zoom the sticky header must not cover form inputs; set `scroll-margin-top` on each section to equal the combined height of the top action bar and the sticky breadcrumb.
- [ ] Provide a "Skip to main content" link as the first focusable element in the DOM, visually hidden until focused, pointing to `#main-content`. This satisfies WCAG 2.4.1.

### 8.4 Keyboard shortcuts

- [ ] `Ctrl+S` (Windows/Linux) / `⌘S` (macOS): trigger Save & Apply if unsaved changes exist; show a "Nothing to save" toast if the form is clean. Never intercept if the user is in a text input within an embedded service iframe.
- [ ] `Ctrl+/` / `⌘/`: open the command palette (see §8.7). Close it with `Escape` or by clicking outside.
- [ ] `Escape`: close the topmost open panel (command palette, then side panel, then embedded service viewer) in that priority order. Never close if focus is inside an `<input>` or `<textarea>` unless the input is inside the panel being closed.
- [ ] `Alt+1` through `Alt+5`: jump to Setup, Accounts, Services, Logs, Diagnostics respectively. These do not conflict with browser or OS defaults on the target platforms (Chrome on Windows/macOS/Linux) — verify before shipping.
- [ ] `Tab` order follows the visual reading order top-to-bottom, left-to-right, respecting `display` order in the DOM so no `tabindex` values > 0 are needed. Verify with a keyboard-only walkthrough on each section.
- [ ] Show a keyboard shortcut reference card accessible via `?` key (when focus is not in a text input). Render it as a modal with a single-column table of action / shortcut pairs. Close with `Escape`.
- [ ] All shortcut handlers check `event.target.closest('[data-shortcut-scope="portal"]')` or equivalent guard so shortcuts do not fire when the user is typing inside the embedded service iframe.

### 8.5 Quick-action top bar

- [ ] A fixed top bar (height 48 px) is always visible at `position: sticky; top: 0; z-index: 200`. It contains, left to right: portal wordmark / home link, then right-aligned: Health badge, Copy Manifest button, Open Player button.
- [ ] **Health badge**: a single-character status dot (green / amber / red) followed by a short label ("All healthy" / "1 degraded" / "Service down"). Clicking it jumps to `#diagnostics`. It polls `/api/health` every 30 s when the tab is visible; stops polling when `document.hidden` is true.
- [ ] **Copy Manifest button**: copies the current manifest URL to the clipboard. Disabled (and shows tooltip "Save settings first") when unsaved changes are present. Shows "Copied!" for 2 s after success.
- [ ] **Open Player button**: opens the AIOStreams player URL (from `/api/manifest-info`) in a new tab. Disabled with tooltip "Complete setup first" when BASE_URL is not set.
- [ ] The top bar must not cause content to be obscured: `main` has `padding-top` equal to the top bar height. At 200% zoom the bar stays on one line; test with the longest realistic service name and manifest URL label.
- [ ] The top bar buttons each have accessible names (`aria-label`), visible focus rings, and 44×44 px touch targets. Keyboard shortcut hints appear in tooltips (e.g. "Copy Manifest (Ctrl+M)").

### 8.6 First-run / onboarding flow

- [ ] On page load, check the response from `/api/status` for `base_url_set` and `tmdb_api_key_set`. If either is false and the user has not explicitly dismissed the wizard, render the onboarding overlay.
- [ ] The onboarding overlay is a full-width banner (not a blocking modal) inserted at the top of `#setup`, showing: step indicators (Step 1 of 3), progress bar, current step content, Back / Next / Skip buttons, and a "Dismiss and do this later" link.
- [ ] **Step 1 — Base URL**: a single labeled input for BASE_URL with inline validation and an explanation: "This is the public address Stremio will use to reach your server." A "What is this?" expandable block gives examples.
- [ ] **Step 2 — TMDB API key**: a labeled input with a direct link "Get a free key at themoviedb.org". Inline test button: "Verify key" calls the existing test endpoint and shows pass/fail inline.
- [ ] **Step 3 — Admin password**: prompt to set a password with confirmation. Mark this step as optional with a visible "(Optional)" badge; the Skip button on this step is prominently labeled "Skip for now."
- [ ] After Step 3 (or after Skip), save state to `localStorage` as `{ onboardingDismissed: true, dismissedAt: <ISO timestamp> }`. On subsequent loads, skip the wizard. Provide a "Re-run setup wizard" link in the Maintenance section to reset this flag.
- [ ] The wizard must not store any secret values in `localStorage`. Only the dismissal flag is persisted client-side; actual values are submitted to the backend as normal form posts.
- [ ] Do not show the wizard inside an embedded service viewer. The wizard targets `#setup` and must not break the embedded frame state.

### 8.7 Search / command palette

- [ ] `Ctrl+/` opens a floating palette centered in the viewport (max-width 560 px, max-height 60 vh). It has a single search `<input>` at the top auto-focused, and a scrollable list of results below.
- [ ] The palette indexes: all section names (jump targets), all current action labels ("Test Setup", "Copy Manifest", "Open Player", "Open Logs", "Save & Apply", "Download Support Bundle"), and all configured service names from `/api/services`.
- [ ] Typing filters the list to fuzzy-match entries. Use a simple client-side Levenshtein or prefix match — no server call. Show up to 10 results. Highlight the matched characters in results with `<mark>`.
- [ ] `↑`/`↓` arrows move the highlighted result. `Enter` activates it: jump to section, trigger action, or open service. `Escape` closes without action.
- [ ] Results are grouped: **Sections** / **Actions** / **Services**. Each group has a plain-text header. Empty groups are hidden.
- [ ] Palette opens with the last query cleared. If no results match, show "No results for '<query>'" and two suggestion links: "Jump to Setup" and "Open Logs."
- [ ] The palette is a `<dialog>` element with `role="dialog"`, `aria-modal="true"`, `aria-label="Command palette"`. Focus is trapped inside while open and returns to the triggering element on close.

### 8.8 Empty states

- [ ] **No accounts configured** (Accounts section): show an illustration placeholder (SVG icon, ~80 px), heading "No accounts yet", body "Add a streaming account to get started — Usenet or indexer accounts are optional", and a primary "Add account" button.
- [ ] **No indexers configured** (Accounts › Indexers subsection): "No indexers added. Prowlarr can manage these automatically — open it in the Services section." Include a link that scrolls to `#services` and highlights the Prowlarr row.
- [ ] **No logs** (Logs section): "No log entries yet. Logs appear here after services start." Do not show a spinner; logs are on-demand pull, not streamed by default.
- [ ] **Service list unavailable** (Services section): if `/api/services` returns an error, show "Services could not be loaded" with a Retry button and the HTTP status code or error type (do not expose stack traces).
- [ ] **No diagnostics run yet** (Diagnostics section): "Run a test to see results here." Primary "Run Test Setup" button. Do not show stale results from a previous session.
- [ ] All empty states have a minimum height of 120 px so the section is visually present in the nav scroll-spy. They must not trigger layout shift when data later loads in.

### 8.9 Breadcrumb inside embedded service panel

- [ ] When an embedded service panel is open, replace the sticky breadcrumb (§8.3) with a path showing: **Portal › Services › [Service Name]**. The service name is taken from the service list entry, not the iframe title.
- [ ] Each segment of the breadcrumb is a link: "Portal" goes to `#setup`, "Services" goes to `#services` and closes the embedded panel. "[Service Name]" is the current page and carries `aria-current="page"`.
- [ ] The breadcrumb updates within 200 ms of the embedded panel opening or closing; it must not read from the iframe's `document.title` (cross-origin iframes will block this).
- [ ] If the embedded service itself provides sub-navigation (e.g. Prowlarr › Settings › Indexers), the portal breadcrumb does not attempt to reflect it — only the portal-level path is shown. A note in `docs/PORTAL-ARCHITECTURE.md` explains why.

### 8.10 Return-to-portal affordance

- [ ] A "← Back to Portal" button is rendered in the portal chrome (not inside the iframe) at the top-left of the embedded service panel, always above the iframe. Minimum size 44×44 px. Label: "← Back to Portal".
- [ ] Clicking it closes the embedded viewer, restores scroll position to the Services section (`#services`), and returns keyboard focus to the service card row that opened it. This is the same behavior as `Escape` when the embedded viewer is the topmost panel.
- [ ] A "⤢ Open in new tab" button is adjacent to the Back button in the portal chrome, opening the service's URL directly. This is distinct from the existing `#service-frame-external` control documented in §4 and must share the same DOM element if that element already exists, not duplicate it.
- [ ] When the portal is embedded inside an external reverse proxy or is itself inside a parent frame, the Back button behavior must not call `window.parent.postMessage` or navigate outside the portal origin.

### Acceptance

Verify all of the following before closing this section:

1. A new user with BASE_URL unset sees the onboarding wizard on first load; completing or dismissing it does not reappear on reload; "Re-run setup wizard" in Maintenance resets it.
2. Navigating to `http://host:8088/#logs` scrolls to the Logs section and highlights it in the nav without a full page reload. Navigating to `#logs?service=comet&follow=true` pre-selects Comet and starts follow mode.
3. The sticky breadcrumb updates as the user scrolls through Setup → Accounts → Services → Logs using keyboard only (`Tab`, `Shift+Tab`, arrow keys).
4. `Ctrl+/` opens the command palette; typing "comet" shows Comet under Services; pressing `Enter` opens the Comet embedded viewer; `Escape` closes it and returns focus.
5. `Ctrl+S` with unsaved changes triggers Save & Apply; with no changes it shows "Nothing to save" toast. `Alt+1` through `Alt+5` jump to the correct sections.
6. Each section in its empty state renders visibly (≥120 px height), is reachable by keyboard, and contains at least one actionable element (button or link).
7. Opening the Prowlarr embedded viewer shows "Portal › Services › Prowlarr" in the breadcrumb. Clicking "Services" closes the viewer and scrolls to `#services`. "← Back to Portal" button is always visible above the iframe.
8. The top action bar (health badge, Copy Manifest, Open Player) is visible at the top of the viewport on a 1080p screen, on a 360 px wide mobile screen, and at 200% browser zoom with no horizontal overflow.
9. Run an axe or Lighthouse accessibility audit on the navigation landmark, command palette, and onboarding wizard. Zero critical or serious violations.

## 9. Micro-interactions, feedback states & empty/error design

- [ ] **Skeleton screens:** When service-status cards, the log panel, or the
      streams list are waiting on an API response, render placeholder shapes that
      match the target layout (card outline, line stubs at correct widths) rather
      than leaving the area blank. Remove skeletons and swap in real content
      atomically so the page does not reflow or jump. Never show a skeleton for
      longer than the actual load time; if data is already cached, skip it.
- [ ] **Tiered loading indicators:** Apply a consistent threshold rule across
      every fetch in the portal:
      - `<300 ms`: show nothing (avoid flicker for fast local responses).
      - `300 ms – 2 s`: show a small inline spinner next to the triggering control
        or inside the affected region; do not block the rest of the page.
      - `>2 s`: replace the spinner with a progress bar (indeterminate unless a
        concrete percentage is available from the backend) and a **Cancel** button
        that aborts the in-flight request and restores the previous UI state.
      Document this rule in a shared JS utility so individual fetch calls do not
      each implement their own ad-hoc delay logic.
- [ ] **Toast / notification system:** Implement a single toast manager that
      stacks at most 3 toasts in the top-right corner (below any fixed header).
      Each toast carries: an icon (✓ success · ⚠ warning · ✕ error) plus a
      concise message string. Toasts auto-dismiss after 4 s but pause the timer
      on pointer-hover. When a 4th toast would appear, the oldest is silently
      removed first. Fire toasts for at minimum: Save complete, Apply started,
      Apply succeeded, Apply failed with reason, Test passed (name the test),
      Test failed (name the test and the specific error), Copy to clipboard
      succeeded, and any network error from a background poll.
- [ ] **Inline field validation:** Validate form fields on `blur`, not on
      `input`. Display the error message directly below the offending field in a
      `role="alert"` element so screen readers announce it immediately. Never
      surface validation failures only at form submission after the user has
      moved on. Clear the inline error as soon as the field value passes
      validation on the next blur. Required-field errors must name the field
      explicitly (e.g. "API Key is required") rather than generic "field is
      invalid".
- [ ] **Custom confirmation dialogs for destructive actions:** Replace every
      `window.confirm()` call with a modal dialog that names the exact action and
      its consequence. At minimum require this for: Remove account, Remove
      indexer, Clear logs, Reset to defaults, and Revoke device pairing. The
      dialog must have a clearly labeled **Confirm** button (using the action
      verb, e.g. "Remove account") and a **Cancel** button, with **Cancel**
      focused by default. Pressing Escape cancels. The dialog must trap keyboard
      focus while open.
- [ ] **Progress indicators with elapsed time and cancel:** For long operations
      (Apply configuration, Test setup, Restart service), display a progress
      region that shows: operation name, elapsed time in seconds (updated each
      second), and a **Cancel** button. Cancel must send an abort signal to the
      server endpoint (or close the fetch with `AbortController`) and show a
      "Cancelled" toast; it must not leave the server operation running silently.
      Do not display a fake percentage when the backend provides no progress
      information; use an indeterminate bar instead.
- [ ] **Typed error states for unreachable services:** When a service status
      poll fails, classify the failure before displaying it:
      - **Network error** (no response / DNS / ECONNREFUSED): "Cannot reach
        [service] — check that the container is running." Action: Retry / View
        logs.
      - **Auth error** (HTTP 401 / 403): "[Service] rejected the request —
        verify the API key." Action: Open settings.
      - **Config error** (HTTP 400 / 422 / known bad-config response): "[Service]
        reports a configuration problem." Action: View details / Open settings.
      - **Timeout** (request exceeded threshold): "[Service] is slow to respond —
        it may be starting up." Action: Retry in 10 s / View logs.
      Never collapse all four categories into "Service unavailable". Each type
      must render its specific recovery action as a tappable button, not plain text.
- [ ] **Success micro-feedback on specific actions:**
      - Save & Apply: the button briefly shows a check icon (✓) for 1.5 s before
        returning to its default label.
      - Copy Manifest / Copy URL: replace the copy icon with "Copied!" for 2 s,
        then restore.
      - Test (any): the result banner identifies the test by name and outcome,
        not just "Test passed".
      - Password changed: show a success toast and clear the password fields;
        do not silently leave old values in place.
- [ ] **Optimistic UI for enable/disable toggles:** When the user flips an
      indexer, account, or server enable switch, update the toggle and any
      dependent status badges immediately in the DOM without waiting for the
      server response. If the PATCH/POST fails, roll back the toggle to its
      previous state and show an error toast that names the item and the failure
      reason. The toggle must be disabled (pointer-events: none) for the duration
      of the in-flight request to prevent a second flip racing the first.
- [ ] **Dirty-state indicator for unsaved changes:** Whenever a form section
      contains a changed, unsaved value, display a subtle visual indicator on
      that section's heading or nav entry (e.g. a small filled dot or an asterisk
      with `aria-label="unsaved changes"`) so users know exactly which section
      holds pending edits. Clear the indicator immediately after a successful
      save. If the user attempts to navigate away from the page with dirty fields,
      show a `beforeunload` warning and, where SPA routing is used, intercept the
      route change with a custom confirmation dialog.
- [ ] **Empty state component pattern:** Implement a reusable empty-state component
      used across all sections, adhering to the section-specific specifications in §8.8
      (plus search/test results with "No streams found"). Each empty state renders an
      illustrative SVG icon (~80 px), clear guidance on why data is absent, and an
      actionable primary button (e.g. "Add account", "Test search"). Empty states maintain
      a minimum height of 120 px to prevent layout shifts upon data load, and must never
      render as blank 0-height or collapsed regions.

Acceptance: (a) Load the portal on a cold cache and confirm skeleton screens
appear then resolve without layout shift. (b) Trigger a save and confirm a
success toast appears and auto-dismisses; hover it and confirm the timer pauses.
(c) Enter an invalid API key into a field and tab away; confirm an inline error
appears without submitting the form. (d) Click "Remove account" and confirm a
named modal appears with Cancel focused; pressing Escape closes it without
removing the account. (e) Trigger Apply configuration and confirm elapsed time
increments and Cancel aborts the operation. (f) Force a service to be
unreachable and confirm the error message names the failure type and shows a
recovery action button. (g) Toggle an indexer off while the network is blocked
and confirm the toggle rolls back with an error toast. (h) Edit a field without
saving and confirm a dirty indicator appears on the section heading; save and
confirm it clears. (i) Remove all indexers and confirm the non-empty empty state
from §8.8 with an "Add indexer" action is shown.

## First implementation slice

Start with phases 1 and 2: the compact player/manifest area, always-visible setup,
consistent form controls, a Save & apply bar, and trustworthy readiness messages.
Then complete account management and embedded service flows before expanding
diagnostics. Reuse working backend and proxy behavior while changing presentation.

Sections 7–9 expand this roadmap with foundational design, navigation, and
micro-interaction standards. These should not be deferred to a separate late phase,
but incorporated progressively as each original section's UI work is implemented:
- **Design tokens (§7):** Establish color, typography, spacing, icon, and card tokens
  during Section 1 implementation to eliminate hard-coded styles from the outset.
- **Navigation & IA (§8):** Stand up the sticky header, section anchor slugs, skip link,
  and clean navigation structure during Section 1 and Section 2.
- **UX states & micro-interactions (§9):** Build the toast notification system, typed
  error states, optimistic toggles, and dirty-form tracking directly into the form and
  service management flows of Sections 2, 3, and 4.
