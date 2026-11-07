# Release validation — 2026-11-07

Status: **not ready for final publication**. Original production stack remains unchanged; live tests use project `aio-release` and separate data/ports.

- Copilot roadmap retained in `docs/COPILOT-ROADMAP.md`; merged release gates in `ROADMAP.md`.
- Controller/bootstrap and generated manager deployment restored; package builds and apply-from-portal acceptance remain outstanding.
- 75 Python regression tests passed; prior browser suite passed 6 tests and PostgreSQL repeat initialization passed.
- 21/21 internal endpoint checks passed. Several checks are TCP only; this is not functional certification of every integration.
- Premiumize, TMDB and TVDB authentication passed. Fanart configuration recovered from original ignored environment; current live Fanart authentication still needs rerun.
- Personalized and alias manifests passed.
- Movie: 16 stream URL candidates, zero duplicate URLs, 65,536 media bytes returned with HTTP 206; **15 seconds of media successfully decoded by FFmpeg in Stremio Web**.
- Episode: Game of Thrones S1E1 and Breaking Bad S1E1 yielded no usable stream URLs; Sootio timeout observed. Episode playback has **not passed**.
- Repeat movie requests still took about 20 seconds, indicating the timed-out secondary scraper remains a latency cost. End-to-end call-count instrumentation remains outstanding.
- Fresh Zilean import was initially disabled for resource isolation. It is now enabled to populate episode cache; completion still needs verification.

Routing changes under test: Comet owns Prowlarr/Zilean; AIOStreams owns anime ID mapping; Sootio has no recursive aggregator/indexer calls and uses distinct direct sources; MediaFusion does not re-query Prowlarr/Zilean. Anime acceptance remains required after removing Comet's duplicate import.

Other remaining release gates: source/manager maintenance parity, actual controller apply, live backup/restore acceptance, image builds/version pins, episode/metadata/subtitle/proxy functional matrix, request trace/count audit, screenshot refresh and CI verification. Source is uncommitted and has not been published as final.


## Tracing/packaging update

See [TRACING-AND-PACKAGING.md](TRACING-AND-PACKAGING.md). Eight images now build locally, package runtime checks pass, 77 regression tests pass, and movie **and episode** media both passed 15-second decode. Earlier episode failures above describe the earlier test state. Full manager apply and final publication remain open gates.


## Image-only full stack and credential cleanup

The complete `aio-package` stack started from local packaged images and named volumes, with empty provider credentials. All 21 internal endpoint checks passed after initialization. The portal/controller apply action returned HTTP 202 and subsequently completed successfully (`exit_code=0`, manifest ready). This verifies packaged orchestration; credential-free operation does not repeat authenticated playback.

Development `.env` files were cleared, release-test containers/volumes removed, and disposable data directories removed from both the release-test copy and the original agent checkout. Text and encoded-config cleanup ran across this workspace. Current release source matches none of the four supplied provider keys. Original user installation and original archive are preserved at user request.

The history audit found exposed keys in `tests/benchmark_pathways.py` and `tests/check_all_services_e2e.py` across commits `72c5c20`, `f076287`, `cda5519`, and `de8e4fd`. Current-source cleanup does not remove those historical copies. User authorized removal of the keys from Git history; the existing installation and original archive are excluded from cleanup. Rotate the exposed credentials regardless. Details without secret values: `KEY-CLEANUP.json`.


## Publication preparation

The supplied provider values were removed from reachable Git history, including all three existing release tags; local history verification found zero remaining matches. Commit sequence/messages were retained. The original user installation and original backup archive remain unchanged by explicit request. The latest source contains no supplied provider values. Earlier findings above are retained as a chronological audit.
