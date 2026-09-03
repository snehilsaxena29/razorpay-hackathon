# Cassettes

Recorded provider exchanges, replayed so a run can be reproduced without a key.

**This directory ships empty.** A cassette is only useful if it covers a whole
run: a partial one produces mostly misses, and a run where eight of ten attacks
miss still computes a safety score from the two that did not. That number reads
exactly like a clean run and means nothing, which is the most dangerous shape a
safety report can take. (The harness now refuses to headline a score below 50%
coverage — see `SafetyScore.is_representative` — but the cassette should be
whole regardless.)

`make demo` does not need this directory. It runs the deterministic stub agents,
which need no provider at all.

## Recording one

Needs a provider with enough quota for a full run — roughly 200 model calls for
both agents across the catalogue, which is more than a Groq free tier allows in
a day.

```bash
export GROQ_API_KEY=...
python scripts/smoke_groq.py     # confirm the key and model id first
make record                      # writes reference_agents.json
```

Then verify the recording is complete before trusting it:

```bash
unset GROQ_API_KEY
python -m gauntlet run --agent naive     # every attack should resolve
```

Any `ERROR: no recorded response` means the cassette is incomplete for that
prompt. Re-record rather than shipping it.
