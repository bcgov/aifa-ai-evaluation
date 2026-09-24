"""Evaluation runner - simplified."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import structlog

from aifa_pyrit.config import settings
from aifa_pyrit.client import BackendClient
from aifa_pyrit.evaluators.pyrit_security import PyRITSecurityEvaluator
from aifa_pyrit.search_client import AzureSearchContextRetriever

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger(__name__)

# Initialize AI Search retriever if configured
search_retriever = None
if settings.use_azure_search():
    try:
        search_retriever = AzureSearchContextRetriever()
        logger.info("azure_search_retriever_enabled")
    except Exception as e:
        logger.warning(f"azure_search_retriever_init_failed: {str(e)}")


def load_context(query: str = "") -> str:
    """
    Load context from Azure AI Search or fallback to file.
    
    Args:
        query: Search query (used for AI Search)
        file: Fallback file path for context
        
    Returns:
        Context string
    """
    if search_retriever:
        try:
            context = search_retriever.retrieve_context(query or "permit application")
            logger.info("context_retrieved_from_search")
            return context
        except Exception as e:
            logger.warning(f"search_context_retrieval_failed: {str(e)}")
    logger.warning("no_context_available")
    return ""


def extract_text(obj):
    """Extract text from response object."""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list) and obj:
        first = obj[0]
        if isinstance(first, dict) and "response" in first:
            return first["response"]
        return str(first)
    if isinstance(obj, dict) and "response" in obj:
        return obj["response"]
    return json.dumps(obj, ensure_ascii=False)


def summary_stats(evals):
    """Calculate summary from evaluations."""
    scores = [e["score"] for e in evals.values()]
    if not scores:
        return {"overall_score": 0.0, "count": 0}
    avg = sum(scores) / len(scores)
    return {
        "overall_score": round(avg, 2),
        "count": len(scores),
        "min": round(min(scores), 2),
        "max": round(max(scores), 2),
    }


class EvaluationRunner:
    """Run evaluation on backend responses."""

    def __init__(self):
        all_evals = {
            "security": PyRITSecurityEvaluator(),
        }

        enabled = [e.strip().lower() for e in settings.enabled_evaluators.split(",") if e.strip()]
        if enabled:
            self.evaluators = {
                k: v for k, v in all_evals.items() if k.lower() in enabled or any(name in enabled for name in ("pyrit_security", "security"))
            }
        else:
            self.evaluators = {}

        if not self.evaluators:
            logger.info("evaluators_initialized - enabled: [] using_minimal_pyrit_scorer")
        else:
            logger.info(f"evaluators_initialized - enabled: {list(self.evaluators.keys())}")

    async def run(self):
        """Run evaluation."""
        logger.info(f"eval_start - run: {settings.evaluation_run_name}")
        
        try:
            async with BackendClient() as client:
                is_healthy = await client.health_check()
                cases = client.get_sample_cases()
                logger.info(f"cases_loaded - count: {len(cases)}")

                results = []
                for case in cases:
                    resp = await client.invoke(
                        query=case["query"],
                        step_number=case.get("step_number"),
                    )
                    text = extract_text(resp.get("response", resp))
                    evals = self._eval_response(text, query=case["query"])
                    results.append({
                        "case": case,
                        "response": resp,
                        "evaluations": evals,
                        "summary": summary_stats(evals),
                    })

                scores = [r["summary"]["overall_score"] for r in results]
                overall = round(sum(scores) / len(scores), 2) if scores else 0.0

                output = {
                    "run_name": settings.evaluation_run_name,
                    "scenario": settings.evaluation_scenario,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "backend_url": settings.backend_api_url,
                    "backend_healthy": is_healthy,
                    "cases": results,
                    "summary": {
                        "overall_score": overall,
                        "case_count": len(results),
                    },
                }
                logger.info(f"eval_complete - score: {overall}")
                return output
                
        except Exception as e:
            logger.exception("eval_failed")
            raise

    def _eval_response(self, response: str, query: str = ""):
        """Evaluate response with any explicitly enabled evaluators."""
        context = load_context(query=query)
        inputs = {
            "security": {"response": response, "query": query, "context": context},
        }

        results = {}
        for name, evaluator in self.evaluators.items():
            try:
                results[name] = evaluator(**inputs.get(name, {}))
            except Exception:
                logger.exception("eval_error", evaluator=name)
                results[name] = {"score": 0.0, "reason": "Evaluation error", "metadata": {}}
        return results

    def save_results(self, results, output_dir: str = "results"):
        """Save results to JSON file."""
        try:
            Path(output_dir).mkdir(exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filepath = Path(output_dir) / f"eval_{timestamp}.json"
            json.dump(results, open(filepath, "w"), indent=2)
            logger.info(f"results_saved - file: {str(filepath)}")
        except Exception as e:
            logger.exception("save_failed")


async def main():
    """Main entry point."""
    try:
        settings.validate_config()
        runner = EvaluationRunner()
        results = await runner.run()
        runner.save_results(results)
        print("\n" + "=" * 60)
        print("Evaluation Complete")
        print("=" * 60)
        print(json.dumps(results, indent=2))
        return results
    except ValueError as e:
        logger.error("config_error", error=str(e))
        raise
    except Exception as e:
        logger.exception("unexpected_error")
        raise


if __name__ == "__main__":
    asyncio.run(main())
