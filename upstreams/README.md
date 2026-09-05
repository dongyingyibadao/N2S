# Official upstream knowledge

This directory registers official sources and stores only N2S-authored metadata, deterministic indexes,
reviews, and curated summaries. Official prose, patches, code, and license files are not committed into
N2S. They are held under `upstreams/_cache/` as a local Git mirror and immutable read-only snapshots.

The only registered source is `cann-recipes-embodied-ai`, branch `master`. The initial accepted revision is
`45d167135c81d97573bfbe0e564bb4a1d9642514`. The source repository uses Apache-2.0 at its root, includes
separate model and third-party notices, and its disclaimer limits examples to reference and non-commercial
use. N2S therefore manages the cache as internal non-commercial reference material and does not republish
upstream bodies or patches as N2S-owned content.

## Storage layers

- `sources.json`: authoritative source URL, accepted revision, license fingerprints, indexing policy, and
  recipe-specific metadata.
- `indexes/*.json`: tracked, byte-deterministic index of the accepted revision. Every Git tree item carries
  its exact revision, object ID, SHA256, path, type, model/mode/device/version context, ownership marker,
  and fixed GitCode URL. A regular file's hash basis is `blob_content`; a gitlink has no blob and therefore
  uses `blob_sha256: null` plus an `entry_sha256` based on its submodule commit ID.
- `knowledge/*.json`: N2S-authored summaries. `official_claim` records what the source says;
  `n2s_validation` records whether N2S reproduced it.
- `reviews/*.json`: explicit revision acceptance records. Acceptance never edits a migration rule.
- `_cache/`: ignored mirror, snapshots, live index, current symlink, lock, and daily sync state.

## Commands

```bash
tooling/n2s-knowledge refresh-if-due
tooling/n2s-knowledge sync --force
tooling/n2s-knowledge status --json
tooling/n2s-knowledge search "fusion attention" --scope manipulation
tooling/n2s-knowledge search "CANN 8.3" --accepted-only --json
tooling/n2s-knowledge show upstream://cann-recipes-embodied-ai@45d167135c81d97573bfbe0e564bb4a1d9642514/manipulation/pi0/train/README.md
tooling/n2s-knowledge diff --from accepted --to live
tooling/n2s-knowledge accept --source cann-recipes-embodied-ai --revision SHA --review REVIEW.json
```

`refresh-if-due` performs at most one remote attempt per UTC date. `sync --force` is the explicit
maintainer override. Both use an exclusive file lock. A normal fast-forward can update the `current`
snapshot while remaining unreviewed; remote URL drift, non-fast-forward history, or any discovered license
file change fetches objects but blocks the switch. Network failure retains the last successful snapshot.
No command checks out a worktree or executes upstream hooks, installers, Python, or shell code.

`search` combines curated summaries with the current snapshot's full text and labels accepted versus
unreviewed revisions. `show` only reads an exact local snapshot; if it is absent, it prints the fixed remote
URL. Performance entries retain device, card count, batch, model, dataset, and measurement context and must
not be normalized across hardware.

## Acceptance

An acceptance review must validate against `schemas/review.schema.json`, match the source and full commit,
choose `accept`, and confirm license review. `accept` records the review, updates only the source's accepted
revision/license fingerprints, and rebuilds the accepted index. It has no code path to `rules/`.
