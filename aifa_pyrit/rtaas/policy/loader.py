"""Loads the policy YAML files once and gives simple lookups."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

HERE = Path(__file__).parent
FRAMEWORKS = ("owasp", "eu_ai_act", "nist")


def _load(name: str) -> dict:
    return yaml.safe_load((HERE / name).read_text(encoding="utf-8"))


@lru_cache
def catalog() -> dict:
    return _load("catalog.yaml")


@lru_cache
def crosswalk() -> dict:
    return _load("crosswalk.yaml")


@lru_cache
def tiers() -> dict:
    return _load("tiers.yaml")


def versions() -> dict[str, str]:
    """Which rulebook a run was graded against (recorded on every graded run)."""
    return {"catalog": str(catalog()["version"]), "crosswalk": str(crosswalk()["version"]), "tiers": str(tiers()["version"])}


def failure_modes() -> dict[str, dict]:
    return {f["id"]: f for f in catalog()["failure_modes"]}


def failure_mode(fm_id: str) -> dict:
    return failure_modes()[fm_id]


def principles() -> dict[str, dict]:
    return {p["code"]: p for p in catalog()["principles"]}


def tier(key: str) -> dict:
    for t in tiers()["tiers"]:
        if t["key"] == key:
            return t
    raise KeyError(key)


def _codes(fw: str, code: str) -> list[str]:
    """Crosswalk code -> the tags it covers, e.g. '600-1 §2.3, §2.11' -> ['600-1 §2.3', '600-1 §2.11']."""
    if fw == "nist" and code.startswith("600-1 ") and "," in code:
        return ["600-1 " + part.strip().removeprefix("600-1 ") for part in code.split(",")]
    return [code]


def _normalise(fw: str, tag: str) -> str:
    tag = tag.strip()
    if fw == "nist":
        tag = re.sub(r"^MEASURE\s+", "MS ", tag)
    return tag


def crosswalk_index() -> dict[str, dict[str, set[str]]]:
    """{framework: {tag: {failure modes}}} from crosswalk.yaml."""
    index: dict[str, dict[str, set[str]]] = {}
    for fw in FRAMEWORKS:
        index[fw] = {}
        for item in crosswalk()[fw]["items"]:
            for code in _codes(fw, item["code"]):
                index[fw].setdefault(code, set()).update(item["failure_modes"])
    return index


def _crosswalk_entry(index: dict[str, set[str]], fw: str, tag: str) -> set[str] | None:
    tag = _normalise(fw, tag)
    if tag in index:
        return index[tag]
    # 'Art. 14(4)(b)' is evidence toward the 'Art. 14' entry
    for code, fms in index.items():
        if tag.startswith(code + "("):
            return fms
    return None


def validate() -> list[str]:
    """Cheap consistency checks. Run in CI so the YAML can't drift."""
    errors = []
    fms = failure_modes()
    principle_codes = set(principles())
    for f in fms.values():
        if f["principle"] not in principle_codes:
            errors.append(f"{f['id']}: unknown principle {f['principle']}")
        for k in ("pass", "low", "medium", "high"):
            if not f["severity_ladder"].get(k):
                errors.append(f"{f['id']}: severity ladder missing '{k}'")
        for k in ("low", "medium", "high"):
            if not f["mitigation"].get(k):
                errors.append(f"{f['id']}: mitigation missing for tier '{k}'")
    for fw in FRAMEWORKS:
        for item in crosswalk()[fw]["items"]:
            for fm_id in item["failure_modes"]:
                if fm_id not in fms:
                    errors.append(f"crosswalk {fw} {item['code']}: unknown failure mode {fm_id}")
    index = crosswalk_index()
    for f in fms.values():
        for fw in FRAMEWORKS:
            for tag in f["evidence"].get(fw, []):
                entry = _crosswalk_entry(index[fw], fw, tag)
                if entry is None:
                    errors.append(f"{f['id']}: evidence tag {fw} '{tag}' is not in crosswalk.yaml")
                elif f["id"] not in entry:
                    errors.append(f"{f['id']}: crosswalk {fw} '{tag}' does not list {f['id']}")
    if len(fms) != tiers()["failure_mode_bar"]["total_failure_modes"]:
        errors.append(f"tiers.yaml total_failure_modes={tiers()['failure_mode_bar']['total_failure_modes']} but catalog has {len(fms)}")
    return errors
