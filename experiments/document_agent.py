"""Run a visible model/tool exchange, manually or using LangGraph."""

import argparse
import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langsmith import tracing_context

from services.document_agent_runtime import (
    DEFAULT_MODEL, SYSTEM_PROMPT, execute_tool_calls, make_local_model, response_failure,
)
from services.document_tools import make_list_documents_tool


def run_manual_exchange(question, model, document_tool):
    """One tool round demonstrates the protocol before introducing a graph."""
    messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=question)]
    bound_model = model.bind_tools([document_tool])
    response = bound_model.invoke(messages)
    messages.append(response)
    if response_failure(response):
        raise RuntimeError(f"Model response failed: {response_failure(response)}")
    if response.invalid_tool_calls:
        raise RuntimeError("Model returned a malformed tool call.")
    if response.tool_calls:
        messages.extend(execute_tool_calls(response, document_tool, remaining_calls=1))
        response = bound_model.invoke(messages)
        messages.append(response)
        if response_failure(response):
            raise RuntimeError(f"Model response failed: {response_failure(response)}")
        if response.tool_calls or response.invalid_tool_calls:
            raise RuntimeError("Manual experiment allows one tool round; model requested more.")
    if not isinstance(response, AIMessage) or not response.content:
        raise RuntimeError("Model did not provide a final answer.")
    return messages


def message_record(message):
    record = {"role": message.type, "content": message.content}
    if isinstance(message, AIMessage) and message.tool_calls:
        record["tool_calls"] = message.tool_calls
    if message.response_metadata.get("done_reason"):
        record["done_reason"] = message.response_metadata["done_reason"]
    if message.type == "tool":
        record.update(tool_call_id=message.tool_call_id, status=message.status)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?", default="Which documents have I uploaded?")
    parser.add_argument("--mode", choices=["manual", "graph"], default="manual")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()
    model = make_local_model(args.model)
    document_tool = make_list_documents_tool()
    stop_reason = "completed"

    # The experiment stays local even if the shell has cloud tracing enabled.
    with tracing_context(enabled=False):
        if args.mode == "manual":
            messages = run_manual_exchange(args.question, model, document_tool)
        else:
            from services.document_graph import build_document_graph

            graph = build_document_graph(model, document_tool)
            state = graph.invoke({"messages": [HumanMessage(content=args.question)]})
            messages = state["messages"]
            stop_reason = state["stop_reason"]
    for message in messages:
        if message.type != "system":
            print(json.dumps(message_record(message), ensure_ascii=False))
    if args.mode == "graph":
        print(json.dumps({
            "stop_reason": stop_reason, "model_calls": state["model_calls"],
            "tool_requests": state.get("tool_requests", 0),
        }))
    if stop_reason != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
