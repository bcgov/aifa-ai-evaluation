"""Promptfoo container API.

Serves the target adapter (`/health`, `/invoke`) plus `/api/promptfoo/*`, which runs an
allowlisted set of promptfoo CLI commands as background jobs. Commands are executed with
argument lists (never a shell) and every user value is validated before it reaches argv.
"""

from __future__ import annotations

import asyncio
import csv
import hmac
import io
import json
import logging
import os
import re
import shlex
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse, Response
import yaml
from pydantic import BaseModel, Field

try:
    from promptfoo.src.config import settings
    from promptfoo.src.promptfoo_adapter import app
    from promptfoo.src.storage import PromptfooStorage, safe_join
except ModuleNotFoundError:  # pragma: no cover - fallback for local subproject execution
    from src.config import settings
    from src.promptfoo_adapter import app
    from src.storage import PromptfooStorage, safe_join

PROMPTFOO_DIR = Path(__file__).resolve().parents[1]
logger = logging.getLogger("uvicorn.error")
REPO_ROOT = PROMPTFOO_DIR.parent
# Fixed location: promptfoo-config.yaml references file://../data_promptfoo/...
DATA_DIR = REPO_ROOT / "data_promptfoo"
RESULTS_DIR = Path(os.getenv("PROMPTFOO_RESULTS_DIR", str(REPO_ROOT / "results-promptfoo")))
CONFIG_WORKSPACE = RESULTS_DIR / "configs"
META_DIR = RESULTS_DIR / ".meta"
STORAGE = PromptfooStorage(DATA_DIR, RESULTS_DIR)
BUNDLED_CONFIGS = ("promptfoo-config.yaml",)
TARGET_LABEL = "aifa-water-licence"
TARGET_URL = os.getenv("PROMPTFOO_TARGET_URL", f"http://127.0.0.1:{os.getenv('PORT', '8001')}/invoke")
RUN_TOKEN = os.getenv("PROMPTFOO_RUN_TOKEN", "")
JOB_TIMEOUT = int(os.getenv("PROMPTFOO_JOB_TIMEOUT", "3600"))
MAX_PARALLEL_JOBS = max(1, int(os.getenv("PROMPTFOO_MAX_PARALLEL_JOBS", "1")))
MAX_LOG_LINES = 5000
MAX_JOBS_KEPT = 50
MAX_ROWS = 2000
# promptfoo exits 100 when the run completed but at least one test failed.
OK_EXIT_CODES = {0, 100}

SAFE_NAME = re.compile(r"^[A-Za-z0-9][\w.-]{0,150}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9][\w:.-]{0,120}$")
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


# ---------------------------------------------------------------- catalog

PLUGINS: list[dict[str, str]] = [
    {"id": "default", "group": "Collections", "label": "Promptfoo default set"},
    {"id": "owasp:llm", "group": "Collections", "label": "OWASP LLM Top 10"},
    {"id": "nist:ai:measure", "group": "Collections", "label": "NIST AI RMF (measure)"},
    {"id": "mitre:atlas", "group": "Collections", "label": "MITRE ATLAS"},
    {"id": "harmful", "group": "Collections", "label": "All harmful-content plugins"},
    {"id": "prompt-extraction", "group": "Security", "label": "System prompt extraction"},
    {"id": "system-prompt-override", "group": "Security", "label": "System prompt override"},
    {"id": "hijacking", "group": "Security", "label": "Goal hijacking"},
    {"id": "excessive-agency", "group": "Security", "label": "Excessive agency"},
    {"id": "ascii-smuggling", "group": "Security", "label": "ASCII smuggling"},
    {"id": "cross-session-leak", "group": "Security", "label": "Cross-session leak"},
    {"id": "debug-access", "group": "Security", "label": "Debug interface access"},
    {"id": "rbac", "group": "Security", "label": "Role-based access control"},
    {"id": "bola", "group": "Security", "label": "Object-level authorization (BOLA)"},
    {"id": "bfla", "group": "Security", "label": "Function-level authorization (BFLA)"},
    {"id": "sql-injection", "group": "Security", "label": "SQL injection"},
    {"id": "shell-injection", "group": "Security", "label": "Shell injection"},
    {"id": "ssrf", "group": "Security", "label": "Server-side request forgery"},
    {"id": "pii:direct", "group": "Privacy", "label": "PII — direct disclosure"},
    {"id": "pii:session", "group": "Privacy", "label": "PII — session leakage"},
    {"id": "pii:social", "group": "Privacy", "label": "PII — social engineering"},
    {"id": "pii:api-db", "group": "Privacy", "label": "PII — API/database access"},
    {"id": "harmful:privacy", "group": "Privacy", "label": "Privacy violations"},
    {"id": "hallucination", "group": "Trust & accuracy", "label": "Hallucination"},
    {"id": "overreliance", "group": "Trust & accuracy", "label": "Overreliance on false premises"},
    {"id": "contracts", "group": "Trust & accuracy", "label": "Unauthorized commitments"},
    {"id": "imitation", "group": "Trust & accuracy", "label": "Impersonation"},
    {"id": "politics", "group": "Trust & accuracy", "label": "Political opinions"},
    {"id": "religion", "group": "Trust & accuracy", "label": "Religious opinions"},
    {"id": "competitors", "group": "Trust & accuracy", "label": "Competitor endorsements"},
    {"id": "off-topic", "group": "Trust & accuracy", "label": "Off-topic manipulation"},
    {"id": "divergent-repetition", "group": "Trust & accuracy", "label": "Divergent repetition"},
    {"id": "harmful:misinformation-disinformation", "group": "Harmful content", "label": "Misinformation"},
    {"id": "harmful:specialized-advice", "group": "Harmful content", "label": "Specialized (legal/financial) advice"},
    {"id": "harmful:hate", "group": "Harmful content", "label": "Hate speech"},
    {"id": "harmful:harassment-bullying", "group": "Harmful content", "label": "Harassment"},
    {"id": "harmful:insults", "group": "Harmful content", "label": "Insults"},
    {"id": "harmful:profanity", "group": "Harmful content", "label": "Profanity"},
    {"id": "harmful:self-harm", "group": "Harmful content", "label": "Self-harm"},
    {"id": "harmful:violent-crime", "group": "Harmful content", "label": "Violent crime"},
    {"id": "harmful:non-violent-crime", "group": "Harmful content", "label": "Non-violent crime"},
]

STRATEGIES: list[dict[str, str]] = [
    {"id": "basic", "group": "Single turn", "label": "Basic (plugin probes as written)"},
    {"id": "prompt-injection", "group": "Single turn", "label": "Prompt injection"},
    {"id": "jailbreak", "group": "Single turn", "label": "Iterative jailbreak", "note": "LLM"},
    {"id": "jailbreak:tree", "group": "Single turn", "label": "Tree-of-attacks jailbreak", "note": "LLM"},
    {"id": "jailbreak:composite", "group": "Single turn", "label": "Composite jailbreak", "note": "remote"},
    {"id": "best-of-n", "group": "Single turn", "label": "Best-of-N", "note": "remote"},
    {"id": "citation", "group": "Single turn", "label": "Authority citation", "note": "remote"},
    {"id": "math-prompt", "group": "Single turn", "label": "Math encoding", "note": "remote"},
    {"id": "crescendo", "group": "Multi turn", "label": "Crescendo", "note": "LLM"},
    {"id": "goat", "group": "Multi turn", "label": "GOAT", "note": "remote"},
    {"id": "base64", "group": "Encoding", "label": "Base64"},
    {"id": "rot13", "group": "Encoding", "label": "ROT13"},
    {"id": "leetspeak", "group": "Encoding", "label": "Leetspeak"},
    {"id": "hex", "group": "Encoding", "label": "Hex"},
    {"id": "homoglyph", "group": "Encoding", "label": "Homoglyph"},
]
PLUGIN_IDS = tuple(p["id"] for p in PLUGINS)
STRATEGY_IDS = tuple(s["id"] for s in STRATEGIES)


# ---------------------------------------------------------------- helpers

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _slug(value: str, fallback: str = "run") -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()[:40]
    return slug or fallback


def _ensure_dirs() -> None:
    for path in (RESULTS_DIR, CONFIG_WORKSPACE, META_DIR):
        path.mkdir(parents=True, exist_ok=True)


def _file_in(directory: Path, name: str, suffixes: tuple[str, ...]) -> Path | None:
    path = safe_join(directory, name)
    return path if path.suffix in suffixes and path.is_file() else None


def resolve_config(name: str) -> Path:
    path = (
        _file_in(PROMPTFOO_DIR, name, (".yaml", ".yml")) if name in BUNDLED_CONFIGS
        else _file_in(CONFIG_WORKSPACE, name, (".yaml", ".yml"))
    )
    if path is None:
        raise HTTPException(status_code=400, detail=f"Unknown config: {name}")
    return path


def load_dataset_cases(name: str) -> list[dict[str, Any]]:
    """Test cases of a promptfoo-format file in data_promptfoo/, kept exactly as written (assertions included)."""
    path = _file_in(DATA_DIR, name, (".yaml", ".yml", ".json"))
    if path is None:
        raise HTTPException(status_code=404, detail=f"Unknown test file: {name}")
    if path.stat().st_size > 1_000_000:
        raise HTTPException(status_code=400, detail="Test file is larger than 1 MB.")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"Could not read {name}: {exc}") from exc
    items = loaded.get("tests") if isinstance(loaded, dict) else loaded
    cases = [c for c in (items if isinstance(items, list) else []) if isinstance(c, dict) and isinstance(c.get("vars"), dict)]
    if not cases:
        raise HTTPException(status_code=400, detail=f"{name} has no promptfoo test cases (expected a list with 'vars').")
    return cases


def case_label(case: dict[str, Any]) -> str:
    variables = case["vars"]
    label = case.get("description") or variables.get("query") or variables.get("prompt") or "(untitled test)"
    return str(label).strip()[:300]


def write_dataset_config(dataset: str, indices: list[int]) -> Path:
    """Bundled eval config with only the chosen cases of `dataset` inlined as its tests."""
    cases = load_dataset_cases(dataset)
    chosen = sorted(set(indices))
    bad = [i for i in chosen if not 0 <= i < len(cases)]
    if bad:
        raise HTTPException(status_code=400, detail=f"Unknown test case: {', '.join(map(str, bad))}")
    config = yaml.safe_load((PROMPTFOO_DIR / BUNDLED_CONFIGS[0]).read_text(encoding="utf-8"))
    config["tests"] = [cases[i] for i in chosen]
    path = safe_join(CONFIG_WORKSPACE, f"subset_{_slug(Path(dataset).stem)}_{_stamp()}.yaml")
    # JSON is valid YAML, so the config is written without a YAML dump.
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def resolve_result(name: str) -> Path:
    path = _file_in(RESULTS_DIR, name, (".json",))
    if path is None:
        raise HTTPException(status_code=404, detail=f"Unknown result: {name}")
    return path


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def promptfoo_cmd() -> list[str]:
    custom = os.getenv("PROMPTFOO_BIN")
    if custom:
        return shlex.split(custom)
    found = shutil.which("promptfoo")
    return [found] if found else ["npx", "--yes", "promptfoo@latest"]


def _azure_base_url(endpoint: str) -> str:
    """Full base URL incl. any gateway path prefix (e.g. https://host/tenant-name)."""
    value = (endpoint or "").strip().rstrip("/")
    if value and not re.match(r"^https?://", value):
        value = "https://" + value
    return value


def _azure_provider(endpoint: str, deployment: str, api_version: str, key_env: str) -> dict[str, Any] | None:
    base = _azure_base_url(endpoint)
    if not base or not deployment:
        return None
    # Keys stay in env (apiKeyEnvar) so generated configs never contain secrets.
    return {"id": f"azure:chat:{deployment}", "config": {"apiBaseUrl": base, "apiVersion": api_version, "apiKeyEnvar": key_env}}


def grader_provider() -> dict[str, Any] | None:
    if not settings.AUDIT_LLM_api_key:
        return None
    return _azure_provider(settings.AUDIT_LLM_endpoint, settings.AUDIT_LLM_deployment,
                           settings.AUDIT_LLM_api_version, "AUDIT_LLM_API_KEY")


def judge_provider() -> dict[str, Any] | None:
    """Model that grades llm-rubric assertions."""
    return grader_provider()


def promptfoo_env() -> dict[str, str]:
    # Node's fetch cannot use SOCKS proxies, and the target adapter is on localhost.
    env = {k: v for k, v in os.environ.items() if k.lower() not in {"all_proxy", "https_proxy", "http_proxy"}}
    # promptfoo auto-loads ./.env, which would re-add the SOCKS proxy; settings already come from our config.
    env["DOTENV_PATH"] = os.devnull
    env.pop("DOTENV_CONFIG_PATH", None)
    if settings.AUDIT_LLM_api_key:
        # Otherwise promptfoo's default grader prefers api.openai.com over Azure.
        env.pop("OPENAI_API_KEY", None)
        env.pop("OPENAI_BASE_URL", None)
    values = {
        "AUDIT_LLM_API_KEY": settings.AUDIT_LLM_api_key,
        "AZURE_API_KEY": settings.AUDIT_LLM_api_key,
        "AZURE_API_BASE_URL": _azure_base_url(settings.AUDIT_LLM_endpoint),
        "AUDIT_LLM_DEPLOYMENT_NAME": settings.AUDIT_LLM_deployment,
        "AZURE_DEPLOYMENT_NAME": settings.AUDIT_LLM_deployment,
        "ADVERSARIAL_OPENAI_API_KEY": settings.adversarial_api_key,
        "PROMPTFOO_TARGET_URL": TARGET_URL,
        "PROMPTFOO_DISABLE_TELEMETRY": "1",
        "PROMPTFOO_DISABLE_UPDATE": "1",
        "FORCE_COLOR": "0",
        "CI": "true",
    }
    for key, value in values.items():
        if value and not env.get(key):
            env[key] = value
    return env


# ---------------------------------------------------------------- command specs

@dataclass(frozen=True)
class Opt:
    name: str
    label: str
    kind: Literal["config", "result", "text", "id", "int", "bool", "choice", "multi"]
    flag: str | None = None  # None => positional argument
    required: bool = False
    help: str = ""
    choices: tuple[str, ...] = ()
    min: int = 0
    max: int = 10_000
    default: Any = None

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name, "label": self.label, "kind": self.kind, "flag": self.flag,
            "required": self.required, "help": self.help, "choices": list(self.choices),
            "min": self.min, "max": self.max, "default": self.default,
        }

    def value(self, raw: Any) -> str | None:
        """Validate one user value; returns the argv string or None when unset."""
        if raw is None or raw == "" or raw == []:
            if self.required:
                raise HTTPException(status_code=400, detail=f"{self.label} is required.")
            return None
        if self.kind == "bool":
            return "1" if raw is True else None
        if self.kind == "int":
            try:
                number = int(raw)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"{self.label} must be a number.") from None
            if not self.min <= number <= self.max:
                raise HTTPException(status_code=400, detail=f"{self.label} must be between {self.min} and {self.max}.")
            return str(number)
        if self.kind == "config":
            return str(resolve_config(str(raw)))
        if self.kind == "result":
            return str(resolve_result(str(raw)))
        if self.kind == "choice":
            if raw not in self.choices:
                raise HTTPException(status_code=400, detail=f"Invalid {self.label}.")
            return str(raw)
        if self.kind == "multi":
            items = raw if isinstance(raw, list) else str(raw).split(",")
            items = [str(i).strip() for i in items if str(i).strip()]
            bad = [i for i in items if i not in self.choices]
            if bad:
                raise HTTPException(status_code=400, detail=f"Invalid {self.label}: {', '.join(bad)}")
            return ",".join(dict.fromkeys(items)) or None
        text = str(raw).strip()
        if self.kind == "id":
            if not SAFE_ID.match(text):
                raise HTTPException(status_code=400, detail=f"Invalid {self.label}.")
            return text
        if len(text) > 2000 or CONTROL.search(text):
            raise HTTPException(status_code=400, detail=f"{self.label} must be one line under 2000 characters.")
        return text

    def argv(self, raw: Any) -> list[str]:
        value = self.value(raw)
        if value is None:
            return []
        if self.flag is None:
            return [value]
        if self.kind == "bool":
            return [self.flag]
        # `--flag=value` keeps user values from ever being parsed as options.
        return [f"{self.flag}={value}"] if self.flag.startswith("--") else [self.flag, value]


@dataclass(frozen=True)
class Command:
    id: str
    label: str
    group: str
    summary: str
    argv: tuple[str, ...]
    options: tuple[Opt, ...] = ()
    output: Literal["json", "yaml"] | None = None

    def schema(self) -> dict[str, Any]:
        return {
            "id": self.id, "label": self.label, "group": self.group, "summary": self.summary,
            "cli": "promptfoo " + " ".join(self.argv), "output": self.output,
            "options": [o.schema() for o in self.options],
        }


CONFIG = Opt("config", "Config", "config", "--config", required=True)
CONCURRENCY = Opt("max_concurrency", "Max concurrency", "int", "--max-concurrency", min=1, max=20, help="Parallel calls to the target.")
DELAY = Opt("delay", "Delay (ms)", "int", "--delay", min=0, max=60_000, help="Pause between calls.")
NO_CACHE = Opt("no_cache", "Disable cache", "bool", "--no-cache")
EVAL_ID = Opt("eval_id", "Eval ID", "id", required=True, help="An eval ID from 'List' or 'latest'.")

COMMANDS: dict[str, Command] = {c.id: c for c in [
    Command("eval", "Run eval", "Evaluate", "Run every test in a config against the target and grade the answers.",
            ("eval", "--no-table", "--no-progress-bar", "--no-share"),
            (CONFIG,
             Opt("description", "Description", "text", "--description"),
             Opt("filter_pattern", "Filter: description regex", "text", "--filter-pattern"),
             Opt("filter_first_n", "Filter: first N tests", "int", "--filter-first-n", min=1),
             Opt("filter_failing", "Re-run failures from result", "result", "--filter-failing"),
             Opt("repeat", "Repeat each test", "int", "--repeat", min=1, max=20),
             CONCURRENCY, DELAY, NO_CACHE),
            output="json"),
    Command("redteam-run", "Red-team run (generate + eval)", "Red team",
            "Generate attack probes from a red-team config, then run them against the target.",
            ("redteam", "run"),
            (CONFIG,
             Opt("num_tests", "Probes per plugin", "int", "--num-tests", min=1, max=50),
             CONCURRENCY, DELAY,
             Opt("force", "Force regeneration", "bool", "--force", default=True)),
            output="json"),
    Command("redteam-generate", "Generate attack probes", "Red team",
            "Create adversarial test cases (written as a new config you can eval later).",
            ("redteam", "generate", "--no-progress-bar"),
            (CONFIG,
             Opt("purpose", "Purpose override", "text", "--purpose"),
             Opt("plugins", "Plugins", "multi", "--plugins", choices=PLUGIN_IDS),
             Opt("strategies", "Strategies", "multi", "--strategies", choices=STRATEGY_IDS),
             Opt("num_tests", "Probes per plugin", "int", "--num-tests", min=1, max=50),
             CONCURRENCY, DELAY,
             Opt("force", "Force regeneration", "bool", "--force")),
            output="yaml"),
    Command("redteam-eval", "Red-team eval", "Red team", "Run a previously generated red-team config.",
            ("redteam", "eval", "--no-table", "--no-progress-bar", "--no-share"),
            (CONFIG, CONCURRENCY, DELAY, NO_CACHE), output="json"),
    Command("validate", "Validate config", "Utilities", "Check a config's schema, or test connectivity to its target.",
            ("validate",),
            (Opt("what", "Validate", "choice", required=True, choices=("config", "target"), default="config"), CONFIG)),
    Command("retry", "Retry errors", "Utilities", "Re-run ERROR results (timeouts, rate limits) of a stored eval.",
            ("retry", "--no-share"), (EVAL_ID, CONCURRENCY, DELAY)),
    Command("cache-clear", "Clear cache", "Utilities", "Force fresh target calls on the next run.", ("cache", "clear")),
]}


def build_steps(command: Command, options: dict[str, Any]) -> tuple[list[list[str]], Path | None, str | None, str | None]:
    """Returns (argv steps, output path, config name, config name that the eval step actually ran)."""
    unknown = set(options) - {o.name for o in command.options}
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown options: {', '.join(sorted(unknown))}")

    config_name = options.get("config") or None
    config_path = resolve_config(str(config_name)) if config_name else None
    stem = _slug(config_path.stem) if config_path else command.id
    output: Path | None = None
    if command.output == "json":
        output = safe_join(RESULTS_DIR, f"{command.id}_{stem}_{_stamp()}.json")
    elif command.output == "yaml":
        output = safe_join(CONFIG_WORKSPACE, f"{command.id.replace('redteam-', 'probes-')}_{stem}_{_stamp()}.yaml")

    base = promptfoo_cmd()
    if command.id == "redteam-run":
        # Two explicit steps so the eval always lands in a JSON result file.
        probes = safe_join(CONFIG_WORKSPACE, f"probes_{stem}_{_stamp()}.yaml")
        by_name = {o.name: o for o in command.options}
        shared = by_name["max_concurrency"].argv(options.get("max_concurrency")) + by_name["delay"].argv(options.get("delay"))
        generate = [*base, "redteam", "generate", "--no-progress-bar", "--verbose", *by_name["config"].argv(config_name),
                    f"--output={probes}", *by_name["num_tests"].argv(options.get("num_tests")),
                    *by_name["force"].argv(options.get("force", True)), *shared]
        evaluate = [*base, "eval", "--no-table", "--no-progress-bar", "--no-share",
                    f"--config={probes}", f"--output={output}", *shared]
        return [generate, evaluate], output, config_name, probes.name

    positionals = [arg for o in command.options if o.flag is None for arg in o.argv(options.get(o.name, o.default))]
    flags = [arg for o in command.options if o.flag is not None for arg in o.argv(options.get(o.name))]
    argv = [*base, *command.argv, *positionals, *flags]
    if output is not None:
        argv.append(f"--output={output}")
    return [argv], output, config_name, config_name if command.id in {"eval", "redteam-eval"} else None


# ---------------------------------------------------------------- jobs

@dataclass
class Job:
    id: str
    command: str
    label: str
    steps: list[list[str]]
    config: str | None
    output: Path | None
    eval_config: str | None = None
    status: str = "queued"
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    step: int = 0
    lines: list[str] = field(default_factory=list)
    dropped: int = 0
    cancelled: bool = False
    proc: asyncio.subprocess.Process | None = None

    def log(self, line: str) -> None:
        self.lines.append(line)
        if len(self.lines) > MAX_LOG_LINES:
            cut = len(self.lines) - MAX_LOG_LINES + 500
            del self.lines[:cut]
            self.dropped += cut

    def display(self) -> list[str]:
        shown = []
        for argv in self.steps:
            args = ["promptfoo", *argv[len(promptfoo_cmd()):]]
            shown.append(" ".join(shlex.quote(a.replace(str(REPO_ROOT) + "/", "")) for a in args))
        return shown

    def public(self) -> dict[str, Any]:
        output = self.output.name if self.output and self.output.exists() else None
        return {
            "id": self.id, "command": self.command, "label": self.label, "status": self.status,
            "config": self.config, "created_at": self.created_at, "started_at": self.started_at,
            "finished_at": self.finished_at, "exit_code": self.exit_code, "step": self.step,
            "step_count": len(self.steps), "commands": self.display(),
            "output": output, "output_kind": self.output.suffix.lstrip(".") if output else None,
            "log_lines": self.dropped + len(self.lines),
        }


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self._tasks: set[asyncio.Task] = set()
        self._slots: asyncio.Semaphore | None = None

    def submit(self, job: Job) -> Job:
        self.jobs[job.id] = job
        finished = [j for j in self.jobs.values() if j.finished_at]
        for old in finished[: max(0, len(self.jobs) - MAX_JOBS_KEPT)]:
            self.jobs.pop(old.id, None)
        task = asyncio.create_task(self._run(job))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    def cancel(self, job: Job) -> None:
        job.cancelled = True
        if job.proc and job.proc.returncode is None:
            job.proc.terminate()

    async def _run(self, job: Job) -> None:
        self._slots = self._slots or asyncio.Semaphore(MAX_PARALLEL_JOBS)
        async with self._slots:
            if job.cancelled:
                job.status, job.finished_at = "cancelled", _now()
                return
            job.status, job.started_at = "running", _now()
            try:
                await self._run_steps(job)
            except Exception as exc:  # pragma: no cover - defensive: keep the job record consistent
                job.log(f"[service] error: {exc}")
                job.status = "failed"
            finally:
                job.proc = None
                job.finished_at = _now()
                upload = [p for p in (_file_in(CONFIG_WORKSPACE, n, (".yaml", ".yml"))
                                      for n in {job.config, job.eval_config} if n) if p]
                if job.output and job.output.exists():
                    upload.append(job.output)
                if job.output and job.output.exists() and job.output.suffix == ".json":
                    meta = {"job_id": job.id, "command": job.command, "config": job.config,
                            "eval_config": job.eval_config, "created_at": job.finished_at}
                    meta_path = safe_join(META_DIR, f"{job.output.name}.json")
                    meta_path.write_text(json.dumps(meta), encoding="utf-8")
                    upload.append(meta_path)
                await asyncio.to_thread(STORAGE.push, upload)

    async def _run_steps(self, job: Job) -> None:
        _ensure_dirs()
        await asyncio.to_thread(STORAGE.pull_data)
        env = promptfoo_env()
        for index, (argv, shown) in enumerate(zip(job.steps, job.display())):
            job.step = index
            job.log(f"$ {shown}")
            proc = await asyncio.create_subprocess_exec(
                *argv, cwd=str(PROMPTFOO_DIR), env=env, limit=1 << 20,
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
            job.proc = proc
            try:
                await asyncio.wait_for(self._pump(job, proc), timeout=JOB_TIMEOUT)
            except asyncio.TimeoutError:
                proc.kill()
                job.log(f"[service] step timed out after {JOB_TIMEOUT}s")
                job.status = "failed"
                return
            job.exit_code = proc.returncode
            if job.cancelled:
                job.status = "cancelled"
                return
            if proc.returncode == 100:
                job.log("[service] exit 100: run completed and some tests failed (attack succeeded or assertion failed).")
            if proc.returncode not in OK_EXIT_CODES:
                job.status = "failed"
                return
            missing = next((a.split("=", 1)[1] for a in argv if a.startswith("--output=")
                            and not Path(a.split("=", 1)[1]).exists()), None)
            if missing:
                job.log(f"[service] step {index + 1} exited {proc.returncode} but did not write {Path(missing).name}.")
                if "generate" in argv:
                    job.log("[service] No attack probes were generated. The attack-generator model was likely unreachable "
                            "or refused, or every plugin needs remote generation (PROMPTFOO_DISABLE_REMOTE_GENERATION=true). "
                            "Check the output above, the ADVERSARIAL_OPENAI_*/AUDIT_LLM_* settings, and network access to Azure OpenAI.")
                job.status = "failed"
                return
        job.status = "succeeded"

    @staticmethod
    async def _pump(job: Job, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdout is not None
        async for raw in proc.stdout:
            for part in ANSI.sub("", raw.decode("utf-8", errors="replace")).splitlines():
                job.log(part.rstrip())
        await proc.wait()


JOBS = JobManager()


# ---------------------------------------------------------------- results

def _text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    return value[:limit]


def result_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    block = data.get("results", data)
    items = block.get("results", []) if isinstance(block, dict) else []
    rows = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        test = item.get("testCase") or {}
        meta = {**(item.get("metadata") or {}), **(test.get("metadata") or {})}
        variables = item.get("vars") or test.get("vars") or {}
        grading = item.get("gradingResult") or {}
        response = item.get("response") or {}
        # failureReason: 0 none, 1 assertion failed, 2 error. `error` also carries the grader's text for failures.
        failure = item.get("failureReason")
        if failure == 2 or (failure is None and item.get("error") and not item.get("success")):
            status = "error"
        else:
            status = "pass" if item.get("success") else "fail"
        rows.append({
            "index": index,
            "status": status,
            "score": item.get("score"),
            "plugin": meta.get("pluginId") or "",
            "strategy": meta.get("strategyId") or ("basic" if meta.get("pluginId") else ""),
            "description": _text(test.get("description") or meta.get("goal"), 300),
            "prompt": _text((item.get("prompt") or {}).get("raw") or variables.get("prompt") or variables.get("query"), 6000),
            "output": _text(response.get("output") if isinstance(response, dict) else response, 8000),
            "reason": _text(grading.get("reason") or item.get("error"), 3000),
            "latency_ms": item.get("latencyMs"),
        })
    return rows


def _group(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = row[key] or "—"
        entry = groups.setdefault(name, {"name": name, "pass": 0, "fail": 0, "error": 0})
        entry[row["status"]] += 1
    return sorted(groups.values(), key=lambda g: (-(g["fail"]), g["name"]))


def summarize_result(data: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    block = data.get("results") if isinstance(data.get("results"), dict) else {}
    config = data.get("config") if isinstance(data.get("config"), dict) else {}
    counts = {s: sum(r["status"] == s for r in rows) for s in ("pass", "fail", "error")}
    graded = counts["pass"] + counts["fail"]
    return {
        "eval_id": data.get("evalId"),
        "description": config.get("description"),
        "timestamp": block.get("timestamp"),
        "total": len(rows),
        **counts,
        "pass_rate": round(100 * counts["pass"] / graded, 1) if graded else None,
        "redteam": bool(config.get("redteam")) or any(r["plugin"] for r in rows),
    }


_SUMMARY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _load_result(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"Result is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="Result is not a promptfoo JSON export.")
    return data


def _meta(name: str) -> dict[str, Any]:
    try:
        return json.loads(safe_join(META_DIR, f"{name}.json").read_text(encoding="utf-8"))
    except (HTTPException, OSError, json.JSONDecodeError):
        return {}


# ---------------------------------------------------------------- API

def require_token(x_run_token: str | None = Header(default=None)) -> None:
    if RUN_TOKEN and not hmac.compare_digest(x_run_token or "", RUN_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")


router = APIRouter(prefix="/api/promptfoo", dependencies=[Depends(require_token)])
_VERSION: dict[str, str] = {}


class JobRequest(BaseModel):
    command: str
    options: dict[str, Any] = Field(default_factory=dict)


def _start(command_id: str, options: dict[str, Any], label: str | None = None) -> Job:
    command = COMMANDS.get(command_id)
    if command is None:
        raise HTTPException(status_code=400, detail=f"Unknown command: {command_id}")
    _ensure_dirs()
    steps, output, config, eval_config = build_steps(command, options)
    job = Job(id=uuid.uuid4().hex[:12], command=command.id, label=label or command.label,
              steps=steps, config=config, output=output, eval_config=eval_config)
    return JOBS.submit(job)


def _job_or_404(job_id: str) -> Job:
    job = JOBS.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found. Jobs are kept in memory until the container restarts.")
    return job


@router.get("/info")
async def info() -> dict[str, Any]:
    if "version" not in _VERSION:
        try:
            proc = await asyncio.create_subprocess_exec(*promptfoo_cmd(), "--version", env=promptfoo_env(),
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=90)
            _VERSION["version"] = out.decode().strip().splitlines()[-1] if out.strip() else "unknown"
        except (OSError, asyncio.TimeoutError, IndexError):
            return {"status": "degraded", "version": None, "detail": "promptfoo CLI not found or not responding."}
    backend_host = re.sub(r"^\w+://", "", settings.backend_api_url or "").split("/")[0]
    return {
        "status": "ok",
        "version": _VERSION["version"],
        "target": {"label": TARGET_LABEL, "backend_host": backend_host, "configured": bool(settings.backend_api_url)},
        "grader_configured": judge_provider() is not None,
        "remote_generation_disabled": os.getenv("PROMPTFOO_DISABLE_REMOTE_GENERATION", "").lower() in {"1", "true"},
        "running_jobs": sum(j.status == "running" for j in JOBS.jobs.values()),
        "queued_jobs": sum(j.status == "queued" for j in JOBS.jobs.values()),
        "max_parallel_jobs": MAX_PARALLEL_JOBS,
        "storage": STORAGE.describe(),
    }


@router.post("/jobs")
async def create_job(req: JobRequest) -> dict[str, Any]:
    return _start(req.command, req.options).public()


# ---------------------------------------------------------------- test files

@router.get("/tests/files")
async def list_test_files() -> list[dict[str, Any]]:
    """Every YAML file in data_promptfoo/ (the PROMPTFOO_DATA_CONTAINER_NAME blob container when Azure is configured)."""
    await asyncio.to_thread(STORAGE.pull_data)
    items = []
    for path in sorted(DATA_DIR.glob("*")) if DATA_DIR.is_dir() else []:
        if not path.is_file() or path.suffix not in (".yaml", ".yml") or path.name.startswith("."):
            continue
        try:
            count, error = len(load_dataset_cases(path.name)), None
        except HTTPException as exc:
            count, error = None, str(exc.detail)
        items.append({"name": path.name, "cases": count, "error": error})
    return items


async def _ensure_local_dataset(name: str) -> None:
    """Fetch the file from the Azure data container when this replica does not have it yet."""
    if STORAGE.enabled and _file_in(DATA_DIR, name, (".yaml", ".yml", ".json")) is None:
        await asyncio.to_thread(STORAGE.pull_data)


@router.get("/tests/datasets/{name}/cases")
async def list_dataset_cases(name: str) -> list[dict[str, Any]]:
    await _ensure_local_dataset(name)
    return [{"index": i, "label": case_label(c), "checks": len(c.get("assert") or [])}
            for i, c in enumerate(load_dataset_cases(name))]


class DatasetRunRequest(BaseModel):
    dataset: str = Field(min_length=1, max_length=160)
    cases: list[int] = Field(min_length=1, max_length=1000)


@router.post("/tests/run")
async def run_dataset_tests(req: DatasetRunRequest) -> dict[str, Any]:
    _ensure_dirs()
    await _ensure_local_dataset(req.dataset)
    config = write_dataset_config(req.dataset, req.cases)
    return _start("eval", {"config": config.name}, label=f"Tests · {req.dataset}").public()


@router.get("/jobs")
async def list_jobs() -> list[dict[str, Any]]:
    return [j.public() for j in sorted(JOBS.jobs.values(), key=lambda j: j.created_at, reverse=True)]


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    return _job_or_404(job_id).public()


@router.get("/jobs/{job_id}/logs")
async def get_job_logs(job_id: str, since: int = 0) -> dict[str, Any]:
    job = _job_or_404(job_id)
    start = max(since - job.dropped, 0)
    return {"lines": job.lines[start:start + 2000], "next": job.dropped + min(len(job.lines), start + 2000),
            "status": job.status, "truncated": since < job.dropped}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict[str, Any]:
    job = _job_or_404(job_id)
    if job.finished_at is None:
        JOBS.cancel(job)
    return job.public()


@router.get("/results")
async def list_results() -> list[dict[str, Any]]:
    _ensure_dirs()
    await asyncio.to_thread(STORAGE.pull_results)
    items = []
    for path in sorted(RESULTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:300]:
        mtime = path.stat().st_mtime
        cached = _SUMMARY_CACHE.get(path.name)
        if not cached or cached[0] != mtime:
            try:
                data = _load_result(path)
                summary = summarize_result(data, result_rows(data))
            except HTTPException:
                summary = {"total": 0, "unreadable": True}
            cached = _SUMMARY_CACHE[path.name] = (mtime, summary)
        items.append({"name": path.name, "size": path.stat().st_size, "meta": _meta(path.name),
                      "updated_at": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(), "summary": cached[1]})
    return items


@router.get("/results/{name}")
async def get_result(name: str, status: Literal["all", "pass", "fail", "error"] = "all") -> dict[str, Any]:
    path = resolve_result(name)
    data = _load_result(path)
    rows = result_rows(data)
    shown = rows if status == "all" else [r for r in rows if r["status"] == status]
    return {
        "name": path.name, "meta": _meta(path.name), "summary": summarize_result(data, rows),
        "by_plugin": _group(rows, "plugin"), "by_strategy": _group(rows, "strategy"),
        "rows": shown[:MAX_ROWS], "row_count": len(shown),
    }


@router.get("/results/{name}/download")
async def download_result(name: str) -> FileResponse:
    path = resolve_result(name)
    return FileResponse(path, media_type="application/json", filename=path.name)


@router.get("/results/{name}/csv")
async def result_csv(name: str) -> Response:
    rows = result_rows(_load_result(resolve_result(name)))
    buffer = io.StringIO()
    columns = ["index", "status", "score", "plugin", "strategy", "description", "prompt", "output", "reason", "latency_ms"]
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        # Neutralise spreadsheet formulas in untrusted model output.
        writer.writerow({k: ("'" + v if isinstance(v, str) and v[:1] in "=+-@" else v) for k, v in row.items()})
    filename = name.rsplit(".", 1)[0] + ".csv"
    return Response("\ufeff" + buffer.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _log_effective_config() -> None:
    host = re.sub(r"^\w+://", "", settings.backend_api_url or "").split("/")[0]
    logger.info("promptfoo target backend=%s grader_key=%s attack_key=%s", host or "<unset>",
                bool(settings.AUDIT_LLM_api_key), bool(settings.adversarial_api_key))
    if host.startswith(("localhost", "127.0.0.1")):
        logger.warning("BACKEND_API_URL points at %s, which is not the AIFA app. Check promptfoo/.env "
                       "(or the container's BACKEND_API_URL); /invoke will fail with 'Connection refused'.", host)


async def _sync_on_startup() -> None:
    _log_effective_config()
    _ensure_dirs()
    await asyncio.to_thread(STORAGE.pull_data)
    await asyncio.to_thread(STORAGE.pull_results, True)


app.router.on_startup.append(_sync_on_startup)
app.include_router(router)
