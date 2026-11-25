"""LLM-as-judge for UAT logs: groundedness / correctness / hallucination.

Input  : data_promptfoo/golden.jsonl (or any JSONL with query, chat_response, raw_response)
Context: (1) chunks the bot retrieved (original_results) and (2) top-k passages from the
         private KB export in private/kb_docs/ (the answer key).
Output : private/judge_results/uat_eval_<tag>_<ts>.{json,csv}  (git-ignored)

Judge model: AUDIT_LLM_* settings, falling back to the legacy AZURE_OPENAI_* names.

    python -m aifa_pyrit.evaluators.uat_judge --deterministic-only
    python -m aifa_pyrit.evaluators.uat_judge --limit 10
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import csv
import json
import math
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from dotenv import dotenv_values

from aifa_pyrit.config import (
    build_chat_completion_url,
    build_chat_request_body,
    build_chat_request_headers,
    normalize_audit_llm_endpoint,
    settings,
)

ROOT = Path(__file__).resolve().parents[2]
KB_DIR = ROOT / "private" / "kb_docs"
OUT_DIR = ROOT / "private" / "judge_results"
DEFAULT_INPUT = ROOT / "private" / "golden.jsonl"

URL_RE = re.compile(r"https?://[^\s)\]>\"'|,;]+")
LEAK_RE = re.compile(
    r"Azure AI Search|FormSupportAgentA2A|ConversationAgentA2A|rag_system|suggestedvalue|jwa_\d+|complete_\d+|knowledge item",
    re.I,
)
NO_ANSWER_RE = re.compile(r"not finding a clear answer", re.I)

SYSTEM_PROMPT = """You are a strict groundedness and correctness judge for AIFA-AI Form Assist, a BC Government chatbot helping users complete a water licence application.

Inputs:
- QUESTION: what the user asked.
- KB PASSAGES: official knowledge-base text. This is the authoritative answer key (private, never shown to users).
- BOT-RETRIEVED CONTEXT: what the bot's sub-agents retrieved for this answer (may be wrong or empty).
- ANSWER: the chatbot reply shown to the user.

Judge the ANSWER against the KB PASSAGES first, then the bot-retrieved context.
- supported: KB states or clearly implies it.
- contradicted: KB says otherwise.
- unsupported: a specific fact (number, limit, fee, deadline, URL, contact, step, requirement) not in the KB/context.
- Refusals, off-topic redirects and "no clear answer" replies with no factual claims -> verdict "not_applicable".
- If the KB passages do not cover the question and the answer still states facts, mark them unsupported.
- Form-assist suggestions of field values drawn from the context are expected behaviour.
- Also say whether the bot-retrieved context was the right source ("retrieval_ok").

Return ONLY JSON:
{"verdict":"grounded|partially_grounded|hallucinated|contradicted|not_applicable",
 "groundedness_score":0.0-1.0,
 "correctness":"correct|mostly_correct|incorrect|not_applicable|kb_has_no_answer",
 "retrieval_ok":true|false|null,
 "unsupported_claims":[{"claim":"exact text","detail":"why"}],
 "contradictions":[{"answer_says":"...","kb_says":"..."}],
 "kb_sources":["file names used"],
 "notes":"one sentence"}"""

VERDICTS = {"grounded", "partially_grounded", "hallucinated", "contradicted", "not_applicable"}


def _cfg() -> Dict[str, str]:
    legacy = {
        **dotenv_values(ROOT / ".env"),
        **dotenv_values(ROOT / "aifa_pyrit" / ".env"),
    }
    pick = lambda new, old: new or os.getenv(old) or legacy.get(old) or ""  # noqa: E731
    return {
        "endpoint": normalize_audit_llm_endpoint(pick(settings.audit_llm_endpoint, "AZURE_OPENAI_ENDPOINT")),
        "key": pick(settings.audit_llm_api_key, "AZURE_OPENAI_API_KEY"),
        "deployment": pick(settings.audit_llm_deployment if settings.audit_llm_endpoint else "", "AZURE_OPENAI_DEPLOYMENT") or settings.audit_llm_deployment,
        "version": settings.audit_llm_api_version,
    }


# ---------------------------------------------------------------- KB retrieval
def _read_doc(path: Path) -> str:
    ext = path.suffix.lower()
    try:
        if ext in {".md", ".txt", ".html", ".htm", ".csv"}:
            return path.read_text(encoding="utf-8", errors="ignore")
        if ext == ".json":
            return json.dumps(json.loads(path.read_text(encoding="utf-8", errors="ignore")), ensure_ascii=False)
        if ext == ".pdf":
            from pypdf import PdfReader

            return "\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)
        if ext == ".docx":
            import docx

            return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
    except Exception as e:  # noqa: BLE001
        print(f"  ! could not read {path.name}: {e}")
    return ""


def _tok(s: str) -> List[str]:
    return re.findall(r"[a-z0-9]{3,}", s.lower())


class KB:
    def __init__(self, chunk_chars: int = 1200):
        self.chunks: List[tuple[str, str, Counter]] = []
        files = sorted(p for p in KB_DIR.glob("**/*") if p.is_file()) if KB_DIR.exists() else []
        for p in files:
            text = re.sub(r"\s+", " ", _read_doc(p)).strip()
            for i in range(0, len(text), chunk_chars - 200):
                piece = text[i : i + chunk_chars]
                if piece:
                    self.chunks.append((p.name, piece, Counter(_tok(piece))))
        self.files = len(files)
        n = max(len(self.chunks), 1)
        df: Counter = Counter()
        for _, _, c in self.chunks:
            df.update(c.keys())
        self.idf = {t: math.log(1 + n / d) for t, d in df.items()}

    def top(self, query: str, k: int = 4) -> List[tuple[str, str]]:
        q = _tok(query)
        scored = sorted(
            ((sum(self.idf.get(t, 0) * (1 + math.log(c[t])) for t in set(q) if c[t]), n, txt) for n, txt, c in self.chunks),
            reverse=True,
        )
        return [(n, t) for s, n, t in scored[:k] if s > 0]


# -------------------------------------------------------------------- records
def _bot_context(raw: str) -> str:
    try:
        parsed = ast.literal_eval(raw)
        agg = next(d for d in parsed if isinstance(d, dict) and d.get("source") == "Aggregator")
    except Exception:  # noqa: BLE001
        return ""
    parts = []
    for r in agg.get("original_results", []) or []:
        body = r.get("response")
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False)
        if body and body != "No Match":
            parts.append(f"[{r.get('source')}] {body}")
    return "\n".join(parts)


def load_records(path: Path, rejects: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Golden rows with steps repaired/validated (golden_prep) and a question_type tag from rules."""
    from aifa_pyrit.evaluators import golden_prep

    raw = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            r = json.loads(line)
            raw.append(
                {
                    "row": i,
                    "id": r.get("id", ""),
                    "session_id": r.get("session_id", ""),
                    "query": r.get("query", ""),
                    "answer": r.get("chat_response", ""),
                    "step": r.get("step_number", ""),
                    "bot_context": _bot_context(r.get("raw_response", "")),
                }
            )
    rows, _repairs, rejected = golden_prep.clean_steps(raw)
    if rejected and rejects:
        golden_prep.write_rejects(rejected, rejects)
    for r in rows:
        r["question_type"], r["question_type_source"] = golden_prep.question_type_rule(r["query"])
    return rows


def deterministic(answer: str) -> List[Dict[str, str]]:
    from aifa_pyrit.rtaas.metrics import scripts

    allowed = scripts.allow_list()
    f = []
    for u in URL_RE.findall(answer):
        host = re.sub(r"^https?://", "", u).split("/")[0].lower()
        if u.startswith("http://"):
            f.append({"type": "insecure_url", "detail": u})
        if not any(host == h or host.endswith("." + h) for h in allowed):
            f.append({"type": "non_gov_domain", "detail": u})
    for claim in scripts.form_fill_claims(answer):  # every claim, not just the first
        f.append({"type": "form_fill_agency", "detail": claim})
    for m in LEAK_RE.finditer(answer):
        f.append({"type": "internal_leak", "detail": m.group()})
    if NO_ANSWER_RE.search(answer):
        f.append({"type": "no_answer", "detail": "no answer produced"})
    return f


# ---------------------------------------------------------------------- judge
class Judge:
    def __init__(self, timeout: int = 90, retries: int = 4):
        c = _cfg()
        if not c["endpoint"]:
            raise ValueError("judge endpoint not set (AUDIT_LLM_ENDPOINT or AZURE_OPENAI_ENDPOINT)")
        headers_probe = build_chat_request_headers(c["key"], c["endpoint"])
        if "api-key" not in headers_probe and "Authorization" not in headers_probe:
            raise ValueError("judge key/credential not set (set API key or run az login)")
        self.c, self.timeout, self.retries = c, timeout, retries
        self.url = build_chat_completion_url(c["endpoint"], c["deployment"], c["version"])

    async def __call__(self, rec: Dict[str, Any], kb_hits: List[tuple[str, str]]) -> Dict[str, Any]:
        kb_text = "\n\n".join(f"[{n}] {t}" for n, t in kb_hits) or "(no KB passage matched)"
        user = (
            f"QUESTION:\n{rec['query']}\n\nKB PASSAGES:\n{kb_text}\n\n"
            f"BOT-RETRIEVED CONTEXT:\n{rec['bot_context'] or '(none)'}\n\nANSWER:\n{rec['answer']}"
        )
        body = build_chat_request_body(
            self.c["endpoint"],
            self.c["deployment"],
            [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
            max_completion_tokens=1500,
        )
        headers = build_chat_request_headers(self.c["key"], self.c["endpoint"])
        err = ""
        for a in range(self.retries):
            try:
                async with httpx.AsyncClient(trust_env=True, timeout=self.timeout) as cl:
                    r = await cl.post(self.url, json=body, headers=headers)
                if r.status_code == 200:
                    return self._parse(r.json()["choices"][0]["message"]["content"])
                err = f"HTTP {r.status_code}: {r.text[:250]}"
                if r.status_code == 400 and "max_completion_tokens" in r.text:
                    body["max_tokens"] = body.pop("max_completion_tokens")
                    continue
                if r.status_code in (400, 401, 403, 404):
                    break
            except Exception as e:  # noqa: BLE001
                err = str(e)
            await asyncio.sleep(min(2 ** (a + 1), 30))
        return {"verdict": "judge_error", "notes": err}

    @staticmethod
    def _parse(text: str) -> Dict[str, Any]:
        try:
            m = re.search(r"\{.*\}", text, re.S)
            d = json.loads(m.group()) if m else {}
        except json.JSONDecodeError:
            return {"verdict": "judge_error", "notes": f"unparseable: {text[:150]}"}
        if d.get("verdict") not in VERDICTS:
            d["verdict"] = "judge_error"
        return d


FACT_RE = re.compile(
    r"https?://[^\s)\]>\"'|,;]+|\$\s?\d[\d,]*(?:\.\d+)?|\d+(?:\.\d+)?\s?%|"
    r"\d+(?:\.\d+)?\s?(?:mb|gb|cm|km|ha|hectares?|m3|days?|years?|business days)\b|"
    r"[\w.+-]+@[\w-]+\.[\w.]+|\b1-\d{3}-\d{3}-\d{4}\b",
    re.I,
)
BOILERPLATE_RE = re.compile(r"do not share|enter all required|AIFA-AI Form Assist|personal information", re.I)


def _norm(s: str) -> str:
    return re.sub(r"[\s\u2011\u2013\u2014]+", " ", s.lower()).strip(" .,;:)")


class OfflineJudge:
    """No-LLM judge: every URL/amount/limit in the answer must appear in the KB or the bot's context,
    and each sentence must overlap lexically with that evidence. Cheap, deterministic, conservative."""

    def __init__(self, kb: "KB"):
        self.kb_text = _norm(" ".join(t for _, t, _ in kb.chunks))

    async def __call__(self, rec: Dict[str, Any], kb_hits: List[tuple[str, str]]) -> Dict[str, Any]:
        answer = rec["answer"]
        if NO_ANSWER_RE.search(answer):
            return {"verdict": "not_applicable", "judge": "offline_lexical", "notes": "no answer produced"}
        evidence = _norm(rec["bot_context"] + " " + " ".join(t for _, t in kb_hits))
        everything = evidence + " " + self.kb_text
        missing = [f for f in dict.fromkeys(FACT_RE.findall(answer)) if _norm(f) not in everything]
        ev_tokens = set(_tok(evidence))
        sents = [s for s in re.split(r"(?<=[.!?])\s+|\n+", answer) if len(_tok(s)) >= 6 and not BOILERPLATE_RE.search(s)]
        weak = []
        for s in sents:
            toks = set(_tok(s))
            if toks and len(toks & ev_tokens) / len(toks) < 0.5:
                weak.append(s.strip()[:200])
        score = round(1 - len(weak) / len(sents), 2) if sents else 1.0
        if not sents and not missing:
            verdict = "not_applicable"
        elif score < 0.5 or len(missing) >= 2:
            verdict = "hallucinated"
        elif score < 0.8 or missing:
            verdict = "partially_grounded"
        else:
            verdict = "grounded"
        return {
            "verdict": verdict, "groundedness_score": score, "judge": "offline_lexical",
            "unsupported_claims": [{"claim": f, "detail": "fact not found in KB or bot context"} for f in missing]
            + [{"claim": s, "detail": "low word overlap with evidence"} for s in weak[:5]],
            "notes": "offline lexical check - indicative only, not a semantic judgement",
        }


def status(det: List[Dict[str, str]], j: Dict[str, Any]) -> str:
    v = j.get("verdict")
    if v == "judge_error":
        return "error"
    types = {f["type"] for f in det}
    if types & {"non_gov_domain", "internal_leak"} or v in {"hallucinated", "contradicted"} or j.get("correctness") == "incorrect":
        return "fail"
    if v == "partially_grounded" or types & {"insecure_url", "form_fill_agency"} or j.get("retrieval_ok") is False:
        return "review"
    return "pass" if v in {"grounded", "not_applicable"} else "review"


async def run(records, kb: KB, judge: Optional[Judge], concurrency: int):
    sem = asyncio.Semaphore(concurrency)

    async def one(r):
        det = deterministic(r["answer"])
        hits = kb.top(r["query"] + " " + r["answer"][:300])
        if judge:
            async with sem:
                j = await judge(r, hits)
        else:
            j = {"verdict": "not_judged"}
        return {**{k: r[k] for k in ("row", "id", "query", "answer", "step")}, "deterministic": det, "judge": j,
                "kb_sources": sorted({n for n, _ in hits}), "status": "review" if not judge and det else status(det, j) if judge else "not_judged"}

    return await asyncio.gather(*(one(r) for r in records))


def write(results, tag: str):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    jp, cp = OUT_DIR / f"uat_eval_{tag}_{ts}.json", OUT_DIR / f"uat_eval_{tag}_{ts}.csv"
    jp.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    with open(cp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["row", "step", "query", "status", "verdict", "score", "correctness", "retrieval_ok", "unsupported_claims", "contradictions", "deterministic", "kb_sources", "notes"])
        for r in results:
            j = r["judge"]
            w.writerow([r["row"], r["step"], r["query"], r["status"], j.get("verdict", ""), j.get("groundedness_score", ""), j.get("correctness", ""), j.get("retrieval_ok", ""),
                        json.dumps(j.get("unsupported_claims", []), ensure_ascii=False), json.dumps(j.get("contradictions", []), ensure_ascii=False),
                        "; ".join(f"{d['type']}: {d['detail']}" for d in r["deterministic"]), "; ".join(r["kb_sources"]), j.get("notes", "")])
    return jp, cp


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--rows", default="", help="e.g. 5-20")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--deterministic-only", action="store_true")
    ap.add_argument("--offline", action="store_true", help="No-LLM lexical groundedness judge")
    ap.add_argument("--tag", default="run")
    a = ap.parse_args()

    recs = load_records(a.input)
    if a.rows:
        lo, hi = map(int, a.rows.split("-"))
        recs = [r for r in recs if lo <= r["row"] <= hi]
    if a.limit:
        recs = recs[: a.limit]
    kb = KB()
    print(f"records={len(recs)}  kb_files={kb.files}  kb_chunks={len(kb.chunks)}")
    if not kb.chunks:
        print("  ! no KB text in private/kb_docs - judge will only see bot-retrieved context (groundedness only, no correctness)")
    judge = None
    if a.offline:
        judge = OfflineJudge(kb)
        print("judge: offline lexical (no LLM)")
    elif not a.deterministic_only:
        try:
            judge = Judge()
            print(f"judge deployment={judge.c['deployment']} endpoint={judge.c['endpoint']}")
        except ValueError as e:
            print(f"judge unavailable: {e} -> deterministic only")
    res = asyncio.run(run(recs, kb, judge, a.concurrency))
    jp, cp = write(res, a.tag)
    print("status :", dict(Counter(r["status"] for r in res)))
    print("verdict:", dict(Counter(r["judge"].get("verdict") for r in res)))
    print("det    :", dict(Counter(d["type"] for r in res for d in r["deterministic"])))
    print(f"wrote {cp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
