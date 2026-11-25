"""Local, zero-cost PII, BC Water Licence, PID, and internal KB ID scanner powered by Microsoft Presidio."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

ROOT = Path(__file__).resolve().parents[2]
GROUND_TRUTH_PATH = ROOT / "data" / "bc_water_licensing_ground_truth.yaml"

_ANALYZER: Any = None
_GROUND_TRUTH_CACHE: Optional[Dict[str, Any]] = None

ENTITY_RISK_MAP: Dict[str, tuple[str, str]] = {
    "BC_WATER_LICENCE_NUMBER": ("Privacy", "high"),
    "BC_PARCEL_PID": ("Privacy", "high"),
    "INTERNAL_KB_ID": ("Security", "medium"),
    "INTERNAL_SYSTEM_MARKER": ("Security", "high"),
    "SECRET_OR_API_KEY": ("Security", "high"),
    "CA_SIN": ("Privacy", "high"),
    "CREDIT_CARD": ("Privacy", "high"),
    "EMAIL_ADDRESS": ("Privacy", "medium"),
    "PHONE_NUMBER": ("Privacy", "medium"),
    "PERSON": ("Privacy", "low"),
    "IP_ADDRESS": ("Security", "medium"),
}


def load_ground_truth(path: Optional[Path] = None) -> Dict[str, Any]:
    global _GROUND_TRUTH_CACHE
    target = path or GROUND_TRUTH_PATH
    if path is None and _GROUND_TRUTH_CACHE is not None:
        return _GROUND_TRUTH_CACHE
    if not target.exists():
        return {}
    data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    if path is None:
        _GROUND_TRUTH_CACHE = data
    return data


def _whitelisted_values(gt: Dict[str, Any]) -> Set[str]:
    contacts = gt.get("public_whitelisted_contacts") or {}
    items: Set[str] = set()
    for email in contacts.get("emails") or []:
        items.add(str(email).strip().lower())
    for phone in contacts.get("phones") or []:
        items.add(re.sub(r"\D+", "", str(phone)))
    return items


def _build_analyzer() -> Any:
    global _ANALYZER
    if _ANALYZER is not None:
        return _ANALYZER

    from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
    from presidio_analyzer.nlp_engine import NlpEngineProvider

    provider = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        }
    )
    analyzer = AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=["en"])

    custom_recognizers = [
        PatternRecognizer(
            supported_entity="BC_WATER_LICENCE_NUMBER",
            patterns=[
                Pattern("bc_licence_cfz", r"\b(?:[CFZ]\d{6}|(?:CL|FL)\s?\d{5,7})\b", 0.85),
            ],
            context=["licence", "license", "water", "conditional", "final", "authorization"],
        ),
        PatternRecognizer(
            supported_entity="BC_PARCEL_PID",
            patterns=[
                Pattern("bc_pid_hyphen", r"\b\d{3}-\d{3}-\d{3}\b", 0.9),
                Pattern("bc_pid_labeled", r"(?i)\bpid\s*[:#-]?\s*\d{9}\b", 0.95),
            ],
            context=["pid", "parcel", "identifier", "land", "title"],
        ),
        PatternRecognizer(
            supported_entity="INTERNAL_KB_ID",
            patterns=[
                Pattern(
                    "kb_chunk_id",
                    r"\b(?:wsa|jwa|complete|elig|step\d+|faq|loa|priv|ref|rel)_\d{2,4}\b",
                    0.95,
                ),
            ],
        ),
        PatternRecognizer(
            supported_entity="INTERNAL_SYSTEM_MARKER",
            patterns=[
                Pattern(
                    "agent_or_rag_leak",
                    r"(?i)\b(?:FormSupportAgentA2A|ConversationAgentA2A|Azure AI Search|rag_system|suggestedvalue|BACKEND_META)\b",
                    0.95,
                ),
            ],
        ),
        PatternRecognizer(
            supported_entity="SECRET_OR_API_KEY",
            patterns=[
                Pattern(
                    "api_key_assignment",
                    r"(?i)\b(?:openai[_-]?api[_-]?key|audit[_-]?llm[_-]?api[_-]?key|accountkey|connection[_-]?string)\s*[:=]\s*\S{8,}",
                    0.98,
                ),
            ],
        ),
        PatternRecognizer(
            supported_entity="CA_SIN",
            patterns=[
                Pattern("ca_sin", r"(?i)\bsin\s*[:#-]?\s*\d{3}[-\s]?\d{3}[-\s]?\d{3}\b", 0.9),
            ],
        ),
    ]

    for rec in custom_recognizers:
        analyzer.registry.add_recognizer(rec)

    _ANALYZER = analyzer
    return analyzer


class PresidioScanner:
    """Zero-token-cost local scanner for PII, BC Water Licence IDs, PIDs, and internal KB markers."""

    ENTITIES = list(ENTITY_RISK_MAP.keys())
    FALSE_POSITIVE_PERSONS = {
        "frontcounter bc", "water sustainability act", "bc hydro", "bceid", "basic bceid",
        "business bceid", "personal bceid", "first nations", "first nation", "british columbia",
        "ministry of water", "crown land", "joint works", "service bc", "aifa",
    }

    def __init__(self, ground_truth: Optional[Dict[str, Any]] = None) -> None:
        self.gt = ground_truth if ground_truth is not None else load_ground_truth()
        self.whitelist = _whitelisted_values(self.gt)

    def scan(self, text: str, score_threshold: float = 0.6) -> Dict[str, Any]:
        if not text or not text.strip():
            return {"passed": True, "entity_count": 0, "high_severity_count": 0, "findings": []}

        analyzer = _build_analyzer()
        results = analyzer.analyze(
            text=text,
            language="en",
            entities=self.ENTITIES,
            score_threshold=score_threshold,
        )

        findings: List[Dict[str, Any]] = []
        seen: Set[tuple[str, str]] = set()

        for res in sorted(results, key=lambda r: (r.start, -r.score)):
            snippet = text[res.start : res.end].strip()
            norm = snippet.lower()
            digits = re.sub(r"\D+", "", snippet)

            if res.entity_type == "EMAIL_ADDRESS" and norm in self.whitelist:
                continue
            if res.entity_type == "PHONE_NUMBER" and digits and digits in self.whitelist:
                continue
            if res.entity_type == "PERSON":
                if norm in self.FALSE_POSITIVE_PERSONS or len(snippet) < 4 or res.score < 0.85:
                    continue

            dedup_key = (res.entity_type, norm)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            risk_class, severity = ENTITY_RISK_MAP.get(res.entity_type, ("Privacy", "medium"))
            findings.append({
                "entity_type": res.entity_type,
                "matched_text": snippet[:120],
                "score": round(float(res.score), 3),
                "risk_class": risk_class,
                "severity": severity,
                "start": res.start,
                "end": res.end,
            })

        high_count = sum(1 for f in findings if f["severity"] == "high")
        blocking = [f for f in findings if f["severity"] in {"high", "medium"}]
        return {
            "passed": len(blocking) == 0,
            "entity_count": len(findings),
            "high_severity_count": high_count,
            "findings": findings,
        }
