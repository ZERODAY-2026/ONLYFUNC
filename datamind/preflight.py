"""Pre-flight checks. Run: python -m datamind.preflight [--no-llm]

Exit codes: 0 = ready, 2 = ready except configured tables are not loaded yet (run.bat loads them), 1 = problem.
Prints plain [ok]/[warn]/[FAIL] lines and exact fixes; never prints secrets.
"""
import os
import sys
import time

from .config import ROOT, load_config
from .logs import get_logger


def say(tag: str, msg: str) -> None:
    print(f"  [{tag}] {msg}")


def check_env() -> bool:
    ok = True
    for name in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER"):
        if not os.getenv(name):
            say("FAIL", f"{name} is empty in .env")
            ok = False
    key = os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH")
    if key:
        if os.path.exists(key):
            say("ok", "Snowflake auth: key pair")
        else:
            say("FAIL", f"private key file not found: {key}  (run: run.bat keygen)")
            ok = False
    elif os.getenv("SNOWFLAKE_PAT"):
        say("ok", "Snowflake auth: access token")
    elif os.getenv("SNOWFLAKE_PASSWORD"):
        say("ok", "Snowflake auth: password")
    else:
        say("FAIL", "no Snowflake credentials. Easiest: run.bat keygen, then paste the SQL it prints into Snowsight")
        ok = False
    if "ollama.com" in (os.getenv("OLLAMA_HOST") or "") and not os.getenv("OLLAMA_API_KEY"):
        say("FAIL", "OLLAMA_HOST points to Ollama cloud but OLLAMA_API_KEY is empty (https://ollama.com/settings/keys)")
        ok = False
    return ok


def check_snowflake() -> int:
    from .catalog import discover_tables, missing_tables
    from .snowflake_client import connect, run_query
    try:
        conn = connect("SNOWFLAKE_READER_ROLE")
    except Exception as e:
        get_logger().exception("Snowflake login failed")
        say("FAIL", f"Snowflake login: {str(e).splitlines()[0]}")
        say("FAIL", "fixes: check account/user in .env; run setup.sql in Snowsight; for key login make sure the public key is registered")
        return 1
    try:
        role, wh = run_query(conn, "SELECT CURRENT_ROLE(), CURRENT_WAREHOUSE()").rows[0]
        say("ok", f"Snowflake login (role {role}, warehouse {wh})")
        cfg = load_config()
        discover_tables(conn, cfg)
        missing = missing_tables(conn, cfg)
        for d in cfg.datasets:
            if d.auto:
                say("ok", f"dataset {d.name}: {len(d.tables)} extra table(s) discovered in {d.database}.{d.schema}" + (f" ({', '.join(d.tables)})" if d.tables else ""))
                continue
            present = [t for t in d.tables if f"{d.database}.{d.schema}.{t}" not in missing]
            if present:
                n = run_query(conn, f"SELECT COUNT(*) FROM {d.database}.{d.schema}.{present[0]}").rows[0][0]
                say("ok", f"dataset {d.name}: {len(present)}/{len(d.tables)} tables readable ({present[0]}: {n} rows)")
        if missing:
            say("warn", f"tables not found: {', '.join(missing)}")
            # Fixable automatically only if every missing table belongs to a dataset that has a `load:` recipe.
            loadable = {f"{d.database}.{d.schema}.{t}".upper() for d in cfg.datasets if d.load for t in d.tables}
            return 2 if all(m.upper() in loadable for m in missing) else 1
        return 0
    finally:
        conn.close()


def check_gemma() -> bool:
    from . import llm
    host = os.getenv("OLLAMA_HOST") or "local Ollama"
    try:
        t = time.time()
        llm.chat_text("Answer in one word.", "Say OK.")
        say("ok", f"Gemma {llm.model_name()} via {host} ({time.time() - t:.1f}s)")
        return True
    except Exception as e:
        say("FAIL", f"Gemma {llm.model_name()} via {host}: {type(e).__name__}: {str(e).splitlines()[0]}")
        say("FAIL", "fixes: set OLLAMA_API_KEY and OLLAMA_HOST=https://ollama.com, or run local Ollama and `ollama pull gemma3n:e4b`")
        return False


def main() -> int:
    if not (ROOT / ".env").exists():
        say("FAIL", ".env not found")
        return 1
    if not check_env():
        return 1
    code = check_snowflake()
    if code == 1:
        return 1
    if "--no-llm" not in sys.argv and not check_gemma():
        return 1
    return code


if __name__ == "__main__":
    sys.exit(main())
