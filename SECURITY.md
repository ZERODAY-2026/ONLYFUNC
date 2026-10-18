# Security policy

DataMind sits between a language model and a database, so we take two kinds of problems especially seriously:

- Anything that lets SQL other than a single read-only query reach Snowflake, for example a way around `validator.py`.
- Anything that leaks secrets (keys, tokens, passwords) into logs, the live trace, the UI or the repository.

## Reporting a problem
Please don't open a public issue for a security problem. Instead:

1. Use GitHub's private vulnerability reporting on this repository (Security tab, then "Report a vulnerability") if it's available.
2. If it isn't, open an issue that asks for a private contact, and leave out every detail of the problem.

Tell us what you found, how to reproduce it, and what an attacker could do with it. We'll reply as soon as we can, keep you posted while we work on a fix, and credit you when it's published unless you'd rather we didn't.

## Supported versions
Only the latest code on the `main` branch gets security fixes.

## Keeping your own setup safe
- Keep secrets in `.env` and `.keys/` only. Both are gitignored, so don't force-add them.
- Let the app log in with the read-only role (`DM_READER`). Never point it at ACCOUNTADMIN.
- If a key or token ever ends up in a chat, a screenshot or a commit, revoke it in Snowflake and make a new one. Deleting the message isn't enough.
- Keep `DM_STATEMENT_TIMEOUT` set, so a runaway query can't drain your credits.
