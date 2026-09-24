# holdout/ — FINAL HOLDOUT (sealed)

The latest generation of every dataset lives here and **nothing under this
directory is ever read by agent code** (`agents/`, `dsl/`, `engine/`,
`genoframe/`, `campaigns/`, `sim/` runtime paths). Enforced three ways:

1. `make seal-holdout` writes the files, then `chmod -R a-w holdout/`.
2. `common/paths.py::assert_not_holdout()` raises if any loader is handed a
   path that resolves under this directory.
3. `tests/test_firewall.py` greps every prompt and event payload in
   `registry/` for holdout file digests and holdout animal ids, and greps the
   agent-side source tree for the string `holdout`.

Only `campaigns/final_table.py` (the deterministic core, run once at the end
of a campaign) may open the sealed files, and it logs that read as a
`policy_flags=["holdout_final_read"]` event.
