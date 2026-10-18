"""Workflow: question -> Gemma SQL likhta hai -> validator -> Snowflake chalata hai -> Gemma wapas aayi rows ko explain karta hai."""
import json
import os
import time

import snowflake.connector.errors as sf_errors

from . import llm, trace
from .catalog import describe_examples, describe_schema
from .config import Config
from .grounding import evidence_fallback, numbers_grounded
from .llm import LLMError
from .logs import get_logger
from .models import Answer
from .prompts import EXPLAIN_SYSTEM, SPLIT_RULE, SQL_SYSTEM, SUGGEST_SYSTEM
from .snowflake_client import QueryResult, run_query
from .validator import ValidationError, validate

__all__ = ["Agent", "Answer"]

EXPLAIN_ROWS = 50  # explanation ke liye model ko itni rows dikhai jaati hain
SUGGEST_ROWS = 10  # follow-up suggestions ke liye itni rows kaafi hain
MAX_SUGGESTIONS = 3
MIN_SUGGESTION_CHARS = 8
MAX_SUGGESTION_CHARS = 140
MAX_PARTS = 3  # multipart sawal me zyada se zyada itne hisse
MAX_QUESTION_CHARS = 1000
log = get_logger()


def multipart_enabled() -> bool:
    """DM_MULTIPART=0 se poora multipart feature (prompt ka extra rule bhi) band ho jaata hai."""
    return os.getenv("DM_MULTIPART", "1").strip().lower() not in {"0", "false", "no", "off"}


class Agent:
    def __init__(self, conn, cfg: Config, allow_split: bool = True):
        self.conn, self.full_cfg = conn, cfg
        self.allow_split = allow_split           # child agent kabhi split nahi karta: recursion nahi, sirf ek level
        self._children: dict[str, Agent] = {}    # dataset -> uska single-dataset agent (schema ek baar padh kar cache)
        self.cfg = cfg                      # abhi active datasets; set_scope() isko chhota kar sakta hai
        self.scope: list[str] | None = None  # None = saare datasets
        self.system = self._build_system()
        self.history: list[tuple[str, str]] = []  # follow-up questions ke liye (question, sql)

    def _build_system(self) -> str:
        examples = describe_examples(self.cfg)
        schema = describe_schema(self.conn, self.cfg)  # `tables: auto` wale datasets ko bhi dobara discover karta hai
        if self.scope:
            off = [d.name for d in self.full_cfg.datasets if d.name not in self.scope]
            schema += (f"\nDatasets enabled for this conversation: {', '.join(self.scope)}. Other datasets exist ({', '.join(off)}) but are switched off. "
                       "If the question needs a switched-off dataset, reply with action 'unsupported' and name the dataset the user should switch on.")
        system = SQL_SYSTEM.format(schema=schema, examples=f"\nExamples:\n{examples}" if examples else "")
        if self._split_on():
            system += SPLIT_RULE
        trace.emit("SCHEMA", f"prompt built from live Snowflake columns: schema text {len(schema)} chars, few-shot examples {len(examples)} chars, "
                            f"system prompt {len(system)} chars, {len(self.cfg.datasets)} datasets, {len(self.cfg.allowed_tables())} allowed tables")
        return system

    def set_scope(self, names) -> None:
        """Sirf chune hue datasets par sawal poochne do: prompt me bhi wahi tables jaati hain aur validator bhi sirf unhi ko allow karta hai."""
        wanted = list(dict.fromkeys(names))
        known = [d.name for d in self.full_cfg.datasets]
        unknown = [n for n in wanted if n not in known]
        if not wanted or unknown:
            raise ValueError("Choose at least one dataset" if not wanted else f"Unknown dataset(s): {', '.join(unknown)}")
        self.scope = None if set(wanted) == set(known) else [n for n in known if n in wanted]
        self.cfg = self.full_cfg if self.scope is None else self.full_cfg.subset(self.scope)
        trace.emit("SCOPE", f"datasets enabled: {', '.join(self.scope or known)}")
        self._children.clear()
        self.system = self._build_system()

    def _split_on(self) -> bool:
        """Split tabhi jab feature on ho, yeh parent agent ho, aur kam se kam 2 datasets chale hue hon (ek dataset me split ka matlab nahi)."""
        return self.allow_split and multipart_enabled() and sum(1 for d in self.cfg.datasets if d.tables) >= 2

    def _child(self, dataset: str) -> "Agent":
        if dataset not in self._children:
            self._children[dataset] = Agent(self.conn, self.cfg.subset([dataset]), allow_split=False)
        return self._children[dataset]

    def _split(self, question: str, plan: dict) -> Answer:
        """Sawal ko alag datasets ke hisson me baant kar har hissa ek single-dataset child agent se poochta hai: wahi validator, wahi read-only
        role, wahi repair aur grounding. Hisson ke jawab sirf jode jaate hain (har ek ka apna verified explanation); koi merged number nahi banta."""
        known = {d.name for d in self.cfg.datasets if d.tables}
        parts, seen = [], set()
        for item in plan.get("parts") if isinstance(plan.get("parts"), list) else []:
            q = " ".join(str(item.get("question", "")).split()) if isinstance(item, dict) else ""
            ds = item.get("dataset") if isinstance(item, dict) else None
            if q and ds in known and q.casefold() not in seen:   # pehle duplicate/ghalat hatao, phir limit lagao
                seen.add(q.casefold())
                parts.append((q, ds))
                if len(parts) == MAX_PARTS:
                    break
        trace.emit("SPLIT", f"Gemma split the question into {len(parts)} part(s): " + "; ".join(f"[{ds}] {trace.short(q, 70)}" for q, ds in parts))
        if len({ds for _, ds in parts}) == 1:   # sab hisse ek hi dataset ke: asal me split nahi, seedha us dataset se poochho
            return self._child(parts[0][1])._ask(question)
        if len(parts) < 2:
            return Answer("unsupported", question, message=plan.get("message") or "This question needs more than one dataset, but it could not be split into separate parts I can answer.")
        steps: list[Answer] = []
        for number, (q, ds) in enumerate(parts, 1):
            child = self._child(ds)
            child.history.clear()
            trace.emit("SPLIT", f"part {number}/{len(parts)} -> dataset {ds}: {trace.short(q, 100)}")
            try:
                step = child._ask(q)
            except LLMError as e:
                step = Answer("error", q, message=str(e))
            step.trace = []
            steps.append(step)
            trace.emit("SPLIT", f"part {number}/{len(parts)} finished: status={step.status} query_id={step.query_id or '-'}")
        good = [s for s in steps if s.status in {"answered", "empty"}]
        text = []
        for number, ((q, ds), step) in enumerate(zip(parts, steps), 1):
            body = (step.explanation if step.status == "answered" else step.message if step.status == "empty"
                    else f"This part could not be answered: {step.message or step.status}")
            text.append(f"**Part {number} · {ds.replace('_', ' ')}**: {q}\n\n{body}")
        if not good:
            return Answer("error", question, message="None of the parts could be answered.\n\n" + "\n\n".join(text), steps=steps)
        text.append("*These parts come from separate datasets with no declared link between them, so each is answered on its own and no combined figure is calculated.*")
        self.history.extend((s.question, s.sql) for s in good if s.sql)
        sql = "\n\n".join(f"-- Part {i}: {s.question}\n{s.sql}" for i, s in enumerate(good, 1) if s.sql)
        executed = "\n\n".join(f"-- Part {i}: {s.question}\n{s.executed_sql}" for i, s in enumerate(good, 1) if s.executed_sql)
        return Answer("answered", question, sql=sql, executed_sql=executed, explanation="\n\n".join(text), steps=steps,
                      tables=list(dict.fromkeys(t for s in good for t in s.tables)),
                      assumptions=[f"Part {i}: {a}" for i, s in enumerate(steps, 1) for a in s.assumptions],
                      warnings=[f"Part {i}: {w}" for i, s in enumerate(steps, 1) for w in s.warnings],
                      query_id=", ".join(s.query_id for s in good if s.query_id))

    def suggest_followups(self, answer: Answer) -> list[str]:
        """Is jawab ke context se (question, SQL, rows, pichhle sawal, chale hue datasets) 2-3 follow-up sawal suggest karta hai.
        Sirf answered/empty jawab ke liye. Kabhi exception nahi uthata: suggestion na bane toh khaali list, jawab pe koi asar nahi.
        Suggestion sirf text hai; click karne par woh normal pipeline (validator + Snowflake) se hi guzarta hai."""
        if answer.status not in {"answered", "empty"} or answer.steps:  # multipart jawab ke liye abhi suggestions nahi
            return []
        earlier = [q for q, _ in self.history]
        context = {
            "last_question": answer.question, "executed_sql": trace.short(answer.executed_sql or answer.sql, 600),
            "columns": answer.columns, "rows": [dict(zip(answer.columns, r)) for r in answer.rows[:SUGGEST_ROWS]],
            "row_count": len(answer.rows), "tables": answer.tables, "assumptions": answer.assumptions,
            "earlier_questions": earlier[-5:],
        }
        brief = "\n".join(f"- {d.name}: {d.description} (tables: {', '.join(d.tables)})" for d in self.cfg.datasets if d.tables)
        try:
            plan = llm.chat_json(SUGGEST_SYSTEM.format(datasets=brief), json.dumps(context, default=str))
        except Exception:
            log.warning("Could not get follow-up suggestions", exc_info=True)
            trace.emit("SUGGEST", "Gemma could not suggest follow-ups; the answer is unaffected")
            return []
        seen = {q.casefold() for q in earlier} | {answer.question.casefold()}
        out: list[str] = []
        items = plan.get("suggestions")
        for item in items if isinstance(items, list) else []:  # string ya None aaye toh character-by-character nahi chalna
            text = " ".join(item.split()) if isinstance(item, str) else ""
            if not MIN_SUGGESTION_CHARS <= len(text) <= MAX_SUGGESTION_CHARS or text.casefold() in seen or text.upper().startswith(("SELECT", "WITH ")):
                continue
            seen.add(text.casefold())
            out.append(text)
        out = out[:MAX_SUGGESTIONS]
        trace.emit("SUGGEST", f"{len(out)} follow-up question(s) suggested from the answer, its rows and {len(earlier)} earlier question(s)")
        return out

    def refresh_tables(self) -> None:
        """Live schema dobara padhta hai (nayi ya hataayi gayi tables) bina restart kiye; validator ki allowlist bhi saath me update ho jaati hai."""
        self._children.clear()
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
            if action == "split" and self._split_on():
                return self._split(question, plan)
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
