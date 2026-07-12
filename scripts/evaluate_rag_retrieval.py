"""Evaluate small offline RAG retrieval recall benchmarks."""
from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("ZHIXING_SUPPRESS_CONSOLE_LOGS", "1")
warnings.filterwarnings("ignore", category=SyntaxWarning, module=r"jieba.*")
warnings.filterwarnings("ignore", category=UserWarning, module=r"jieba.*")

from app.evaluation.rag_retrieval import (  # noqa: E402
    DEFAULT_DOCUMENTS_DIR,
    DEFAULT_RAG_RETRIEVAL_SCENARIO_FILE,
    evaluate_rag_mixed_corpus_safety,
    evaluate_rag_retrieval,
    render_rag_retrieval_markdown,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a deterministic offline RAG retrieval recall benchmark. "
            "No .env, LLM, vector database, or external API is required."
        )
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_RAG_RETRIEVAL_SCENARIO_FILE,
        help="Path to the retrieval scenario catalog.",
    )
    parser.add_argument(
        "--documents-dir",
        type=Path,
        default=DEFAULT_DOCUMENTS_DIR,
        help="Path to the RAG knowledge document directory.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        nargs="+",
        default=[3, 5],
        help="One or more Top-K values to evaluate.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of Markdown.",
    )
    parser.add_argument(
        "--mixed-corpus-safety",
        action="store_true",
        help=(
            "Run the public mixed-corpus safety gate: keep public and internal "
            "documents in the candidate set, then enforce forbidden-hit guardrails."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional output file. Parent directories are created as needed.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    evaluator = (
        evaluate_rag_mixed_corpus_safety
        if args.mixed_corpus_safety
        else evaluate_rag_retrieval
    )
    result = evaluator(
        scenario_path=args.catalog,
        documents_dir=args.documents_dir,
        top_k_values=args.top_k,
    )
    if args.json:
        rendered = json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
    else:
        rendered = render_rag_retrieval_markdown(result)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
