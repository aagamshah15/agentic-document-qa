import json
import unittest
from unittest.mock import Mock

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langsmith import tracing_context

from experiments.document_agent import run_manual_exchange
from services.document_graph import build_document_graph
from services.document_tools import make_list_documents_tool
from tests_agent.test_document_tools import tool_call


class ScriptedModel:
    """Control model outputs while exercising the real graph and real tools."""

    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def bind_tools(self, tools):
        self.tools = tools
        return self

    def invoke(self, messages, config=None):
        self.requests.append(list(messages))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class DocumentGraphTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(tracing_context(enabled=False))
        self.reader = Mock(return_value=[])
        self.tool = make_list_documents_tool(self.reader)

    def run_graph(self, model, **limits):
        graph = build_document_graph(model, self.tool, **limits)
        return graph.invoke({"messages": [HumanMessage(content="List my documents.")]})

    def test_greeting_can_finish_without_any_tool_calls(self):
        model = ScriptedModel(AIMessage(content="Hello!"))
        state = self.run_graph(model)
        self.reader.assert_not_called()
        self.assertEqual(state["stop_reason"], "completed")
        self.assertEqual(state["model_calls"], 1)

    def test_tool_result_reaches_model_with_matching_call_id(self):
        model = ScriptedModel(
            AIMessage(content="", tool_calls=[tool_call()]), AIMessage(content="No PDFs are saved.")
        )
        state = self.run_graph(model)
        self.reader.assert_called_once_with()
        result = model.requests[1][-1]
        self.assertIsInstance(result, ToolMessage)
        self.assertEqual(result.tool_call_id, "request-1")
        self.assertEqual(json.loads(result.content)["documents"], [])
        self.assertEqual(state["model_calls"], 2)
        self.assertEqual(state["tool_requests"], 1)
        self.assertEqual(state["stop_reason"], "completed")

    def test_storage_error_reaches_model_as_error_not_empty_inventory(self):
        self.reader.side_effect = PermissionError("private path")
        model = ScriptedModel(
            AIMessage(content="", tool_calls=[tool_call()]), AIMessage(content="The listing failed.")
        )
        self.run_graph(model)
        self.assertEqual(model.requests[1][-1].status, "error")
        self.assertNotIn("private path", model.requests[1][-1].content)

    def test_model_can_correct_invalid_arguments(self):
        model = ScriptedModel(
            AIMessage(content="", tool_calls=[tool_call(args={"path": "/tmp"})]),
            AIMessage(content="", tool_calls=[tool_call(call_id="corrected")]),
            AIMessage(content="No documents are saved."),
        )
        state = self.run_graph(model)
        self.reader.assert_called_once_with()
        self.assertEqual(model.requests[1][-1].status, "error")
        self.assertEqual(model.requests[2][-1].status, "success")
        self.assertEqual(state["tool_requests"], 2)

    def test_model_can_correct_an_unknown_tool(self):
        model = ScriptedModel(
            AIMessage(content="", tool_calls=[tool_call(name="search_documents")]),
            AIMessage(content="", tool_calls=[tool_call(call_id="corrected")]),
            AIMessage(content="No documents are saved."),
        )
        self.run_graph(model)
        self.reader.assert_called_once_with()
        self.assertEqual(model.requests[1][-1].status, "error")

    def test_repeated_requests_stop_at_model_call_limit(self):
        model = ScriptedModel(*[
            AIMessage(content="", tool_calls=[tool_call(call_id=str(index))]) for index in range(3)
        ])
        state = self.run_graph(model, max_model_calls=3, max_tool_calls=10)
        self.assertEqual(len(model.requests), 3)
        self.assertEqual(self.reader.call_count, 2)
        self.assertEqual(state["stop_reason"], "call_limit")
        self.assertEqual(state["messages"][-2].tool_call_id, "2")
        self.assertEqual(state["messages"][-2].status, "error")
        self.assertIn("call limit", state["messages"][-1].content)

    def test_repeated_requests_stop_at_tool_call_limit(self):
        model = ScriptedModel(
            AIMessage(content="", tool_calls=[tool_call()]),
            AIMessage(content="", tool_calls=[tool_call(call_id="again")]),
        )
        state = self.run_graph(model, max_tool_calls=1)
        self.reader.assert_called_once_with()
        self.assertEqual(state["stop_reason"], "call_limit")

    def test_batch_requests_cannot_bypass_tool_limit(self):
        model = ScriptedModel(
            AIMessage(content="", tool_calls=[tool_call(call_id=str(index)) for index in range(4)]),
            AIMessage(content="Listing complete."),
        )
        self.run_graph(model, max_tool_calls=1)
        self.reader.assert_called_once_with()
        results = [message for message in model.requests[1] if isinstance(message, ToolMessage)]
        self.assertEqual(len(results), 4)
        self.assertEqual([result.status for result in results], ["success", "error", "error", "error"])

    def test_malformed_tool_call_stops_without_execution(self):
        model = ScriptedModel(AIMessage(content="", invalid_tool_calls=[{
            "name": "list_documents", "args": "{broken", "id": "bad", "error": "Invalid JSON",
        }]))
        state = self.run_graph(model)
        self.reader.assert_not_called()
        self.assertEqual(state["stop_reason"], "malformed_tool_call")

    def test_empty_model_response_is_reported_as_failure(self):
        state = self.run_graph(ScriptedModel(AIMessage(content="")))
        self.assertEqual(state["stop_reason"], "empty_response")
        self.reader.assert_not_called()

    def test_truncated_response_is_not_accepted_as_a_final_answer(self):
        model = ScriptedModel(AIMessage(
            content="You have uploaded the following", response_metadata={"done_reason": "length"}
        ))
        state = self.run_graph(model)
        self.assertEqual(state["stop_reason"], "truncated_response")
        self.reader.assert_not_called()

    def test_unparsed_thinking_is_not_accepted_as_a_final_answer(self):
        state = self.run_graph(ScriptedModel(AIMessage(content="Unparsed output</think>Hello")))
        self.assertEqual(state["stop_reason"], "unparsed_thinking")

    def test_truncated_tool_request_is_not_executed(self):
        model = ScriptedModel(AIMessage(
            content="", tool_calls=[tool_call()], response_metadata={"done_reason": "length"}
        ))
        state = self.run_graph(model)
        self.reader.assert_not_called()
        self.assertEqual(state["stop_reason"], "truncated_response")
        self.assertEqual(state["messages"][-2].tool_call_id, "request-1")

    def test_manual_exchange_rejects_truncated_answer(self):
        model = ScriptedModel(AIMessage(content="Partial", response_metadata={"done_reason": "length"}))
        with self.assertRaisesRegex(RuntimeError, "truncated_response"):
            run_manual_exchange("List documents", model, self.tool)

    def test_model_timeout_propagates_without_retry_or_tool_execution(self):
        model = ScriptedModel(TimeoutError("Model timed out"))
        with self.assertRaises(TimeoutError):
            self.run_graph(model)
        self.reader.assert_not_called()
        self.assertEqual(len(model.requests), 1)

    def test_unexpected_model_message_is_rejected(self):
        with self.assertRaises(TypeError):
            self.run_graph(ScriptedModel(HumanMessage(content="Wrong message type")))

    def test_call_limits_must_be_positive(self):
        for limits in [{"max_model_calls": 0}, {"max_tool_calls": 0}, {"max_model_calls": -1}]:
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                build_document_graph(ScriptedModel(), self.tool, **limits)

    def test_separate_invocations_do_not_share_messages_or_counters(self):
        model = ScriptedModel(AIMessage(content="First reply"), AIMessage(content="Second reply"))
        graph = build_document_graph(model, self.tool)
        for question in ["Hello", "Hi again"]:
            state = graph.invoke({"messages": [HumanMessage(content=question)]})
            self.assertEqual(state["model_calls"], 1)
            self.assertEqual(len(state["messages"]), 2)
        self.assertEqual(len(model.requests[1]), 2)  # System prompt plus current question.

    def test_manual_exchange_preserves_the_same_tool_protocol(self):
        model = ScriptedModel(
            AIMessage(content="", tool_calls=[tool_call()]), AIMessage(content="No documents.")
        )
        messages = run_manual_exchange("List my documents", model, self.tool)
        self.assertEqual(messages[-2].tool_call_id, "request-1")
        self.assertEqual(messages[-1].content, "No documents.")
        self.reader.assert_called_once_with()

    def test_manual_exchange_rejects_a_second_tool_round(self):
        model = ScriptedModel(
            AIMessage(content="", tool_calls=[tool_call()]),
            AIMessage(content="", tool_calls=[tool_call(call_id="again")]),
        )
        with self.assertRaisesRegex(RuntimeError, "one tool round"):
            run_manual_exchange("List my documents", model, self.tool)
        self.reader.assert_called_once_with()
