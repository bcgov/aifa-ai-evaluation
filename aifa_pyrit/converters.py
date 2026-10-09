"""Build PyRIT attack converter configuration from simple converter names."""

from __future__ import annotations

import importlib
from typing import Any, Dict, List, Optional

CONVERTER_CLASSES: Dict[str, str] = {
    "base64": "Base64Converter",
    "rot13": "ROT13Converter",
    "leetspeak": "LeetspeakConverter",
    "morse": "MorseConverter",
    "ascii_smuggler": "AsciiSmugglerConverter",
    "translation": "TranslationConverter",
}

LLM_CONVERTERS = {"translation"}
DEFAULT_TRANSLATION_LANGUAGE = "french"

CONVERTER_MODULES = ("pyrit.converter", "pyrit.prompt_converter")

CONFIGURATION_LOCATIONS = (
    ("pyrit.prompt_normalizer", "PromptConverterConfiguration"),
    ("pyrit.prompt_normalizer", "ConverterConfiguration"),
    ("pyrit.executor.attack", "PromptConverterConfiguration"),
    ("pyrit.executor.attack", "ConverterConfiguration"),
)


def available_converters() -> List[str]:
    return sorted(CONVERTER_CLASSES)


def needs_llm(names: Optional[List[str]]) -> bool:
    return any(n.split(":", 1)[0] in LLM_CONVERTERS for n in (names or []))


def normalize_converter_names(names: Optional[List[str]]) -> List[str]:
    cleaned = [str(n).strip().lower() for n in (names or []) if str(n).strip()]
    unknown = [n for n in cleaned if n.split(":", 1)[0] not in CONVERTER_CLASSES]
    if unknown:
        raise ValueError(
            f"Unknown converter(s): {', '.join(unknown)}. Available: {', '.join(available_converters())}"
        )
    return cleaned


def _import_first(candidates: List[tuple], what: str) -> Any:
    for module_name, attr in candidates:
        try:
            return getattr(importlib.import_module(module_name), attr)
        except (ImportError, AttributeError):
            continue
    raise ImportError(f"Could not import {what} from this PyRIT version")


LLM_FAILURE_PREFIXES = ("Azure OpenAI ", "Error querying Azure OpenAI", "No user message found")


class ConverterFailedError(RuntimeError):
    """Raised when an LLM-backed converter returns an error message instead of converted text."""


def _fail_on_llm_error(converter: Any, name: str) -> Any:
    original = converter.convert_async

    async def guarded(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)
        text = str(getattr(result, "output_text", "") or "")
        if text.startswith(LLM_FAILURE_PREFIXES):
            raise ConverterFailedError(f"Converter '{name}' failed and returned an error instead of converted text: {text[:300]}")
        return result

    converter.convert_async = guarded
    return converter


def _make_converter(name: str, converter_target: Any) -> Any:
    base, _, option = name.partition(":")
    cls = _import_first([(m, CONVERTER_CLASSES[base]) for m in CONVERTER_MODULES], CONVERTER_CLASSES[base])
    if base == "translation":
        if converter_target is None:
            raise ValueError("The translation converter needs an LLM target (converter_target)")
        converter = cls(converter_target=converter_target, language=option or DEFAULT_TRANSLATION_LANGUAGE)
        return _fail_on_llm_error(converter, name)
    return cls()


def build_converter_config(names: Optional[List[str]], converter_target: Any = None) -> Any:
    """Return an AttackConverterConfig applying the named converters in order, or None if no names given."""
    cleaned = normalize_converter_names(names)
    if not cleaned:
        return None

    converters = [_make_converter(n, converter_target) for n in cleaned]
    configuration = _import_first(list(CONFIGURATION_LOCATIONS), "converter configuration")
    attack_converter_config = _import_first(
        [("pyrit.executor.attack", "AttackConverterConfig")], "AttackConverterConfig"
    )
    return attack_converter_config(request_converters=configuration.from_converters(converters=converters))
