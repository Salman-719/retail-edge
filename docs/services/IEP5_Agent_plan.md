# IEP5 — AI Agent (LLM Insights)

**Role:** LLM-powered natural-language interface. Answers manager questions by calling analytics tools, generates proactive daily/weekly reports, produces actionable suggestions, and guards against hallucination. Primary provider Anthropic Claude, with OpenAI fallback.

**Source:** `services/iep5-agent/`
**Primary port:** 8005
**Dependencies:** IEP4 (tool backend), PostgreSQL (conversation history), Redis (session state), Anthropic + OpenAI APIs

---

## Contract (what IEP5 exposes)

| Route | Purpose | Status |
|-------|---------|--------|
| `GET /health` | Liveness | DONE |
| `POST /agent/query` | Answer NL question (`AgentQuery` → `AgentResponse`) | DONE (placeholder) |
| `POST /agent/report` | Generate daily/weekly/custom report (`ReportRequest` → `ReportResponse`) | DONE (placeholder) |
| `GET /agent/suggestions/{store_id}` | Proactive insights list | DONE (returns `[]`) |
| `GET /metrics` | Prometheus | NOT STARTED |

**Schemas:** `services/iep5-agent/app/schemas.py` — `AgentQuery`, `AgentResponse`, `ReportRequest`, `ReportResponse`, `Suggestion`.

---

## Current Status

| Task | Status | Notes |
|------|--------|-------|
| FastAPI skeleton + `/health` | DONE | |
| Typed schemas | DONE | |
| Stub endpoints (placeholders) | DONE | |
| `anthropic` + `openai` deps installed | DONE | |
| `LLMClient` (dual-provider) | NOT STARTED | M6 |
| Tool definitions | NOT STARTED | M6 |
| `ToolExecutor` (→ IEP4 / DB) | NOT STARTED | M6 |
| System prompt (`prompts/`) | NOT STARTED | M6 |
| Hallucination detector | NOT STARTED | M6 |
| Multi-turn conversation manager | NOT STARTED | M6 |
| Chart generation (matplotlib → base64) | NOT STARTED | M6 |
| Proactive daily / weekly reports | NOT STARTED | M6 |
| Prompt version tracking | NOT STARTED | M6 |
| Custom Prometheus metrics | NOT STARTED | M8 |
| Prometheus scrape target | NOT STARTED | M8 |

**Overall: ~5%.**

---

## Architecture

```
                        ┌──────────────┐
                        │  LLMClient   │
   AgentQuery  ─────►   │  Claude→OAI  │
                        └─────┬────────┘
                              │ tool_use
                        ┌─────▼────────┐
                        │ ToolExecutor │───► IEP4 HTTP  ───► analytics_results
                        └─────┬────────┘          │
                              │                    └──► S3 heatmap URLs
                        ┌─────▼────────┐
                        │Hallucination │
                        │  Detector    │
                        └─────┬────────┘
                              ▼
                        AgentResponse
```

---

## Implementation Tasks

### 1. LLMClient (dual-provider)

**File:** `services/iep5-agent/app/core/llm_client.py` (NEW)

```
class LLMClient:
    primary   = "claude"
    secondary = "openai"

    async def chat(messages, tools=None, temperature=0.3) -> dict:
        try: _call_claude(...)
        except (TimeoutError, RateLimitError, APIError): _call_openai(...)
        on both failing: raise LLMUnavailableError
        returns { content, tool_calls[], provider, tokens_used }
```

Environment: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` (already wired in docker-compose).

### 2. Tool definitions

**File:** `services/iep5-agent/app/tools/definitions.py` (NEW)

```
TOOLS = [
  query_traffic_data(store_id, start, end, zone_name?, granularity)
  query_queue_history(store_id, start, end)
  query_staff_metrics(store_id, start, end)
  query_sales_data(store_id, start, end)
  query_heatmap(store_id, start, end)
  query_zone_flow(store_id, start, end)
  query_alerts(store_id, severity?, limit)
  generate_chart(chart_type, data, title)
  custom_query(store_id, query_description)
]
```

### 3. ToolExecutor

**File:** `services/iep5-agent/app/tools/executor.py` (NEW)

```
class ToolExecutor:
    def __init__(db_session, iep4_url): ...
    async def execute(name, params) -> dict:
        handler = getattr(self, f"_exec_{name}", None)
        return await handler(**params)
    async def _exec_query_traffic_data(...):
        → httpx GET {iep4_url}/analytics/{sid}/traffic
    async def _exec_generate_chart(chart_type, data, title):
        → matplotlib render → base64 PNG
```

### 4. System prompt

**File:** `prompts/retail_agent_system.md` (NEW)

- Role statement ("RetailVision AI, retail analytics advisor").
- Tool list auto-injected.
- Guidelines: always ground in tool calls, give specific zones/times/numbers, include confidence, format with headers/bullets.
- Few-shot examples (busy query, staff recommendation).

**File:** `prompts/VERSION` — active prompt version (e.g. `1.2.0`). Log per-request via Prometheus label.

Also: `prompts/daily_report_template.md`, `prompts/weekly_report_template.md`.

### 5. Hallucination detector

**File:** `services/iep5-agent/app/core/hallucination.py` (NEW)

```
class HallucinationDetector:
    def check(response, tool_results) -> {verified, unverified, confidence}
        1. regex extract numeric claims (\d+[.%]?)
        2. for each claim, fuzzy-match against tool_results values (±10% tolerance)
        3. any unmatched → unverified; confidence = verified / (verified + unverified)

    def sanitize(response, unverified) -> str
        annotate or strip unverified sentences
```

### 6. Conversation manager

**File:** `services/iep5-agent/app/core/conversation.py` (NEW)

```
class ConversationManager:
    MAX_TURNS = 20
    MAX_TOKENS = 100_000
    def add_user_message(text): ...
    def add_assistant_response(content, tool_calls): ...
    def add_tool_result(tool_id, result): ...
    def _trim(): summarise older turns into a single context message
    def get_messages() -> list for LLM
```

Persistence: Redis list `agent:conv:{store_id}:{user_id}` (TTL 1 h) or PG `conversations` table for history.

### 7. Chart generation

**File:** `services/iep5-agent/app/tools/chart_gen.py` (NEW)

```
matplotlib.use("Agg")
generate_chart(chart_type: "bar"|"line"|"pie"|"heatmap", data, title) -> base64 PNG
```

### 8. Proactive reports

**File:** `services/iep5-agent/app/reports.py` (NEW)

```
generate_daily_report(store_id)  → ReportResponse
  1. call relevant tools for yesterday
  2. LLM compose narrative, pick charts
  3. render charts
  4. assemble markdown with embedded images
  5. persist markdown + images to S3
  6. return

generate_weekly_report(store_id)  → ReportResponse
```

Scheduler (APScheduler or reuse IEP4's): daily 06:00, weekly Mon 06:00.

### 9. Wire endpoints (replace stubs)

**File:** `services/iep5-agent/app/main.py`

```
POST /agent/query:
  conv = ConversationManager(store_id)
  conv.add_user_message(q)
  while True:
    r = await llm.chat(conv.get_messages(), tools=TOOLS)
    if r.tool_calls:
        for tc in r.tool_calls:
            conv.add_tool_result(tc.id, await executor.execute(tc.name, tc.params))
    else:
        break
  check = detector.check(r.content, collected_tool_results)
  return AgentResponse(answer=sanitize(...), confidence=check.confidence, sources, charts)
```

### 10. Observability

**File:** `services/iep5-agent/app/core/metrics.py` (NEW)

```
agent_queries_total              Counter
agent_query_duration             Histogram
llm_call_duration                Histogram (provider)
llm_tokens_used                  Counter (provider, direction)
llm_fallback_total               Counter
hallucination_detected_total     Counter
tool_call_total                  Counter (tool_name)
tool_call_duration               Histogram (tool_name)
report_generation_total          Counter (type)
```

---

## Evaluation Criteria

- [ ] Agent calls tools for every numerical question
- [ ] Hallucination detector flags fabricated claims > 90 % on test set
- [ ] Simulated Claude failure → OpenAI answers
- [ ] 5+ turn conversation maintains context
- [ ] Daily report renders with narrative + ≥ 2 embedded charts
- [ ] Generated PNG charts valid base64, open in browser
- [ ] Prometheus metrics populate (latency, tokens, fallback)
- [ ] Suggestions endpoint returns grounded insights (not placeholders)

---

## Key Files

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI + endpoint wiring |
| `app/schemas.py` | Typed I/O |
| `app/core/llm_client.py` (NEW) | Dual-provider LLM wrapper |
| `app/core/conversation.py` (NEW) | Multi-turn context |
| `app/core/hallucination.py` (NEW) | Claim verification |
| `app/tools/definitions.py` (NEW) | Tool specs |
| `app/tools/executor.py` (NEW) | Tool routing → IEP4/DB |
| `app/tools/chart_gen.py` (NEW) | matplotlib PNG |
| `app/reports.py` (NEW) | Daily/weekly auto-report |
| `app/core/metrics.py` (NEW) | Prometheus |
| `prompts/*.md` (NEW) | System prompt + templates + VERSION |

---

## Re-iteration Triggers

- Responses too generic → more retail-specific few-shots
- Hallucination rate high → lower temperature, force stricter "cite tool result ID" format
- Tool calls failing → retry 1× with jitter, then surface to user
- Fallback fires often → add circuit breaker, warn via Prometheus alert
- Reports late / incomplete → split composition across multiple LLM calls (narrative, then chart selection, then summary)
