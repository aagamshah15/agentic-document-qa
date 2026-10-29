"""Adapt the catalog to a model-facing tool without changing catalog logic."""

from collections.abc import Callable

from langchain_core.tools import StructuredTool, ToolException
from pydantic import BaseModel, ConfigDict

from services.document_catalog import DocumentSummary, list_documents


class NoArguments(BaseModel):
    """Reject invented arguments instead of silently ignoring them."""

    model_config = ConfigDict(extra="forbid")


def make_list_documents_tool(
    catalog_reader: Callable[[], list[DocumentSummary]] = list_documents,
) -> StructuredTool:
    """Inject a reader in tests; the model never gets to choose a directory."""

    def read_catalog(**arguments) -> dict:
        # LangChain bypasses validation for empty Pydantic schemas. A JSON
        # schema plus explicit validation ensures extra arguments are rejected.
        NoArguments.model_validate(arguments)
        try:
            documents = catalog_reader()
        except OSError as error:
            # Do not pass filesystem paths or raw OS errors into model context.
            raise ToolException(
                "Document inventory could not be read due to a storage error. "
                "Whether files exist is unknown. Tell the user the listing failed."
            ) from error
        return {"status": "ok", "documents": documents}

    return StructuredTool.from_function(
        func=read_catalog,
        name="list_documents",
        description=(
            "List saved PDF filenames and byte sizes in the application's upload folder. "
            "Use for questions about available documents, document counts, or whether a "
            "named file exists. Takes no arguments. Indexing status is unknown; this "
            "does not read document contents or prove files are ready for Q&A."
        ),
        args_schema=NoArguments.model_json_schema(),
        handle_tool_error=True,
        handle_validation_error="Invalid arguments: list_documents takes no arguments. Use {}.",
    )
