import json
import unittest
from unittest.mock import Mock

from langchain_core.messages import AIMessage
from langsmith import tracing_context

from services.document_agent_runtime import execute_tool_calls
from services.document_tools import make_list_documents_tool


def tool_call(name="list_documents", args=None, call_id="request-1"):
    return {"name": name, "args": {} if args is None else args, "id": call_id, "type": "tool_call"}


class DocumentToolTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(tracing_context(enabled=False))

    def test_schema_exposes_no_arguments_and_forbids_extras(self):
        schema = make_list_documents_tool().args_schema
        self.assertEqual(schema["properties"], {})
        self.assertFalse(schema["additionalProperties"])

    def test_returns_inventory_and_preserves_tool_call_id(self):
        documents = [{"filename": "report.pdf", "size_bytes": 12, "indexing_status": "unknown"}]
        reader = Mock(return_value=documents)
        result = make_list_documents_tool(reader).invoke(tool_call())
        reader.assert_called_once_with()
        self.assertEqual(result.tool_call_id, "request-1")
        self.assertEqual(result.status, "success")
        self.assertEqual(json.loads(result.content), {"status": "ok", "documents": documents})

    def test_empty_library_is_successful(self):
        result = make_list_documents_tool(lambda: []).invoke(tool_call())
        self.assertEqual(result.status, "success")
        self.assertEqual(json.loads(result.content)["documents"], [])

    def test_model_cannot_choose_a_directory(self):
        reader = Mock(return_value=[])
        result = make_list_documents_tool(reader).invoke(tool_call(args={"upload_dir": "/tmp"}))
        self.assertEqual(result.status, "error")
        self.assertIn("takes no arguments", result.content)
        reader.assert_not_called()

    def test_storage_failure_is_error_without_private_details(self):
        for error in [PermissionError("/private/example.pdf"), OSError("disk failed at /private")]:
            with self.subTest(error=type(error).__name__):
                result = make_list_documents_tool(Mock(side_effect=error)).invoke(tool_call())
                self.assertEqual(result.status, "error")
                self.assertIn("storage error", result.content)
                self.assertIn("Whether files exist is unknown", result.content)
                self.assertNotIn("/private", result.content)

    def test_programming_errors_are_not_disguised_as_storage_failures(self):
        tool = make_list_documents_tool(Mock(side_effect=TypeError("Bug in reader")))
        with self.assertRaises(TypeError):
            tool.invoke(tool_call())

    def test_unknown_tool_is_not_executed(self):
        reader = Mock(return_value=[])
        message = AIMessage(content="", tool_calls=[tool_call(name="delete_documents")])
        results = execute_tool_calls(message, make_list_documents_tool(reader), 1)
        reader.assert_not_called()
        self.assertEqual(results[0].status, "error")
        self.assertEqual(results[0].tool_call_id, "request-1")

    def test_batch_cannot_exceed_execution_budget(self):
        reader = Mock(return_value=[])
        requests = [tool_call(call_id=f"request-{index}") for index in range(3)]
        results = execute_tool_calls(AIMessage(content="", tool_calls=requests), make_list_documents_tool(reader), 1)
        reader.assert_called_once_with()
        self.assertEqual([result.status for result in results], ["success", "error", "error"])
        self.assertEqual([result.tool_call_id for result in results], [call["id"] for call in requests])

    def test_no_budget_means_no_execution(self):
        reader = Mock(return_value=[])
        results = execute_tool_calls(AIMessage(content="", tool_calls=[tool_call()]), make_list_documents_tool(reader), 0)
        reader.assert_not_called()
        self.assertEqual(results[0].status, "error")

    def test_unknown_requests_also_consume_budget(self):
        reader = Mock(return_value=[])
        requests = [tool_call(name="unknown"), tool_call(call_id="request-2")]
        results = execute_tool_calls(AIMessage(content="", tool_calls=requests), make_list_documents_tool(reader), 1)
        reader.assert_not_called()
        self.assertEqual([result.status for result in results], ["error", "error"])
