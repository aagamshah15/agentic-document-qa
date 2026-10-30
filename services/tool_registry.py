"""
Autonomous Data & Schema Studio — Formal Tool Registry & Execution Envelope.
Implements ToolSpec, ToolContext, ToolResult, strict mode/tier scoping, and sanitized errors.
"""

import time
import json
from typing import Dict, Any, List, Optional, Set, Callable, Type, Literal
from pydantic import BaseModel, Field, ValidationError


ToolRisk = Literal["metadata", "read_data", "write_shadow", "write_target"]
Tier = Literal["sandbox", "dev", "prod"]
StudioMode = Literal["explore", "ask", "change", "seed"]


class ToolResult(BaseModel):
    status: Literal["ok", "error"] = "ok"
    summary: str = Field(description="Bounded summary read by the model")
    data: Dict[str, Any] = Field(default_factory=dict, description="Structured bounded payload")
    evidence: List[Dict[str, Any]] = Field(default_factory=list, description="Evidence cards for UI (e.g. query, profile, plan)")
    warnings: List[str] = Field(default_factory=list)
    truncated: bool = False


class ToolContext:
    def __init__(
        self,
        connection_id: Optional[str] = None,
        tier: Tier = "sandbox",
        mode: StudioMode = "ask",
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        budgets: Optional[Dict[str, Any]] = None,
        app_db: Optional[Any] = None,
    ):
        self.connection_id = connection_id
        self.tier = tier
        self.mode = mode
        self.run_id = run_id
        self.session_id = session_id
        self.budgets = budgets or {"max_tool_calls": 20, "max_rows_read": 10000000}
        self.app_db = app_db
        self.tool_calls_count = 0
        self.rows_read_count = 0


class ToolSpec(BaseModel):
    name: str
    description: str
    args_model: Type[BaseModel]
    risk: ToolRisk = "metadata"
    allowed_tiers: Set[Tier] = {"sandbox", "dev", "prod"}
    modes: Set[StudioMode] = {"explore", "ask", "change", "seed"}
    handler: Any = Field(description="Callable[[ToolContext, BaseModel], ToolResult]")

    class Config:
        arbitrary_types_allowed = True


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec):
        self._tools[spec.name] = spec

    def get_tool(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def list_tools_for_mode(self, mode: StudioMode, tier: Tier) -> List[ToolSpec]:
        """Returns tools matching active mode and environment tier."""
        return [
            tool
            for tool in self._tools.values()
            if mode in tool.modes and tier in tool.allowed_tiers
        ]

    def invoke(
        self,
        tool_name: str,
        raw_args: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Executes a tool within boundary limits, mode scoping, and sanitized error envelopes."""
        start_time = time.time()
        tool = self._tools.get(tool_name)

        if not tool:
            return ToolResult(
                status="error",
                summary=f"Unknown tool '{tool_name}'. Available tools in {context.mode} mode: {', '.join([t.name for t in self.list_tools_for_mode(context.mode, context.tier)])}.",
            )

        # Check mode and tier restrictions
        if context.mode not in tool.modes:
            return ToolResult(
                status="error",
                summary=f"Tool '{tool_name}' is not permitted in '{context.mode}' mode. Please switch modes or use permitted tools.",
            )

        if context.tier not in tool.allowed_tiers:
            return ToolResult(
                status="error",
                summary=f"Tool '{tool_name}' (risk: {tool.risk}) is not allowed on connection tier '{context.tier}'.",
            )

        # Check per-run tool call budget
        max_calls = context.budgets.get("max_tool_calls", 20)
        if context.tool_calls_count >= max_calls:
            return ToolResult(
                status="error",
                summary=f"Run tool call budget exhausted ({context.tool_calls_count}/{max_calls} calls). Please increase budget or conclude task.",
            )

        context.tool_calls_count += 1

        # Validate arguments against strict Pydantic model
        try:
            validated_args = tool.args_model.model_validate(raw_args)
        except ValidationError as ve:
            errors = ve.errors()
            err_msg = "; ".join([f"{e['loc']}: {e['msg']}" for e in errors])
            return ToolResult(
                status="error",
                summary=f"Invalid arguments for tool '{tool_name}': {err_msg}",
            )

        # Execute handler
        try:
            result = tool.handler(context, validated_args)
            duration_ms = int((time.time() - start_time) * 1000)

            # Record in app DB if run_id present
            if context.app_db and context.run_id:
                try:
                    with context.app_db._get_connection() as conn:
                        conn.execute(
                            """
                            INSERT INTO tool_calls (
                                id, run_id, tool, args_json, status, result_summary,
                                rows_read, bytes_to_model, duration_ms, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'utc'));
                            """,
                            (
                                f"tc_{int(time.time()*1000)}",
                                context.run_id,
                                tool_name,
                                json.dumps(raw_args),
                                result.status,
                                result.summary[:500],
                                getattr(result, "rows_scanned", 0),
                                len(result.summary) + len(json.dumps(result.data)),
                                duration_ms,
                            ),
                        )
                        conn.commit()
                except Exception:
                    pass

            return result

        except Exception as e:
            # Sanitize error to prevent DSN or secret leakage
            sanitized = str(e)
            for redact in ("password", "secret", "token", "Bearer", "postgres://", "postgresql://"):
                if redact in sanitized:
                    sanitized = "Execution failed due to an internal driver or permissions error."
                    break

            return ToolResult(
                status="error",
                summary=f"Tool '{tool_name}' execution error: {sanitized}",
            )


# Global singleton
tool_registry = ToolRegistry()

# Register core studio tools
try:
    import services.studio_tools
except ImportError:
    pass
