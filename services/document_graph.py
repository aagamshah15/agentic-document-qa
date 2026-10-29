"""A small, explicit LangGraph model/tool loop for document inventory."""

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, MessagesState, StateGraph

from services.document_agent_runtime import SYSTEM_PROMPT, execute_tool_calls, response_failure


class DocumentAgentState(MessagesState):
    """Messages are accumulated by LangGraph; counters belong to one invocation."""

    model_calls: int
    tool_requests: int
    stop_reason: str


def build_document_graph(model, document_tool, *, max_model_calls=4, max_tool_calls=3):
    """Compile a bounded single-request agent with injectable model and tool.

    There is no persistent chat memory or checkpointer yet. Model failures
    propagate to the caller; expected tool errors become model-visible results.
    Tool budgets count requests, including unknown tools and invalid arguments.
    """
    if max_model_calls < 1 or max_tool_calls < 1:
        raise ValueError("Model and tool call limits must be positive.")
    bound_model = model.bind_tools([document_tool])

    def call_model(state: DocumentAgentState, config: RunnableConfig):
        response = bound_model.invoke(
            [SystemMessage(content=SYSTEM_PROMPT), *state["messages"]], config=config
        )
        if not isinstance(response, AIMessage):
            raise TypeError("Expected an AIMessage from the model.")
        complete = bool(response.content) and not response.tool_calls and not response.invalid_tool_calls
        return {
            "messages": [response],
            "model_calls": state.get("model_calls", 0) + 1,
            "stop_reason": "completed" if complete else "running",
        }

    def route_after_model(state: DocumentAgentState):
        response = state["messages"][-1]
        if response.invalid_tool_calls or response_failure(response):
            return "stop"
        if not response.tool_calls:
            return END if response.content else "stop"
        if (state["model_calls"] >= max_model_calls
                or state.get("tool_requests", 0) >= max_tool_calls):
            return "stop"
        return "tools"

    def call_tools(state: DocumentAgentState):
        response = state["messages"][-1]
        used = state.get("tool_requests", 0)
        results = execute_tool_calls(response, document_tool, max_tool_calls - used)
        return {"messages": results, "tool_requests": used + len(response.tool_calls)}

    def stop(state: DocumentAgentState):
        response = state["messages"][-1]
        failure = response_failure(response)
        if failure:
            reason = failure
            answer = "I could not complete the request because the model response was truncated or malformed."
        elif response.invalid_tool_calls:
            reason = "malformed_tool_call"
            answer = "I could not complete the request because the model returned a malformed tool call."
        elif not response.tool_calls:
            reason = "empty_response"
            answer = "I could not complete the request because the model returned an empty response."
        else:
            reason = "call_limit"
            answer = "I stopped because the agent reached its call limit. The request may be incomplete."
        # Close pending tool calls without executing them, preserving valid history.
        cancelled = execute_tool_calls(response, document_tool, remaining_calls=0)
        return {"messages": [*cancelled, AIMessage(content=answer)], "stop_reason": reason}

    builder = StateGraph(DocumentAgentState)
    builder.add_node("model", call_model)
    builder.add_node("tools", call_tools)
    builder.add_node("stop", stop)
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", route_after_model, ["tools", "stop", END])
    builder.add_edge("tools", "model")
    builder.add_edge("stop", END)
    return builder.compile()
