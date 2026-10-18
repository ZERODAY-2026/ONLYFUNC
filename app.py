import pandas as pd
import streamlit as st

from datamind.agent import Agent
from datamind.config import load_config
from datamind.logs import get_logger
from datamind.snowflake_client import connect

st.set_page_config(page_title="DataMind", layout="wide")
st.title("DataMind: talk to your data")
st.caption("Gemma writes the SQL. Snowflake computes the answer. Every answer shows the query and the rows.")


@st.cache_resource
def get_agent() -> Agent:
    cfg = load_config()
    return Agent(connect("SNOWFLAKE_READER_ROLE"), cfg)


try:
    agent = get_agent()
except Exception as e:  # missing .env, Snowflake unreachable, etc.
    get_logger().exception("App failed to start")
    # Show config problems (clear, safe text); anything else only by type, details stay in logs/datamind.log.
    st.error(f"Could not start: {e}" if isinstance(e, RuntimeError) else f"Could not start ({type(e).__name__}). See logs/datamind.log, or run: run.bat check")
    st.stop()

with st.sidebar:
    st.subheader("Datasets")
    for d in agent.cfg.datasets:
        st.markdown(f"**{d.name}**: {d.description}  \n_Source: {d.source}; licence: {d.licence}_")
    if st.button("Clear conversation"):
        agent.history.clear()
        st.session_state.pop("log", None)

st.session_state.setdefault("log", [])
for a in st.session_state["log"]:
    st.chat_message("user").write(a.question)
    with st.chat_message("assistant"):
        if a.status == "answered":
            st.write(a.explanation)
        else:
            st.warning(f"[{a.status}] {a.message}")
        for w in a.warnings:
            st.caption(f"Note: {w}")
        if a.sql:
            with st.expander("How this was obtained / evidence"):
                if a.tables:
                    st.markdown("**Tables used:** " + ", ".join(a.tables))
                for note in a.assumptions:
                    st.markdown(f"- Assumption: {note}")
                st.code(a.executed_sql or a.sql, language="sql")
                if a.query_id:
                    st.caption(f"Snowflake query ID: {a.query_id}")
                if a.rows:
                    st.dataframe(pd.DataFrame(a.rows, columns=a.columns))

if q := st.chat_input("Ask a question about your data"):
    with st.spinner("Thinking..."):
        st.session_state["log"].append(agent.ask(q))
    st.rerun()
