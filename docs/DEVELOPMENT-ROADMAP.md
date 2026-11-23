# Polish roadmap — November 22, 2026

Baseline: a89e303. This roadmap describes acceptance work; older completed labels
and historical performance figures do not establish that this revision passes.

## First slice: trustworthy configuration and diagnostics

1. **Credential safety (P0):** bind saved NZB keys to the exact normalized API
   endpoint, reject mismatched saved IDs and URLs, and never forward credentials
   through redirects. Require capabilities XML rather than any HTTP 200 page.
   Verify wrong host, subdomain, path, port, scheme and redirect cases with tests.
2. **NNTP testing (P0):** preserve successful authentication results through socket
   cleanup. Test accepted credentials, rejected credentials and connection errors.
3. **Truthful diagnostics (P1):** remove fabricated Lumiere counts, snapshot dates
   and progress percentages. Escape untrusted responses and search input; allow
   only valid IMDb IDs in external links. Verify unknown and zero values.
4. **Clipboard and save UX (P1):** show success only after copying succeeds;
   prevent duplicate submissions and preserve edits made during pending saves.

## Second slice: predictable deployment

- Preserve optional anime/Jikan profiles in the generated manager definition.
  Align controller defaults and packaged portal settings with the selected profile.
- Test core, anime, legacy aliases and all-service deployments against the same
  service inventory; optional dependencies must not block core readiness.
- Promote stable image tags only after complete release acceptance, avoiding
  partial image sets when one matrix build or live check fails.
- Review portal authentication defaults, Docker-engine privileges, PostgreSQL
  trust authentication and superuser credentials with an explicit existing-data
  migration plan. Do not rotate credentials or change database roles blindly.

## Third slice: account setup and search quality

- Add explicit Easynews account detection/validation from supported saved server
  entries, preserving an intentional opt-out and separate web-access validation.
- Explain why anime addons are disabled and which account/provider enables them.
- Benchmark current Zilean/native Prowlarr/Torz paths using identical titles,
  cache conditions and result counts. Retired Comet timings are historical only.
- Verify next-episode warming, concurrent viewers and unavailable upstreams
  without duplicate work. Distinguish search success from video playback.

## Acceptance and release

- Run Python regression discovery, frontend logic tests, generated manager checks,
  inventory checks and source/manager/appliance Compose validation.
- Build affected packaged images locally where Docker is available. Run disposable
  integration checks with fixture data, including actual HTTP redirect behavior.
- Browser, paid-provider, remote tunnel and NAS playback checks remain separate
  gates; report skipped checks honestly.
- Obtain user approval before merging, pushing to main or publishing images.

## Team review

### Completed locally

- Saved NZB keys are bound to the selected API endpoint; redirects cannot forward
  them. Responses must contain Newznab capabilities XML.
- NNTP connection cleanup no longer overrides authentication results.
- Linux container regression suite: **274 tests passed**.
- Frontend logic harness: **29 tests passed** (not browser playback tests).
- Generated manager, service inventory and all three Compose definitions validated.
- Packaged portal image built locally and passed imports with networking disabled.
- No live provider, server playback or browser acceptance testing was performed in
  this slice. No changes have been merged or published.

Three concurrent agents reviewed frontend interactions, backend reliability and
deployment consistency. All stopped at an account usage limit before implementing
changes. The lead continued the first credential-safety/NNTP slice locally.
Frontend and deployment findings above remain planned unless separately verified.

## Gemini integration review — November 23, 2026

Reviewed merged commit `10773d5` in parallel for portal interactions and tunnel
lifecycle. Preserved its setup flow and fixed these regressions:

- Removed secret tokens from public metadata and escaped tunnel preview/DNS text.
- Passed saved or entered credentials into Compose; restart recreates the connector
  so changed credentials take effect. Saved API credentials can be reused.
- Prevented selecting a new tunnel from starting the old tunnel's connector.
- Located the connector within the existing Compose project, including manager
  deployments with generated container names. Missing identity fails safely.
- Removed claims that a running container proves remote connectivity.

Both review agents implemented their assigned fixes. The lead completed portal
integration and manager compatibility after an agent reached its usage limit.
User authorized merging on November 23. Live Cloudflare and playback checks remain
unverified; regression tests use fixture credentials only.

Final integration validation: 283 Linux Python tests and 30 frontend logic tests
passed. Source, manager and appliance Compose definitions, generated manager
freshness and service inventory passed. The final portal image built locally.
