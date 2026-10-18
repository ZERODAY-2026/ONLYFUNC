"""DataMind's live, evidence-first conversation interface."""

from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from datamind import trace
from datamind.agent import Agent
from datamind.chat_store import ChatStore
from datamind.config import Config, Dataset, load_config
from datamind.logs import get_logger
from datamind.models import Answer
from datamind.snowflake_client import connect


st.set_page_config(page_title="DataMind — Ask better questions", page_icon="🟥", layout="wide")
st.markdown(
    f"<style>{(Path(__file__).parent / 'ui.css').read_text(encoding='utf-8')}</style>",
    unsafe_allow_html=True,
)


def get_agent() -> Agent:
    """Keep conversation history and its Snowflake connection private to this session."""
    if "agent" not in st.session_state:
        cfg = load_config()
        trace.emit("UI", f"starting the agent: {len(cfg.datasets)} datasets from datasets.yaml")
        st.session_state.agent = Agent(connect("SNOWFLAKE_READER_ROLE"), cfg)
    return st.session_state.agent


@st.cache_resource
def get_chat_store() -> ChatStore:
    return ChatStore(Path(__file__).parent / "data" / "chats")


def chart_data(frame: pd.DataFrame) -> tuple[str, str, pd.DataFrame] | None:
    """Offer a chart only for an actual small categorical + numeric result."""
    if not 2 <= len(frame) <= 50 or len(frame.columns) < 2:
        return None
    label = next(
        (c for c in frame if frame[c].dtype == "object" and frame[c].nunique() == len(frame)),
        None,
    )
    if label is None:
        return None
    for column in frame:
        if column == label:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.notna().all():
            return label, column, pd.DataFrame({label: frame[label], column: values})
    return None


def catalogue_entry(table_name: str, cfg: Config) -> tuple[Dataset, str] | None:
    """Find the configured dataset entry for an evidence table name."""
    normalized = table_name.upper()
    for dataset in cfg.datasets:
        for table in dataset.tables:
            qualified = f"{dataset.database}.{dataset.schema}.{table}".upper()
            if normalized == qualified:
                return dataset, table.upper()
    return None


def render_context(answer: Answer, cfg: Config, saved_snapshot: bool) -> None:
    """Show evidence-derived context without making a second model call."""
    row_count = len(answer.rows)
    source_count = len(answer.tables)
    freshness = "Saved snapshot" if saved_snapshot else "Live Snowflake result"
    result_shape = "Single returned value" if row_count == 1 else f"{row_count:,} returned rows"
    result_sentence = "one returned value" if row_count == 1 else f"{row_count:,} returned rows"
    fields = ", ".join(answer.columns) if answer.columns else "No result fields"

    st.markdown(
        '<div class="context-lede"><span>ANSWER BRIEF</span>'
        '<strong>What this result means, where it came from, and how to verify it.</strong></div>',
        unsafe_allow_html=True,
    )
    if answer.explanation or answer.message:
        st.markdown(
            f'<div class="context-summary"><small>PLAIN-ENGLISH READING</small><p>{escape(answer.explanation or answer.message)}</p></div>',
            unsafe_allow_html=True,
        )
    st.markdown(
        '<div class="context-facts">'
        f'<div><small>RESULT SHAPE</small><b>{escape(result_shape)}</b></div>'
        f'<div><small>SOURCE COVERAGE</small><b>{source_count} table{"s" if source_count != 1 else ""}</b></div>'
        f'<div><small>DATA STATE</small><b>{freshness}</b></div>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="context-section-title">DATA SCOPE</div>', unsafe_allow_html=True)
    entries = [entry for table in answer.tables if (entry := catalogue_entry(table, cfg))]
    if entries:
        for dataset, table in entries:
            details = [dataset.description]
            if dataset.scope:
                details.append(dataset.scope)
            if table in dataset.notes:
                details.append(dataset.notes[table])
            st.markdown(
                f'<div class="source-card"><div><small>CONFIGURED SOURCE</small><strong>{escape(dataset.name.replace("_", " ").upper())}</strong>'
                f'<span>{escape(dataset.database)}.{escape(dataset.schema)}.{escape(table)}</span></div>'
                f'<p>{escape(" ".join(details))}</p></div>',
                unsafe_allow_html=True,
            )
    elif answer.tables:
        for table in answer.tables:
            st.code(table, language=None)
    else:
        st.caption("No source table was recorded for this response.")

    st.markdown('<div class="context-section-title">INTERPRETATION & LIMITS</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="interpretation-card"><b>Reported fields</b><span>{escape(fields)}</span>'
        f'<p>This answer reflects {escape(result_sentence)} from the executed read-only query. '
        'Use the Query tab to inspect its filters, joins and calculation before applying the result elsewhere.</p></div>',
        unsafe_allow_html=True,
    )
    if answer.assumptions:
        st.markdown('<div class="context-section-title">ASSUMPTIONS</div>', unsafe_allow_html=True)
        for note in answer.assumptions:
            st.markdown(f'<div class="assumption-note">↗ {escape(note)}</div>', unsafe_allow_html=True)
    else:
        st.caption("No additional assumptions were recorded for this query.")

    st.markdown('<div class="context-section-title">VERIFICATION TRAIL</div>', unsafe_allow_html=True)
    verification = (
        "Gemma translated the question, DataMind validated a single read-only query against the approved catalogue, "
        "and Snowflake produced the rows. The explanation is generated only from those returned rows."
    )
    st.markdown(f'<div class="verification-note">{verification}</div>', unsafe_allow_html=True)
    if answer.query_id:
        st.code(answer.query_id, language=None)
        st.caption("Snowflake query ID · locate this exact run in Snowflake query history.")


def render_answer(answer: Answer, index: int, cfg: Config, saved_snapshot: bool = False) -> None:
    with st.chat_message("user"):
        st.markdown('<div class="message-kicker">YOU / QUESTION</div>', unsafe_allow_html=True)
        st.write(answer.question)
    with st.chat_message("assistant"):
        st.markdown(f'<div class="message-kicker">DATAMIND / RESPONSE {index + 1:02d}</div>', unsafe_allow_html=True)
        if saved_snapshot:
            st.caption("Saved snapshot · These are the original query results. Re-ask to get current data.")
        if answer.status == "answered":
            st.write(answer.explanation)
        elif answer.status == "empty":
            st.info(answer.message or "No matching rows were returned. Try a wider date range or filter.")
        elif answer.status == "clarify":
            st.info(answer.message or "Could you narrow down the question?")
        else:
            st.warning(answer.message or f"This question could not be answered ({answer.status}).")

        for warning in answer.warnings:
            st.caption(f"Note: {warning}")
        if not answer.sql:
            return

        st.markdown('<div class="evidence-label">THE RECEIPTS <span>— INSPECT THE RESULT</span></div>', unsafe_allow_html=True)
        data_tab, sql_tab, context_tab = st.tabs(["▦ Results", "⌘ Query", "✦ Evidence"])
        with data_tab:
            if answer.rows:
                frame = pd.DataFrame(answer.rows, columns=answer.columns)
                freshness = "Saved Snowflake result" if saved_snapshot else "Live Snowflake result"
                st.markdown(
                    '<div class="result-ribbon">'
                    f'<span>RESULT SET</span><b>{len(frame):,} row{"s" if len(frame) != 1 else ""}</b>'
                    f'<span>{len(answer.tables)} source table{"s" if len(answer.tables) != 1 else ""}</span>'
                    f'<em>{freshness}</em></div>',
                    unsafe_allow_html=True,
                )
                st.dataframe(frame, use_container_width=True, hide_index=True)
                chart = chart_data(frame)
                if chart:
                    label, metric, plot = chart
                    with st.expander("See as a chart"):
                        st.bar_chart(plot.set_index(label)[metric], color="#d91528")
                st.download_button(
                    "↓  Download these rows as CSV",
                    frame.to_csv(index=False).encode("utf-8"),
                    file_name=f"datamind-result-{index + 1}.csv",
                    mime="text/csv",
                    key=f"download-{index}",
                )
            else:
                st.caption("The query returned no rows.")
        with sql_tab:
            st.markdown('<div class="query-intro"><span>QUERY AUDIT</span> This is the exact read-only statement sent to Snowflake.</div>', unsafe_allow_html=True)
            st.code(answer.executed_sql or answer.sql, language="sql")
            if answer.query_id:
                st.code(answer.query_id, language=None)
                st.caption("Snowflake query ID — use this to verify the run in query history.")
        with context_tab:
            render_context(answer, cfg, saved_snapshot)


try:
    agent = get_agent()
    chat_store = get_chat_store()
except Exception as error:
    get_logger().exception("App failed to start")
    st.error(
        f"Could not start: {error}"
        if isinstance(error, RuntimeError)
        else f"Could not start ({type(error).__name__}). See logs/datamind.log or run: run.bat check"
    )
    st.stop()

st.session_state.setdefault("log", [])
st.session_state.setdefault("active_chat_id", None)
st.session_state.setdefault("active_chat_title", "")
st.session_state.setdefault("snapshot_count", 0)
datasets = [d for d in agent.cfg.datasets if not (d.auto and not d.tables)]

with st.sidebar:
    st.markdown(
        '<div class="sidebar-brand"><span class="brand-mark">DM.</span>'
        '<div><strong>DATAMIND</strong><small>THE DATA EDITION</small></div></div>',
        unsafe_allow_html=True,
    )
    st.caption("Your questions. Real answers. Full receipts.")
    if st.button("＋  New conversation", key="new-chat", type="primary", use_container_width=True):
        agent.history.clear()
        st.session_state.log = []
        st.session_state.active_chat_id = None
        st.session_state.active_chat_title = ""
        st.session_state.snapshot_count = 0
        st.rerun()

    st.markdown('<div class="sidebar-kicker">01 / CHAT ARCHIVE</div>', unsafe_allow_html=True)
    search = st.text_input("Search past conversations", placeholder="Search conversations", label_visibility="collapsed", key="chat_search")
    try:
        past_chats = chat_store.list_chats(search)
    except Exception as error:
        get_logger().exception("Could not read saved conversations")
        st.error(f"Could not read saved chats ({type(error).__name__}). See logs/datamind.log.")
        past_chats = []
    if not past_chats:
        st.caption("No saved chats match your search." if search else "Your conversations will appear here after your first question.")
    today = datetime.now().astimezone().date()
    with st.container(height=min(250, 42 * len(past_chats) + 52) if past_chats else 1, border=False):
        for group, entries in (
            ("TODAY", [c for c in past_chats if datetime.fromisoformat(c["updated_at"]).astimezone().date() == today]),
            ("EARLIER", [c for c in past_chats if datetime.fromisoformat(c["updated_at"]).astimezone().date() != today]),
        ):
            if entries:
                st.markdown(f'<div class="chat-group-label">{group}</div>', unsafe_allow_html=True)
            for chat in entries:
                selected = chat["id"] == st.session_state.active_chat_id
                if st.button(
                    f"{'▸ ' if selected else ''}{chat['title']}",
                    key=f"open-chat-{chat['id']}",
                    type="primary" if selected else "secondary",
                    help=f"Last updated {chat['updated_at'][:16].replace('T', ' ')} UTC",
                    use_container_width=True,
                ):
                    try:
                        selected_chat, answers = chat_store.load(chat["id"])
                    except Exception as error:
                        get_logger().exception("Could not open saved conversation")
                        st.error(f"Could not open this chat ({type(error).__name__}). See logs/datamind.log.")
                    else:
                        st.session_state.active_chat_id = chat["id"]
                        st.session_state.active_chat_title = selected_chat["title"]
                        st.session_state.log = answers
                        st.session_state.snapshot_count = len(answers)
                        agent.history = [(a.question, a.sql) for a in answers if a.status in {"answered", "empty"} and a.sql]
                        st.rerun()

    st.markdown('<div class="sidebar-kicker">02 / DATA LIBRARY</div>', unsafe_allow_html=True)
    st.caption(f"{len(datasets)} datasets · {sum(len(d.tables) for d in datasets)} configured tables")
    st.caption("Open a source to see its coverage and licence.")
    for dataset in datasets:
        label = dataset.name.upper() if dataset.name in {"tpch", "tpcds", "owid"} else dataset.name.replace("_", " ").title()
        with st.expander(label):
            st.write(dataset.description)
            st.caption(f"Database: {dataset.database}.{dataset.schema}")
            st.caption(f"Source: {dataset.source}")
            st.caption(f"Licence: {dataset.licence}")
            st.caption(f"{len(dataset.tables)} configured tables")

    st.markdown('<div class="sidebar-kicker">03 / STUDIO</div>', unsafe_allow_html=True)
    count = len(st.session_state.log)
    st.caption(f"{count} question{'s' if count != 1 else ''} in this conversation")
    if st.button("↻  Re-scan tables", key="rescan", use_container_width=True):
        try:
            agent.refresh_tables()
        except Exception as error:
            get_logger().exception("Table re-scan failed")
            st.error(f"Re-scan failed ({type(error).__name__}). See logs/datamind.log.")
        else:
            st.rerun()
    st.markdown(
        '<div class="sidebar-foot"><b>THE METHOD</b><br>'
        'Gemma translates questions to SQL. Snowflake runs read-only queries. '
        'You can inspect the rows, SQL and query ID behind every result.</div>',
        unsafe_allow_html=True,
    )
    st.caption(f"Result previews show up to {agent.cfg.max_rows} rows; calculations run in Snowflake.")

st.markdown(
    '<div class="topline"><span>THE DATA EDITION <b> /  DATAMIND</b></span>'
    '<span><i class="live-dot"></i> CONNECTED TO SNOWFLAKE</span></div>',
    unsafe_allow_html=True,
)
if st.session_state.pop("history_error", None):
    st.warning("This answer could not be saved. Check logs/datamind.log; keep this tab open until resolved.")

if not st.session_state.log:
    st.markdown(
        '<div class="hero"><div class="hero-copy"><div class="hero-kicker">ISSUE 01 / A BETTER WAY TO EXPLORE</div>'
        '<h1>Data has<br><em>a story.</em></h1>'
        '<p>Ask in plain English. Explore the answer. Follow every number back to '
        'the rows and query that produced it.</p></div>'
        '<div class="hero-stamp"><span>CHECK THE RECEIPTS.</span><strong>ASK.<br>SEE.<br>VERIFY.</strong>'
        '<small>GEMMA × SNOWFLAKE<br>READ-ONLY ANALYSIS</small></div></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="ticker" aria-label="DataMind: ask, analyze, verify">'
        '<div class="ticker-track">ASK BETTER QUESTIONS ✳ FOLLOW THE DATA ✳ SEE THE EVIDENCE ✳ '
        'ASK BETTER QUESTIONS ✳ FOLLOW THE DATA ✳ SEE THE EVIDENCE ✳ </div></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="how-strip"><div><b>01</b> ASK A QUESTION</div>'
        '<div><b>02</b> GEMMA WRITES SQL</div><div><b>03</b> SNOWFLAKE COMPUTES</div>'
        '<div><b>04</b> INSPECT THE RECEIPTS</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="starter-label">OPENING QUESTIONS <span>↘</span></div>', unsafe_allow_html=True)
    examples = [
        ("tpch", "How many orders are there?", "Start with the big picture"),
        ("wine_quality", "Compare average quality of red and white wines", "Find a pattern"),
        ("owid", "How has life expectancy changed in India since 2000?", "Follow a trend"),
    ]
    available = {d.name for d in datasets}
    examples = [(q, subtitle) for name, q, subtitle in examples if name in available]
    for column, (question, subtitle) in zip(st.columns(min(3, len(examples)) or 1), examples):
        with column:
            st.caption(subtitle.upper())
            if st.button(f"{question}  ↗", key=f"starter-{question}", use_container_width=True):
                st.session_state.pending_question = question
                st.rerun()
else:
    notebook_mode = "SAVED SNAPSHOT" if st.session_state.snapshot_count == len(st.session_state.log) else "LIVE SESSION"
    st.markdown(f'<div class="conversation-title"><small>YOUR WORKING NOTEBOOK / {notebook_mode}</small> The conversation<span>.</span></div>', unsafe_allow_html=True)
    if st.session_state.active_chat_title:
        st.caption(st.session_state.active_chat_title)
    for index, answer in enumerate(st.session_state.log):
        render_answer(answer, index, agent.cfg, index < st.session_state.snapshot_count)
    st.markdown(
        '<div class="next-prompt">KEEP DIGGING ↗ &nbsp; Ask a follow-up, change the angle, or compare another source.</div>',
        unsafe_allow_html=True,
    )

pending = st.session_state.pop("pending_question", None)
question = st.chat_input("Ask the data. Follow the evidence…") or pending
if question:
    trace.emit("UI", f"question submitted in the browser ({len(question)} chars)")
    with st.spinner("Working through the data…"):
        answer = agent.ask(question)
        st.session_state.log.append(answer)
        try:
            if st.session_state.active_chat_id is None:
                st.session_state.active_chat_id = chat_store.create(question)
            chat_store.append(st.session_state.active_chat_id, answer)
            st.session_state.active_chat_title = chat_store.load(st.session_state.active_chat_id)[0]["title"]
        except Exception as error:
            get_logger().exception("Could not save conversation")
            st.session_state.history_error = f"This answer could not be saved ({type(error).__name__}). Check logs/datamind.log."
    st.rerun()
