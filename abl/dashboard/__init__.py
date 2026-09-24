"""Guardian & Learning dashboard (OPS.md D) — a separate, read-only process.

It tails registry/events.jsonl and reads the SQLite registry through
``registry.db.connect_readonly``; it never imports agent, engine or gate code.
The only files it writes: dashboard/state.json, control/PAUSE (operator action),
registry/alarms.log and registry/digest_YYYY-MM-DD.md.
"""
