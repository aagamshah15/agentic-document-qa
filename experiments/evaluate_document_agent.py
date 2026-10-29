"""Opt-in real-model evaluations using synthetic files, never user uploads."""

import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from time import monotonic

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langsmith import tracing_context

from experiments.document_agent import message_record, run_manual_exchange
from services.document_agent_runtime import DEFAULT_MODEL, make_local_model, response_failure
from services.document_catalog import list_documents
from services.document_graph import build_document_graph
from services.document_tools import make_list_documents_tool


def unavailable_catalog():
    raise PermissionError("Synthetic storage failure")


def run_evaluations(model_name, mode):
    model = make_local_model(model_name)
    records = []
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        populated = root / "populated"
        populated.mkdir()
        for name in ["alpha-report.pdf", "budget-2026.pdf"]:
            (populated / name).write_bytes(b"Synthetic inventory fixture, not a valid PDF")
        empty = root / "empty"
        empty.mkdir()
        reader = lambda: list_documents(populated)
        cases = [
            ("list", "Which documents have I uploaded?", reader, 1, "success"),
            ("count", "How many documents have I uploaded?", reader, 1, "success"),
            ("exists", "Have I uploaded budget-2026.pdf?", reader, 1, "success"),
            ("greeting", "Hello!", reader, 0, None),
            ("empty", "Which documents have I uploaded?", lambda: list_documents(empty), 1, "success"),
            ("storage_error", "Which documents have I uploaded?", unavailable_catalog, 1, "error"),
        ]

        for name, question, catalog_reader, expected_calls, expected_status in cases:
            started = monotonic()
            tool = make_list_documents_tool(catalog_reader)
            try:
                with tracing_context(enabled=False):
                    if mode == "manual":
                        messages = run_manual_exchange(question, model, tool)
                        stop_reason = "completed"
                    else:
                        graph = build_document_graph(model, tool)
                        state = graph.invoke({"messages": [HumanMessage(content=question)]})
                        messages = state["messages"]
                        stop_reason = state["stop_reason"]
                results = [message for message in messages if isinstance(message, ToolMessage)]
                answer = str(messages[-1].content)
                checks = {
                    "completed": stop_reason == "completed",
                    "tool_count": len(results) == expected_calls,
                    "tool_status": all(result.status == expected_status for result in results),
                    "nonempty_answer": bool(answer.strip()),
                    "well_formed_responses": all(
                        response_failure(message) is None
                        for message in messages if isinstance(message, AIMessage)
                    ),
                }
                if name == "list":
                    checks["filenames_present"] = all(
                        filename in answer for filename in ["alpha-report.pdf", "budget-2026.pdf"]
                    )
                elif name == "count":
                    checks["correct_count"] = bool(re.search(r"\b(2|two)\b", answer, re.I))
                elif name == "exists":
                    checks["file_confirmed"] = "budget-2026.pdf" in answer and bool(
                        re.search(r"\b(yes|uploaded|exists|available|found)\b", answer, re.I)
                    )
                elif name == "empty":
                    checks["empty_reported"] = bool(re.search(
                        r"\b(no|none|zero|0|empty|haven't|not|any)\b", answer, re.I
                    ))
                    checks["empty_tool_data"] = bool(results) and json.loads(results[0].content)["documents"] == []
                elif name == "storage_error":
                    checks["failure_reported"] = bool(re.search(
                        r"\b(error|failed|unable|cannot|can't|couldn't|could not)\b", answer, re.I
                    ))
                record = {
                    "case": name, "passed": all(checks.values()), "checks": checks,
                    "answer": answer, "seconds": round(monotonic() - started, 2),
                    "messages": [message_record(message) for message in messages if message.type != "system"],
                }
            except Exception as error:
                # Evaluate the remaining cases, but never turn an exception into a pass.
                record = {"case": name, "passed": False, "error": str(error)}
            records.append(record)
            print(json.dumps({key: value for key, value in record.items() if key != "messages"}), flush=True)
    return {
        "model": model_name, "mode": mode, "timestamp": datetime.now(timezone.utc).isoformat(),
        "packages": {name: version(name) for name in ["langchain-core", "langchain-ollama", "langgraph"]},
        "settings": {
            "temperature": model.temperature, "seed": model.seed, "num_ctx": model.num_ctx,
            "num_predict": model.num_predict, "reasoning": model.reasoning,
        },
        "cases": records, "passed": all(record["passed"] for record in records),
        "note": "Answer checks are heuristics; review saved transcripts for factual correctness.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--mode", choices=["manual", "graph"], default="graph")
    parser.add_argument("--output", type=Path, default=Path("data/agent_evaluation.json"))
    args = parser.parse_args()
    report = run_evaluations(args.model, args.mode)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"Report: {args.output.resolve()}")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
