# Contributing to DataMind

Thanks for thinking about helping. Small fixes are just as welcome as big features: a clearer error message, a typo, a new dataset, a test that catches a bug we missed.

## Before you start
- For anything bigger than a small fix, please open an issue first and tell us what you have in mind. That way nobody spends an evening on something that clashes with work already under way.
- Bugs and ideas both go in [GitHub issues](../../issues). The templates there ask for the details we usually need.

## Setting up
Follow [Getting started](README.md#getting-started) in the README. In short, you need Python 3.10 or newer, a Snowflake trial account and access to a Gemma model through Ollama.

Most of the code can be worked on without any accounts at all. The unit tests run fully offline:

```bash
python -m pytest tests -q        # or: run.bat test
```

## How the code is organised
Each module does one job, and we'd like to keep it that way:

- `llm.py` and `prompts.py` talk to Gemma. They never touch data.
- `snowflake_client.py` is the only place that talks to Snowflake.
- `validator.py` decides what SQL is allowed to run.
- `grounding.py` checks that an explanation's numbers really appear in the result rows.
- `agent.py` ties the steps together. `app.py` is only the UI.

Two rules matter more than any others:

1. **Gemma never computes data, and Snowflake never interprets language.** If a change asks the model to calculate something, it's in the wrong place.
2. **No mocks, fake rows or hard-coded answers in the app.** Every answer must come from a real query run at question time. Fakes are fine in `tests/`, and only there.

## Adding a dataset
This is one of the most useful things you can contribute, and it shouldn't need any Python.

1. Add an entry to `datasets.yaml` with the database, schema and tables. Add a `load:` recipe (`uci` or `csv`) if the data has to be loaded.
2. Describe the data: column meanings, the allowed joins and any metric definitions. The model follows these literally, so check them against the real data.
3. Add a handful of questions to `eval/questions.yaml`, each with truth SQL you wrote yourself. Don't copy the agent's SQL into the truth, because then the test proves nothing.
4. Run `run.bat load`, then `run.bat eval --category <yours>` or `run.bat eval --only <ids>`, and include the result in your pull request.
5. In the README's dataset table, list where the data comes from and its licence. Only use data whose licence allows it, and never commit the data files themselves.

## Before you open a pull request
- `python -m pytest tests -q` passes.
- If you changed prompts, the validator or the agent, run `run.bat smoke`. If you can, run `run.bat eval` too, and tell us the score. If you couldn't run them (they need Snowflake and Gemma), just say so. That's fine.
- New behaviour comes with a test. Bug fixes come with a test that failed before the fix.
- No secrets anywhere: not in code, logs, screenshots or the pull request description. `.env` and `.keys/` are gitignored for a reason.
- Errors reach the user as a short, clear message, and the full details go to `logs/datamind.log`. Please don't swallow exceptions.
- Keep the pull request focused on one thing. Unrelated refactors are easier to review on their own.

## Style
- Follow the style of the code around your change: plain names, short functions, a docstring where the reason isn't obvious.
- Comments explain why, not what.
- In docs and messages, write the way you'd explain it to a colleague. Short sentences and plain words beat clever ones.

## Licence
DataMind is MIT licensed. By contributing, you agree that your contribution is released under the same [licence](LICENSE).

## Code of Conduct
Everyone taking part is expected to follow our [Code of Conduct](CODE_OF_CONDUCT.md).
