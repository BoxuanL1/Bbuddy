# Architecture

The primary workflow is online and agent-directed:

1. The agent identifies the selected course/scope and resources from Blackboard pages.
2. `online` provides visible NTU login, rendered-link snapshots, explicit PDF/PPTX acquisition and subtitle capture orchestration.
3. `adapters.kaltura` listens to browser-context traffic and fetches caption playlists using the browser's authenticated request context.
4. `captions.hls` handles timeline mapping, rollover, discontinuities, deduplication and export. This is migrated prototype code with regression tests; `captions.core` is the older offline parser and is not interchangeable with the HLS cue model yet.
5. `storage` isolates account state and atomically writes documents/checkpoints. URL-bearing inventories and playlist caches are private; acquisition reports omit full URLs.
6. The agent performs course/lecture mapping, evidence classification and writing after acquisition. This final stage still needs structured source indexes and stronger reference validation.

`pipeline.offline` remains a development scaffold. Its placeholder evidence and basic validator must not be treated as M1 completion. PDF/PPTX extraction is optional. Deterministic processing does not call a model; no extra API key is needed for acquisition.

Acquisition is a separate stage from normalization and analysis. `acquisition.json` tracks per-file results and cache keys, while private selection files retain the chosen URLs. Resource roles and Week/Lecture associations belong to the agent's selection, not URL or filename guesses in the downloader.
