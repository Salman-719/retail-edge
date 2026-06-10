"""OpenAI function-calling agent loop. Grounds answers in DB metrics; optionally
runs guarded SQL and EEP actions. Returns the final natural-language answer."""
import json
import logging

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import tools
from app.agent.eep_client import eep_action
from app.core.config import settings

log = logging.getLogger(__name__)
_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

SYSTEM_PROMPT = (
    "You are the RetailVision analytics agent. Answer questions about a retail "
    "store's footfall, dwell time, zone occupancy, and camera activity using the "
    "provided tools — never invent numbers. Always scope queries to the given "
    "store_id. Be concise and quantitative. For any action that changes state, "
    "explain what you will do and only call eep_action when the user clearly "
    "confirms."
)

TOOLS = [
    {"type": "function", "function": {
        "name": "get_metrics",
        "description": "Curated read-only analytics for a store.",
        "parameters": {"type": "object", "properties": {
            "metric": {"type": "string", "enum": ["footfall", "active_visitors",
                       "avg_dwell_seconds", "zone_breakdown", "camera_activity"]},
            "window_hours": {"type": "number", "description": "look-back window, hours"},
        }, "required": ["metric"]}}},
    {"type": "function", "function": {
        "name": "run_readonly_sql",
        "description": "Run a single read-only SELECT for ad-hoc analytics "
                       "(only if curated metrics are insufficient).",
        "parameters": {"type": "object",
                       "properties": {"sql": {"type": "string"}}, "required": ["sql"]}}},
    {"type": "function", "function": {
        "name": "eep_action",
        "description": "Perform a state-changing action via EEP (requires confirmation).",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["start_camera", "stop_camera"]},
            "args": {"type": "object"},
        }, "required": ["action"]}}},
]


async def _dispatch(name: str, args: dict, session: AsyncSession, store_id: str) -> dict:
    if name == "get_metrics":
        return await tools.get_metrics(session, args["metric"], store_id,
                                       float(args.get("window_hours", 24)))
    if name == "run_readonly_sql":
        return await tools.run_readonly_sql(session, args.get("sql", ""))
    if name == "eep_action":
        return await eep_action(args.get("action", ""), {**(args.get("args") or {}),
                                                          "store_id": store_id})
    return {"error": f"unknown tool {name}"}


async def answer(question: str, store_id: str, session: AsyncSession) -> dict:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"store_id={store_id}\n\n{question}"},
    ]
    for _ in range(settings.AGENT_MAX_TOOL_STEPS):
        resp = await _client.chat.completions.create(
            model=settings.OPENAI_MODEL, messages=messages, tools=TOOLS,
            tool_choice="auto", max_tokens=settings.OPENAI_MAX_TOKENS,
        )
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return {"answer": msg.content or ""}
        messages.append(msg.model_dump(exclude_none=True))
        for call in msg.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = await _dispatch(call.function.name, args, session, store_id)
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": json.dumps(result, default=str)})
    return {"answer": "Sorry — I couldn't complete that within the step limit.",
            "truncated": True}
