# Preset apply review — November 16, 2026

Reviewed against source cb91cb6, following the v1.6.0 service consolidation.

## Current architecture retained

- Comet, Search Broker and SlickSync were removed.
- Native Prowlarr and anime-scoped Knaben replace the former Comet route.
- Zilean is queried directly by AIOStreams.
- LumiereDB search and configurable Jikan endpoints were added.
- Recent portal navigation, internal service proxy and authentication work is retained.

This review checks source changes, deployment consistency and the metadata preset
path. It does not establish live acceptance of every provider or the user's server.

## Apply Preset defect

The portal sent the raw preset with a few API keys injected. Unlike bootstrap,
it did not adapt optional artwork/search/catalog providers or the Posters+ key.
Any upstream failure became HTTP 502. Updating a saved profile could then fall
back to creating a new profile, and the frontend hid the response explanation.

The installed AIOMetadata validator rejected Tamtaro Complete with TMDB but no
Fanart key. The prepared preset passed the same validator. This reproduces one
cause of the reported generic 502; the screenshot alone cannot distinguish it
from an incorrect password, timeout, catalog limit or other upstream rejection.

## Corrections

- Load and authenticate the existing profile before applying a preset.
- Preserve local API keys, linked accounts and player users; exclude imported
  identity/version fields and credentials from the template.
- Use TMDB artwork when Fanart is not configured; disable unconfigured Gemini
  search and optional MDBList/personal Simkl catalogs.
- Use the installation's Posters+ access key.
- Include the loaded base version for concurrent-update protection.
- Never create a replacement profile after a failed update.
- Require an explicit successful response and the expected profile identity
  before persisting the selected template.
- Report safe, specific upstream errors; distinguish timeout, authentication,
  invalid configuration and version conflict. Do not forward raw error bodies.

## Verification

- Python discovery: 223 tests run, 10 skipped, no failures.
- Frontend logic: 17 Node/VM tests passed. These are not real-browser acceptance.
- Source, manager and appliance Compose definitions validated.
- Generated manager file and 10-service application inventory checks passed.
- Credential-dependent integration check skipped without test credentials.
- Installed AIOMetadata required-key validator: original Tamtaro preset fails
  without Fanart; prepared preset passes using fixture keys.
- Existing local metadata profile loaded successfully with its saved password.
  Its configuration was not overwritten.

The local LumiereDB container still has the older shell-based healthcheck,
whereas current source uses its native healthcheck. That deployment discrepancy
is separate from preset validation. No server deployment or playback acceptance
is implied by this report.
