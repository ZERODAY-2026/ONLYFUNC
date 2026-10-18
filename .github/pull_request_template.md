## What this changes
<!-- One or two sentences. Link the issue if there is one. -->

## How I checked it
- [ ] `python -m pytest tests -q` passes
- [ ] `run.bat smoke` (needed if prompts, the validator or the agent changed). Result:
- [ ] `run.bat eval` (if you can). Score:
- [ ] Couldn't run the live checks (no Snowflake or Gemma access). That's fine, just tick this.

## Before merging
- [ ] New behaviour has a test, and a bug fix has a test that failed before the fix
- [ ] No secrets in the code, logs, screenshots or this description
- [ ] For a new dataset: its source and licence are listed in the README, and no data files are committed
