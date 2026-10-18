"""Workflow: question -> Gemma SQL likhta hai -> validator -> Snowflake chalata hai -> Gemma wapas aayi rows ko explain karta hai."""
import json
import time

import snowflake.connector.errors as sf_errors

from . import llm, trace
from .catalog import describe_examples, describe_schema
from .config import Config
from .grounding import evidence_fallback, numbers_grounded
from .llm import LLMError
from .logs import get_logger
from .models import Answer
from .prompts import EXPLAIN_SYSTEM, SQL_SYSTEM
from .snowflake_client import QueryResult, run_query
from .validator import ValidationError, validate

__all__ = ["Agent", "Answer"]

EXPLAIN_ROWS = 50  # explanation ke liye model ko itni rows dikhai jaati hain
MAX_QUESTION_CHARS = 1000
log = get_logger()


class Agent:
    def __init__(self, conn, cfg: Config):
        self.conn, self.cfg = conn, cfg
        self.system = self._build_system()
        self.history: list[tuple[str, str]] = []  # follow-up questions ke liye (question, sql)

    def _build_system(self) -> str:
        examples = describe_examples(self.cfg)
        schema = describe_schema(self.conn, self.cfg)  # `tables: auto` wale datasets ko bhi dobara discover karta hai
        system = SQL_SYSTEM.format(schema=schema, examples=f"\nExamples:\n{examples}" if examples else "")
        trace.emit("SCHEMA", f"prompt built from live Snowflake columns: schema text {len(schema)} chars, few-shot examples {len(examples)} chars, "
                            f"system prompt {len(system)} chars, {len(self.cfg.datasets)} datasets, {len(self.cfg.allowed_tables())} allowed tables")
        return system

    def refresh_tables(self) -> None:
        """Live schema dobara padhta hai (nayi ya hataayi gayi tables) bina restart kiye; validator ki allowlist bhi saath me update ho jaati hai."""
        self.system = self._build_system()

    def _context(self, question: str, error: str = "", prev_sql: str = "") -> str:
        parts = []
        if self.history:
            parts.append("Earlier in this conversation:\n" + "\n".join(f"Q: {q}\nSQL: {s}" for q, s in self.history[-3:]))
        parts.append(f"Question: {question}")
        if error:
            parts.append(f"Your previous SQL was:\n{prev_sql}\nIt failed with: {error}\nFix it.")
        return "\n\n".join(parts)

    def ask(self, question: str) -> Answer:
        question = (question or "").strip()
        if not question:
            return Answer("clarify", question, message="What would you like to know about the available data?")
        if len(question) > MAX_QUESTION_CHARS:
            return Answer("refused", question[:80] + "...", message=f"The question is too long (limit {MAX_QUESTION_CHARS} characters).")
        started = time.time()
        trace.emit("ASK", f"question received ({len(question)} chars, {len(self.history)} earlier turn(s) in context): {trace.short(question, 120)}")
        try:
            answer = self._ask(question)
        except LLMError as e:
            answer = Answer("error", question, message=str(e))
        log.info("ask status=%s query_id=%s seconds=%.1f question=%r", answer.status, answer.query_id, time.time() - started, question[:200])
        trace.emit("ASK", f"answer ready: status={answer.status} query_id={answer.query_id or '-'} rows={len(answer.rows or [])} total={time.time() - started:.1f}s")
        return answer

    def _ask(self, question: str) -> Answer:
        plan = llm.chat_json(self.system, self._context(question))
        for attempt in range(2):  # ek repair attempt
            action = plan.get("action")
            trace.emit("PLAN", f"attempt {attempt + 1}: Gemma chose action={action!r}, sql={len(plan.get('sql') or '')} chars, "
                              f"assumptions={len(plan.get('assumptions') or [])}" + (f", message: {trace.short(plan.get('message'), 120)}" if plan.get('message') else ""))
            if action == "clarify":
                return Answer("clarify", question, message=plan.get("message", "Could you clarify?"))
            if action != "query":
                return Answer("unsupported", question, message=plan.get("message", "This question cannot be answered from the available data."))
            sql = plan.get("sql", "")
            assumptions = plan.get("assumptions") or []
            try:
                v = validate(sql, self.cfg, self.cfg.max_rows)
            except ValidationError as e:
                trace.emit("VALIDATE", f"REJECTED ({'retryable' if e.retryable else 'final'}): {e}")
                if e.retryable and attempt == 0:
                    plan = llm.chat_json(self.system, self._context(question, str(e), sql))
                    continue
                return Answer("refused", question, message=str(e), sql=sql)
            trace.emit("VALIDATE", f"accepted: read-only, tables={v.tables}; sql {len(sql)} chars -> {len(v.sql)} chars to execute (LIMIT/wrapper added by the validator if missing)")
            try:
                res = run_query(self.conn, v.sql)
            except sf_errors.ProgrammingError as e:
                trace.emit("SQL", f"Snowflake rejected the query (errno {getattr(e, 'errno', '?')}): {trace.short(e.msg, 200)}")
                log.warning("Snowflake rejected SQL (attempt %d, query id %s): %s | %s", attempt + 1, getattr(e, "sfqid", ""), e.msg, v.sql)
                if attempt == 0:
                    plan = llm.chat_json(self.system, self._context(question, e.msg, sql))
                    continue
                return Answer("error", question, message=f"Snowflake rejected the query: {e.msg}", sql=sql)
            return self._finish(question, sql, v, res, assumptions)
        return Answer("error", question, message="Could not produce a valid query.")

    def _finish(self, question, sql, v, res: QueryResult, assumptions) -> Answer:
        self.history.append((question, sql))
        base = dict(question=question, sql=sql, executed_sql=v.sql, tables=v.tables, assumptions=assumptions,
                    columns=res.columns, rows=res.rows, query_id=res.query_id)
        if not res.rows:
            trace.emit("ANSWER", "query returned 0 rows -> answer is 'empty'; no model text is generated")
            return Answer("empty", message="The query ran successfully but returned no rows, so there is no data to answer this.", **base)
        evidence = {
            "question": question, "executed_sql": v.sql, "columns": res.columns,
            "rows": [dict(zip(res.columns, r)) for r in res.rows[:EXPLAIN_ROWS]],
            "assumptions": assumptions, "result_is_truncated": len(res.rows) > EXPLAIN_ROWS,
        }
        warnings: list[str] = []
        try:
            text = llm.chat_text(EXPLAIN_SYSTEM, json.dumps(evidence, default=str))
            grounded = numbers_grounded(text, question, v.sql, assumptions, res.rows)
            trace.emit("GROUND", f"explanation {len(text)} chars; every number appears in the result rows or question: {grounded}")
            if not grounded:
                warnings.append("The model's explanation contained numbers not found in the rows, so exact values are shown instead.")
                text = evidence_fallback(res.columns, res.rows)
        except LLMError as e:
            warnings.append(str(e))
            text = "Snowflake returned data, but Gemma could not explain it. Inspect the result rows."
        return Answer("answered", explanation=text, warnings=warnings, **base)
