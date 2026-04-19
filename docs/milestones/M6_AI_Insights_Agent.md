# Milestone 6: AI Insights Agent

**Duration:** 1.5 weeks
**Dependencies:** M5
**Goal:** Functional LLM-based agent with tool use, conversational queries, proactive reports, and dual-provider fallback.

---

## Current Status

| Task | Status | Notes |
|------|--------|-------|
| IEP5 stub endpoints | DONE | query, report, suggestions endpoints |
| IEP5 schemas | DONE | AgentQuery, AgentResponse, ReportRequest, etc. |
| anthropic + openai deps installed | DONE | In requirements.txt |
| LLM client module | NOT STARTED | |
| Agent tools (DB queries) | NOT STARTED | |
| Tool execution engine | NOT STARTED | |
| System prompt design | NOT STARTED | /prompts/ dir empty |
| Hallucination detection | NOT STARTED | |
| Multi-turn conversation | NOT STARTED | |
| Chart generation | NOT STARTED | |
| Proactive reports | NOT STARTED | |
| Dual-provider fallback | NOT STARTED | |

**Overall: ~5% complete**

---

## Implementation Tasks

### 1. LLM Client Module

**File:** `services/iep5-agent/app/core/llm_client.py` (NEW)

```python
class LLMClient:
    """Abstract LLM interface with dual-provider fallback."""

    def __init__(self):
        self.primary = "claude"      # Anthropic Claude
        self.secondary = "openai"    # OpenAI GPT-4

    async def chat(self, messages, tools=None, temperature=0.3) -> dict:
        """Send chat request with automatic fallback.

        1. Try primary provider (Claude)
        2. If fails (timeout, rate limit, error): log, try secondary (OpenAI)
        3. If both fail: raise LLMUnavailableError
        4. Log which provider served each request (Prometheus metric)

        Returns: {
            "content": str,
            "tool_calls": list[dict],  # if tools invoked
            "provider": "claude" | "openai",
            "tokens_used": int
        }
        """

    async def _call_claude(self, messages, tools, temperature):
        """Anthropic API call with tool_use support."""

    async def _call_openai(self, messages, tools, temperature):
        """OpenAI API call with function_calling support."""
```

**Config:** `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` from environment (already in docker-compose).

### 2. Agent Tools Definition

**File:** `services/iep5-agent/app/tools/definitions.py` (NEW)

```python
TOOLS = [
    {
        "name": "query_traffic_data",
        "description": "Get visitor traffic data for a store within a time range",
        "parameters": {
            "store_id": str, "start": datetime, "end": datetime,
            "zone_name": Optional[str], "granularity": str
        }
    },
    {
        "name": "query_queue_history",
        "description": "Get queue length and wait time history for checkout zones",
        "parameters": {"store_id": str, "start": datetime, "end": datetime}
    },
    {
        "name": "query_staff_metrics",
        "description": "Get staff coverage and presence data",
        "parameters": {"store_id": str, "start": datetime, "end": datetime}
    },
    {
        "name": "query_sales_data",
        "description": "Get POS sales data and conversion metrics",
        "parameters": {"store_id": str, "start": datetime, "end": datetime}
    },
    {
        "name": "query_heatmap",
        "description": "Get or generate a traffic heatmap for a time period",
        "parameters": {"store_id": str, "start": datetime, "end": datetime}
    },
    {
        "name": "query_zone_flow",
        "description": "Get zone-to-zone customer flow analysis",
        "parameters": {"store_id": str, "start": datetime, "end": datetime}
    },
    {
        "name": "query_alerts",
        "description": "Get recent alerts for a store",
        "parameters": {"store_id": str, "severity": Optional[str], "limit": int}
    },
    {
        "name": "generate_chart",
        "description": "Generate a chart from data",
        "parameters": {"chart_type": str, "data": dict, "title": str}
    },
    {
        "name": "custom_query",
        "description": "Execute a custom analytical query on store data",
        "parameters": {"store_id": str, "query_description": str}
    }
]
```

### 3. Tool Execution Engine

**File:** `services/iep5-agent/app/tools/executor.py` (NEW)

```python
class ToolExecutor:
    """Execute tool calls by querying IEP4 / DB / S3."""

    def __init__(self, db_session, iep4_url):
        self.db = db_session
        self.iep4 = iep4_url

    async def execute(self, tool_name: str, params: dict) -> dict:
        """Route tool call to appropriate handler."""
        handler = getattr(self, f"_exec_{tool_name}", None)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}
        return await handler(**params)

    async def _exec_query_traffic_data(self, store_id, start, end, **kw):
        """Call IEP4 GET /analytics/{store_id}/traffic"""
        resp = await httpx.AsyncClient().get(f"{self.iep4}/analytics/{store_id}/traffic", params=...)
        return resp.json()

    async def _exec_generate_chart(self, chart_type, data, title):
        """Render chart server-side with matplotlib, return base64 PNG."""
        ...
```

### 4. System Prompt

**File:** `prompts/retail_agent_system.md` (NEW)

```markdown
You are RetailVision AI, a retail analytics advisor for store managers.

Role: Analyze in-store customer behavior data and provide actionable recommendations.

Available tools: [auto-injected from tool definitions]

Guidelines:
- Always ground answers in actual data from tool calls
- When asked about numbers, ALWAYS call the relevant query tool first
- Provide specific, actionable recommendations, not generic advice
- Reference specific zones, times, and metrics
- If data is insufficient, say so clearly
- Format responses with clear headers and bullet points
- Include confidence level when making predictions

Few-shot examples:
Q: "How busy was the electronics zone yesterday?"
A: [calls query_traffic_data] Based on yesterday's data, the Electronics zone had 234 visitors...

Q: "Should I add more staff to checkout?"
A: [calls query_queue_history + query_staff_metrics] Looking at the last week...
```

### 5. Hallucination Detection

**File:** `services/iep5-agent/app/core/hallucination.py` (NEW)

```python
class HallucinationDetector:
    """Post-process LLM output to catch fabricated claims."""

    def check(self, response: str, tool_results: list[dict]) -> dict:
        """
        1. Extract numerical claims from response (regex: numbers + units)
        2. Cross-reference each claim against tool_results data
        3. Flag claims that don't match any tool result (tolerance: +/-10%)
        4. Return {verified_claims: [], unverified_claims: [], confidence: float}
        """

    def sanitize(self, response: str, unverified: list) -> str:
        """Strip or annotate unverified claims."""
```

### 6. Multi-Turn Conversation

**File:** `services/iep5-agent/app/core/conversation.py` (NEW)

```python
class ConversationManager:
    """Manage multi-turn chat with sliding window context."""

    MAX_TURNS = 20
    MAX_TOKENS = 100_000  # context budget

    def __init__(self, store_id: str):
        self.store_id = store_id
        self.messages = []  # list of {role, content, tool_calls?, tool_results?}

    def add_user_message(self, text: str):
        self.messages.append({"role": "user", "content": text})
        self._trim()

    def add_assistant_response(self, content: str, tool_calls=None):
        ...

    def _trim(self):
        """If approaching token limit, summarize older turns."""
        # Keep system prompt + last N turns
        # Summarize older turns into a single context message

    def get_messages(self) -> list:
        """Return messages formatted for LLM API."""
```

**Persistence:** Store conversations in Redis with TTL (1 hour) or PostgreSQL for history.

### 7. Chart Generation

**File:** `services/iep5-agent/app/tools/chart_gen.py` (NEW)

```python
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io, base64

def generate_chart(chart_type, data, title) -> str:
    """Render chart and return base64 PNG.

    Supported types:
    - "bar": bar chart
    - "line": time series line chart
    - "pie": distribution pie chart
    - "heatmap": grid heatmap

    Returns: base64-encoded PNG string
    """
```

### 8. Proactive Report Generation

**File:** `services/iep5-agent/app/reports.py` (NEW)

```python
async def generate_daily_report(store_id: str) -> ReportResponse:
    """Auto-generated daily summary report.

    Process:
    1. Call all relevant tools for yesterday's data
    2. Compose prompt: "Generate a daily store report with these data..."
    3. LLM generates narrative + selects charts to create
    4. Render charts
    5. Assemble markdown report with embedded chart images
    6. Store in S3
    7. Return ReportResponse
    """

async def generate_weekly_report(store_id: str) -> ReportResponse:
    """Weekly trend analysis report."""

# Schedule via APScheduler (daily at 6 AM, weekly on Monday)
```

### 9. Wire Up IEP5 Endpoints

**File:** `services/iep5-agent/app/main.py`

Replace stubs:
```python
@app.post("/agent/query")
async def query(payload: AgentQuery):
    conv = ConversationManager(payload.store_id)
    conv.add_user_message(payload.question)

    llm = LLMClient()
    executor = ToolExecutor(db, settings.IEP4_URL)

    # Agent loop: LLM may call tools multiple times
    while True:
        response = await llm.chat(conv.get_messages(), tools=TOOLS)
        if response["tool_calls"]:
            for tc in response["tool_calls"]:
                result = await executor.execute(tc["name"], tc["params"])
                conv.add_tool_result(tc["id"], result)
        else:
            break

    # Hallucination check
    detector = HallucinationDetector()
    check = detector.check(response["content"], tool_results)

    return AgentResponse(
        answer=response["content"],
        confidence=check["confidence"],
        sources=[...],
        charts=[...]
    )
```

### 10. Prompt Version Tracking

**Directory:** `prompts/`

```
prompts/
  retail_agent_system.md       -- main system prompt
  daily_report_template.md     -- daily report generation prompt
  weekly_report_template.md    -- weekly report prompt
  VERSION                      -- current active version (e.g., "1.2.0")
```

Log active prompt version per request in Prometheus label.

---

## Evaluation Criteria (must pass before M7)

- [ ] Agent correctly answers data-grounded questions by calling tools
- [ ] Agent generates actionable recommendations (not just raw data)
- [ ] Hallucination detection catches fabricated numbers >90% of test cases
- [ ] Dual-provider fallback: simulate Claude failure, verify OpenAI responds
- [ ] Multi-turn conversation maintains context over 5+ turns
- [ ] Proactive daily report generates with charts and narrative
- [ ] Chart generation produces valid PNG images
- [ ] All tests pass

## Re-iteration Triggers

- If responses too generic: add more retail-specific examples in system prompt
- If hallucination rate high: lower temperature, add stricter output format
- If tool calls fail: check IEP4 endpoint availability, add retry logic
