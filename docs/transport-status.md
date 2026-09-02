# Transport status has moved

Since 0.4 the Microduck's four transports are the backends of the `microduck` adapter, and
the honesty table for every adapter, the Microduck included, lives at
[adapter-status.md](adapter-status.md). The VERIFIED and UNVERIFIED rows for
`duck-ipc-proto` are there, unchanged; the other robots have their own pages under
[adapters/](adapters/).

`--transport X` still works for one release as an alias of `--robot microduck:X`.
