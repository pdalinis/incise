# incise-core

Dependency-free, content-addressed Markdown edit operations used by the
[`incise`](https://github.com/pdalinis/incise) CLI.

The core accepts document text and semantic operation arguments, then returns
either the edited document or an actionable refusal. File I/O, command-line
parsing, and agent integrations live outside this crate.

Its behavior is checked byte-for-byte against the independent Python oracle in
`bench/incise_ops.py`, with additional property tests for preservation,
targeting, and round trips.
