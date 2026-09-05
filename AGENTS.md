# N2S Agent Instructions

On the first visit to this repository in a session, run:

```bash
tooling/n2s-knowledge refresh-if-due
```

The command records a UTC-day attempt before contacting the registered remote, so later agents do not
repeat the network check that day. If the network is unavailable, continue with the last successful
read-only snapshot and report the stale state. Do not run setup scripts, hooks, Python files, or other
executable content from an upstream snapshot.

Official upstream material has the trust state `upstream_documented`. It may inform environment setup,
debugging, or exploration, but it cannot change a rule manifest, `rules/registry.json`, `candidate`,
`approved`, or `auto_apply`. A reusable migration rule still requires the normal N2S case/module A/B,
detector, codemod, validator, rollback contract, and explicit approval.

Use `tooling/n2s-knowledge search`, `show`, and `diff` for version-pinned access. Treat the cached content
as internal, non-commercial reference material and preserve all upstream and third-party license notices.
