"""Live trace: har connection, network call, SQL statement, model call aur workflow step ke liye console par ek line.

DM_TRACE se on/off hota hai (run.bat isse on karta hai; DM_TRACE=0 karo toh chup ho jaata hai). Lines stderr par jaati hain, toh run.bat
window me turant dikhti hain, aur logs/datamind.log me bhi copy hoti hain. Yahan kuch bhi behaviour nahi badalta; bas batata hai ki
code ne asal me kya kiya: sizes, row counts, status codes, timings, Snowflake query IDs. Secrets (keys, tokens, passwords) kabhi print nahi hote.
"""
import logging
import os
import re
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime

_TRUE = {"1", "true", "yes", "on"}
_lock = threading.Lock()


def on() -> bool:
    return os.getenv("DM_TRACE", "").strip().lower() in _TRUE


def short(text, limit: int = 160) -> str:
    """Ek line, whitespace collapse, asli length likhi hui: 'SELECT ... (+312 chars)'."""
    flat = re.sub(r"\s+", " ", str(text)).strip()
    return flat if len(flat) <= limit else f"{flat[:limit]}... (+{len(flat) - limit} chars)"


def emit(tag: str, message: str) -> None:
    if not on():
        return
    line = f"{datetime.now():%H:%M:%S.%f}"[:-3] + f"  {tag:<9} {message}"
    with _lock:
        print(line, file=sys.stderr, flush=True)
    try:
        from .logs import get_logger
        get_logger().info("TRACE %s %s", tag, message)
    except Exception:  # tracing se app kabhi nahi tootni chahiye
        pass


@contextmanager
def span(tag: str, start: str, quiet_start: bool = False):
    """`start` abhi print karta hai (taaki slow calls chalte waqt dikhein) aur baad me outcome elapsed time ke saath.
    Body `info` (ek dict) me jo seekha woh bharti hai, jaise rows=3 query_id=...; exception aaye toh error ka type dikhta hai."""
    info: dict = {}
    began = time.perf_counter()
    if not quiet_start:
        emit(tag, f"-> {start}")
    try:
        yield info
    except BaseException as e:
        emit(tag, f"<- FAILED after {(time.perf_counter() - began) * 1000:.0f} ms: {type(e).__name__}: {short(str(e), 200)}")
        raise
    details = " ".join(f"{k}={v}" for k, v in info.items())
    emit(tag, f"<- {'ok ' if not quiet_start else ''}{(time.perf_counter() - began) * 1000:.0f} ms {details}".rstrip())


# ---------------------------------------------------------------- network
class _NetHandler(logging.Handler):
    """Snowflake connector ke apne debug log (logger snowflake.connector) ko [NET] lines me badalta hai: uska har HTTP call
    (login, query, result-chunk downloads, logout, cloud-metadata probes), response sizes aur server round-trip times.
    Query strings aur headers kabhi nahi dikhaye jaate."""
    _call = re.compile(r"outbound HTTP call method=(\w+)(?: host=(\S+))? path=(\S+?)(?:\?\S*)?(?: attempt=(\d+))?$")
    _resp = re.compile(r"Received HTTP response response_len=(\d+)")
    _query = re.compile(r"Sync query response received elapsed_ms=([\d.]+)")
    _login = re.compile(r"Making Snowflake login request login_url=([^\s?]+)")

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
            if m := self._call.search(msg):
                method, host, path, attempt = m.groups()
                target = f"{host}{path}" if host else path
                emit("NET", f"{method} {target}" + (f" (attempt {attempt})" if attempt and attempt != "1" else ""))
            elif m := self._resp.search(msg):
                emit("NET", f"   <- response received, {int(m.group(1)):,} bytes")
            elif m := self._query.search(msg):
                emit("NET", f"   <- Snowflake answered the query request in {float(m.group(1)):.0f} ms (server round trip)")
            elif m := self._login.search(msg):
                emit("NET", f"login request to {m.group(1)}")
        except Exception:
            pass


_net_installed = False


def install_network_trace() -> None:
    """Snowflake connector ke log ko hook karta hai taaki uski har request report ho. Idempotent hai; DM_TRACE on na ho toh kuch nahi karta."""
    global _net_installed
    if _net_installed or not on():
        return
    lg = logging.getLogger("snowflake.connector")
    lg.setLevel(logging.DEBUG)
    lg.addHandler(_NetHandler(level=logging.DEBUG))
    _net_installed = True


def httpx_hooks(label: str) -> dict:
    """httpx client (Ollama client) ke liye event_hooks: har request aur uska response status aur size report karta hai.
    Authorization header kabhi padha nahi jaata."""
    starts: dict[int, float] = {}

    def on_request(request):
        starts[id(request)] = time.perf_counter()
        size = request.headers.get("content-length", "?")
        emit("NET", f"{request.method} {request.url.scheme}://{request.url.host}{request.url.path} ({label}) sending {size} bytes")

    def on_response(response):
        began = starts.pop(id(response.request), None)
        took = f" in {(time.perf_counter() - began) * 1000:.0f} ms" if began else ""
        emit("NET", f"{response.request.method} {response.request.url.host}{response.request.url.path} -> HTTP {response.status_code}"
                    f" ({response.headers.get('content-length', 'streamed')} bytes){took}")

    return {"request": [on_request], "response": [on_response]} if on() else {}


# ---------------------------------------------------------------- environment report (run.bat step 4)
_SECRET_NAMES = ("PASSWORD", "TOKEN", "PAT", "API_KEY", "PRIVATE_KEY")
_SHOWN_VALUES = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_READER_ROLE", "SNOWFLAKE_LOADER_ROLE",
                 "OLLAMA_HOST", "GEMMA_MODEL", "DM_STATEMENT_TIMEOUT")


def environment_report() -> None:
    """Dikhata hai ki app asal me kis par aur kaise chal rahi hai. Secret values kabhi nahi dikhti, sirf yeh ki set hain ya nahi."""
    import importlib.metadata as md
    import platform

    from .config import ROOT, load_config  # noqa: F401  (config import karne se .env bhi load ho jaata hai)

    emit("ENV", f"Python {platform.python_version()} on {platform.system()} {platform.release()} ({platform.machine()})")
    versions = []
    for name in ("snowflake-connector-python", "streamlit", "ollama", "sqlglot", "pandas", "pyyaml", "ucimlrepo", "cryptography"):
        try:
            versions.append(f"{name} {md.version(name)}")
        except md.PackageNotFoundError:
            versions.append(f"{name} MISSING")
    emit("ENV", "packages: " + ", ".join(versions))
    names = sorted(k for k in os.environ if k.startswith(("SNOWFLAKE_", "OLLAMA_", "GEMMA_", "DM_")))
    shown = [f"{k}={os.environ[k]}" for k in names if k in _SHOWN_VALUES and os.environ[k]]
    hidden = [f"{k}({'set' if os.environ[k] else 'EMPTY'})" for k in names if any(s in k for s in _SECRET_NAMES)]
    emit("ENV", "settings: " + ", ".join(shown))
    emit("ENV", "secrets (values never shown): " + ", ".join(hidden))
    cfg = load_config()
    emit("ENV", f"datasets.yaml: {len(cfg.datasets)} datasets, {len(cfg.allowed_tables())} allowed tables, max_rows={cfg.max_rows}")
    for d in cfg.datasets:
        emit("ENV", f"  {d.name:<20} {d.database}.{d.schema}  tables={len(d.tables)}{' (auto)' if d.auto else ''}  load={'yes' if d.load else 'no (read in place)'}")


if __name__ == "__main__":
    os.environ.setdefault("DM_TRACE", "1")
    environment_report()
