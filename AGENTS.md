# Development workflow

- Use parallel specialized agents for independent substantial work, with explicit
  file ownership and shared-interface coordination. Use at most four concurrent
  agents including the lead when that is the available limit.
- Inspect current source and maintain a prioritized roadmap before implementation.
- Work on a development branch or isolated checkout. Preserve other contributors'
  edits and keep main stable.
- Do not merge to main, push to main, or publish images without explicit user
  approval. Earlier publication permission does not override this requirement.
- Integrate compatible changes locally, run relevant regression tests, builds and
  Docker Compose validation, and review security and integration risks.
- Report each agent's findings, completed work, evidence and unresolved issues.
- If delegation is unavailable, explain the limitation and continue useful work
  locally without pretending the parallel work completed.
- Keep the product suitable for one Docker Compose installation. Never include
  live keys, runtime data or credential-bearing diagnostics in source or reports.
