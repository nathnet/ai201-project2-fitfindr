# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Initial LLM Call

The planning loop is driven by the LLM. On each iteration, the agent calls Groq with the current message history, all tool definitions, and `tool_choice="auto"` so the LLM decides whether to call a tool or return a final response.

**System prompt:**
```
You are FitFindr, a thrift shopping assistant. You are done when you have all four of the
following ready for the user:

1. A thrift listing that matches the user's request.
2. A price assessment showing how the listing's price compares to similar items.
3. An outfit suggestion built around that listing.
4. An Instagram-style fit card caption for the outfit.

Finding the listing is only the first step — all four must be ready before the task is done.
If search returns no results, the task is complete — inform the user there is nothing to style.
If the search result includes a 'note' field, the filters were already relaxed to find the best
available match — treat the returned listing as the working item.
```

> **Note:** The prompt is goal-oriented rather than prescriptive — it defines what "done" looks like instead of dictating which tools to call and in what order. This gives the LLM room to reason about what is still missing each iteration. The "first step" line is critical: without it, the LLM tends to treat finding a listing as sufficient and exits early. The `note` field instruction tells the LLM that filter relaxation was already handled by the Python layer, preventing it from re-calling search with adjusted parameters.

**Groq call structure:**
```python
response = client.chat.completions.create(
    model=GROQ_MODEL,
    messages=messages,
    tools=TOOL_DEFINITIONS,
    tool_choice="auto",
)
```

- `messages` — starts with the system prompt and user query; assistant tool call responses and tool results are appended each iteration
- `TOOL_DEFINITIONS` — JSON schemas for all available tools (search_listings, compare_price, suggest_outfit, create_fit_card)
- `tool_choice="auto"` — LLM decides whether to call a tool or respond directly

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->
Searches the listings for thrift items matching the user's description, with optional size and price filters. Scores each listing by keyword overlap against its description and style_tags (style_tags weighted higher), drops zero-score listings, and returns results sorted by score descending.

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->

| Parameter | Type | Required | Description |
|---|---|---|---|
| `description` | str | Yes | Keywords describing the item the user is looking for (e.g. "vintage graphic tee") |
| `size` | str or None | No | Size string to filter by; case-insensitive substring match against the listing's size field. Size formats vary by category (e.g. "M" for tops, "US 8" for shoes, "W30 L30" for bottoms, "One Size" for cardigans/oversized) — partial matches may occur across categories i.e. size "8" can match shoes and bottoms. Pass None to skip. |
| `max_price` | float or None | No | Maximum price inclusive. Pass None to skip. |

**What it returns:**
<!-- Describe the return value — what fields does a result contain? -->
A ranked list of matching listing dicts sorted by keyword relevance score, each containing: id, title, description, category, style_tags, size, condition, price, colors, brand, platform. Returns an empty list if nothing matches.

**What happens if it fails or returns nothing:**
<!-- What should the agent do if no listings match? -->
If an empty list is returned, `dispatch_tool` sets `session["error"]` to "No listings found matching your description. Try broadening your search — remove the size or price filter, or use different keywords." and returns the session early without calling `suggest_outfit` or `create_fit_card`.

---

### Tool 2: suggest_outfit

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->
Given a thrifted item and the user's wardrobe, calls the LLM to suggest 1–2 complete outfit combinations. If the wardrobe is empty, returns general styling advice instead.

**System prompt (non-empty wardrobe):**
```
You are a personal stylist. Given the thrift item and the user's wardrobe below, suggest 1–2
complete outfit combinations that each include the new thrift item paired with specific named pieces
from the wardrobe. If any key categories (tops, bottoms, shoes) are missing from the wardrobe,
mention what type of piece would complete the look.
Be concise — 3–5 sentences per outfit. Plain text only — no bullet points, no headers, no markdown.
```

**System prompt (empty wardrobe):**
```
You are a personal stylist. Given the thrift item below, suggest general styling advice —
what types of pieces pair well with it based on its category, what vibe it suits,
and how to build an outfit around it.
Be concise — 3–5 sentences. Plain text only — no bullet points, no headers, no markdown.
```

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->

| Parameter | Type | Required | Description |
|---|---|---|---|
| `new_item` | dict | Yes | The selected listing dict from search_listings (the item the user is considering buying) |
| `wardrobe` | dict | Yes | The user's wardrobe dict with an `items` key containing a list of wardrobe item dicts. May be empty. |

**What it returns:**
<!-- Describe the return value -->
A non-empty string with outfit suggestions. If wardrobe is non-empty, suggestions reference specific named pieces from the wardrobe and flag any missing categories (tops, bottoms, shoes). If wardrobe is empty, returns general styling advice for the new item.

**What happens if it fails or returns nothing:**
<!-- What should the agent do if the wardrobe is empty or no outfit can be suggested? -->
If `wardrobe["items"]` is empty, the LLM is prompted for general styling advice rather than wardrobe-specific combinations — the tool always returns a non-empty string and does not stop the loop. The LLM proceeds to call `create_fit_card` with whatever string is returned.

**What if the tool gets invoked with empty selected item:**
If `new_item` is empty, raises `ValueError("suggest_outfit called with empty new_item")`. This is a
programmatic failure — the tool should never be called without a valid item. The agent guards
against this by only calling `suggest_outfit` after `search_listings` returns at least one result.

---

### Tool 3: create_fit_card

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->
Given an outfit suggestion and the thrifted item, calls the LLM to generate a short, shareable caption styled like an Instagram OOTD post.

**System prompt:**
```
You are a fashion-forward social media writer. Given the outfit suggestion and thrift item below,
pick the single most interesting outfit combination and write a 2–4 sentence Instagram caption for it.
Make it casual and authentic — like a real OOTD post, not a product description.
Mention the item name, price, and platform naturally.
Capture the outfit vibe in specific terms. Sound different each time.
Output the caption text only — no headers, no labels, no preamble.
```

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->

| Parameter | Type | Required | Description |
|---|---|---|---|
| `outfit` | str | Yes | The outfit suggestion string returned by suggest_outfit |
| `new_item` | dict | Yes | The selected listing dict (used for item name, price, and platform in the caption) |

**What it returns:**
<!-- Describe the return value -->
A 2–4 sentence string styled as a casual Instagram/TikTok caption. Mentions the item name, price, and platform once each. Returns a descriptive error string if `outfit` is empty or whitespace — does not raise an exception.

**What happens if it fails or returns nothing:**
<!-- What should the agent do if the outfit data is incomplete? -->
If `outfit` is empty or whitespace, the tool returns a descriptive error string without calling the LLM. `run_agent()` routes the result by checking the `outfit` input: if empty or whitespace, the return value goes into `session["error"]`; otherwise into `session["fit_card"]`. The session is returned early with `fit_card` as None, and `app.py` surfaces the error in panel 1 with panels 2, 3, and 4 left empty.

**Limitation:** the tool returns `str` in both success and failure paths — the assignment's required signature prevents returning `None` (the idiomatic Python failure signal). `run_agent()` must therefore check the input, not the output, to distinguish an error from a valid caption.

---

### Tool 4: compare_price

**What it does:**
Given a found listing, finds comparable items in the dataset — same category with at least one
overlapping style tag — computes price statistics across those comparables, and calls the LLM to
generate a 2–3 sentence price assessment explaining whether the item is a great deal, fair, or
above average.

**System prompt:**
```
You are a thrift shopping expert. Given a listing and price data from comparable items in the
same category, write a 2–3 sentence price assessment. State whether the price is a great deal,
fair, or above average, and explain why using the comparable prices. Be specific — reference the
average price, the price range, and the number of comparable items. If there are very few
comparables (1–2), acknowledge the limited sample. Plain text only — no bullet points, no headers,
no markdown.
```

**Input parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `item` | dict | Yes | The selected listing dict from search_listings (the item whose price is being assessed) |

**What it returns:**
A 2–3 sentence string assessing the price relative to comparables — e.g. "This jacket is priced
at $15, well below the $32.50 average for comparable vintage outerwear (range: $14–$58 across 6
items). At 54% below average, it's a strong deal." If no comparables are found, returns a short
string noting that no same-category items with matching style tags exist — does not call the LLM.

**How comparables are found:**
1. Load all listings.
2. Filter to the same `category` as the item, excluding the item itself.
3. Score each remaining listing by style_tag overlap with the item: count how many of the item's
   `style_tags` appear in the comparable's `style_tags`.
4. Drop all listings with a score of 0 (no shared tags → not stylistically comparable).
5. Compute count, average price, min price, and max price across the remaining listings.
6. Pass count, avg, min, and max to the LLM for reasoning. Count is included so the LLM can
   qualify its confidence — "based on 1 comparable" reads differently than "based on 12 comparables".

**What happens if it fails or returns nothing:**
If no comparables remain after filtering (score > 0), return `"No comparable {category} listings found to assess this price."` without calling the LLM.
The planning loop continues — a missing price assessment does not stop the agent from
proceeding to `suggest_outfit` and `create_fit_card`.

**What if the tool gets invoked with empty selected item:**
If `item` is empty, raises `ValueError("compare_price called with empty item")`. This is a
programmatic failure — the tool should never be called without a valid item. The agent guards
against this by only calling `compare_price` after `search_listings` returns at least one result.

---

## Stretch Feature: Retry Logic with Fallback

**What it does:**
If `search_listings` returns no results, the agent automatically retries with progressively looser constraints rather than immediately surfacing an error. The user is told what was adjusted so they understand why the result may differ from their original query.

**Retry order (implemented in `dispatch_tool`, search branch):**
1. Run the original search with all filters (description + size + max_price).
2. If empty and `size` was specified → append `"No results found for size {size} — size filter removed.\n"` to `session["retry_note"]`, then retry with size removed.
3. If still empty and `max_price` was specified → append `"No results found under ${max_price} — price filter removed.\n"` to `session["retry_note"]`, then retry with price removed as well.
4. If still empty after all retries → set `session["error"]` with a helpful message. Stop the loop.

**Tool result format:**
`dispatch_tool` returns a structured JSON payload instead of a raw list:
```python
payload = {"results": results[:1]}
if session["retry_note"]:
    payload["note"] = session["retry_note"].strip()
return json.dumps(payload)
```
The `note` key is included only when filters were relaxed. This lets the LLM understand why the returned item may not match the original filters (e.g. different size or price), preventing it from re-calling `search_listings` with adjusted parameters.

The system prompt reinforces this: *"If the search result includes a 'note' field, the filters were already relaxed to find the best available match — treat the returned listing as the working item."*

**State changes:**
- `session["retry_note"]` — reset to `""` at the start of each search dispatch, then appended to when a filter is dropped (before the retry call, not after). This means the note records what was attempted, regardless of whether the retry succeeded.
- `session["parsed"]` — stores the original LLM-supplied values; the relaxed values used in retries are not written back.

**What the user sees:**
`handle_query()` checks `session["retry_note"]` and prepends it to the listing panel text so the user can clearly see what filter was dropped. The LLM is not responsible for surfacing this — the UI layer handles it directly.

**No new tool or TOOL_DEFINITIONS entry needed** — this is purely a change to `dispatch_tool`'s search branch.

---

## Stretch Feature: Price Comparison Tool

**What it does:**
After a listing is found, the agent calls `compare_price` to assess whether the item's price is a good deal, fair, or above average relative to similar listings in the dataset. The result is shown in a dedicated panel in the UI.

**How comparables are found (implemented in `compare_price` in `tools.py`):**
1. Load all listings.
2. Filter to the same `category` as the item, excluding the item itself.
3. Score each by style_tag overlap — count how many of the item's `style_tags` appear in the comparable's `style_tags`. Drop zero-score listings (no shared tags → not stylistically comparable).
4. Compute count, avg, min, and max price across all remaining comparables.
5. Pass those four stats to the LLM, which generates a 2–3 sentence plain-text assessment. Count is included so the LLM can qualify its confidence ("based on 1 comparable" vs. "based on 12 comparables").

**If no comparables exist:**
Return `"No comparable {category} listings found to assess this price."` without calling the LLM. The loop continues — a missing price assessment does not stop the agent.

**If `item` is empty:**
Raises `ValueError("compare_price called with empty item")` — programmatic failure, not a user-facing case. The agent only calls `compare_price` after `search_listings` returns at least one result.

**State changes:**
- `session["price_assessment"]` — set to the LLM's assessment string by `dispatch_tool` (compare_price branch). Defaults to `""` so the UI panel renders empty if the tool is skipped.

**What the user sees:**
A dedicated price assessment panel (panel 2) in the Gradio UI showing the LLM's verdict and reasoning. The LLM is responsible for surfacing this — `app.py` renders `session["price_assessment"]` directly.

---

## Planning Loop

**How does your agent decide which tool to call next?**
<!-- Describe the logic your planning loop uses. What does it look at? What conditions change its behavior? How does it know when it's done? -->
The planning loop is LLM-driven. The first call is initialized with just the system prompt and the user's message. On each subsequent iteration, the full message history (including previous tool calls and results) is passed to the LLM with `tool_choice="auto"`.

The LLM decides which tool to call next based on the message history:
- No search result yet → calls `search_listings`
- Listing found → may call `compare_price` and `suggest_outfit` in the same response, since both
  only need `selected_item` and have no dependency on each other
- Outfit found, no fit card yet → calls `create_fit_card`
- Fit card done → returns a final response with no tool calls → loop exits

**Early exits:**
- `search_listings` returns empty results → set `session["error"]`, call no further tools, return session immediately
- `create_fit_card` receives an empty outfit string → set `session["error"]`, call no further tools, return session immediately

**Loop termination:**
The loop exits when the LLM returns a response with no `tool_calls`. If `fit_card` is still `None` at that point (the LLM gave up without completing all four steps), `session["error"]` is set to `"FitFindr couldn't complete your request. Please try again."` so the UI surfaces an error rather than rendering partial results. A max iteration guard of **5** is set (4 tools + 1 buffer for search retries). If the guard is hit, `session["error"]` is set to `"FitFindr ran into an issue and couldn't complete your request. Please try again."` and the session is returned.

**Malformed tool call handling:**
If Groq returns a `400 BadRequestError` with `code == "tool_use_failed"`, the LLM generated a malformed tool call. Retry logic is encapsulated in `_chat()` in `tools.py` — it retries the same call up to `MAX_FAILED_RETRIES = 2` times using a bounded `for` loop. Because the error fires before `messages.append(message)`, the message history is unchanged on each retry. If retries are exhausted, `_chat()` re-raises the `BadRequestError`. `run_agent` catches it at the outer level, logs the error, and sets `session["error"]` to `"FitFindr ran into an issue and couldn't complete your request. Please try again."`

---

## State Management

**How does information from one tool get passed to the next?**
<!-- Describe how your agent stores and accesses state within a session. What data is tracked? How is it passed between tool calls? -->
Each call to `run_agent()` creates a fresh session dict via `_new_session()`. The session is the single source of truth for all state within one interaction and is never shared across calls.

| Field | Set by | Used by |
|---|---|---|
| `query` | `_new_session()` | LLM initial message |
| `wardrobe` | `_new_session()` | `suggest_outfit` |
| `parsed` | `dispatch_tool` (search branch) | `search_listings` |
| `search_results` | `dispatch_tool` (search branch) | `dispatch_tool` to select `selected_item` |
| `selected_item` | `dispatch_tool` (search branch, top of results) | `suggest_outfit`, `create_fit_card` |
| `outfit_suggestion` | `dispatch_tool` (suggest branch) | `create_fit_card` |
| `price_assessment` | `dispatch_tool` (compare_price branch); defaults to `""` | `app.py` (panel 2) |
| `fit_card` | `dispatch_tool` (fit card branch) | `app.py` (panel 4) |
| `error` | `dispatch_tool` or exception handler | `app.py` — rendered in panel 1, panels 2, 3, and 4 left empty |
| `retry_note` | `dispatch_tool` (search branch) | `app.py` (prepended to panel 1 when filters were relaxed) |

Tool results are also appended to the `messages` list each iteration so the LLM can read them in the next loop. The session dict is the Python-side record used to populate the Gradio UI on return; the message history is the LLM-side record used to drive tool selection.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Set `session["error"]` to "No listings found matching your description. Try broadening your search — remove the size or price filter, or use different keywords." Stop the loop immediately. Do not call any further tools. Return the session. |
| compare_price | No same-category items with overlapping style tags | Return a fixed string `"No comparable {category} listings found to assess this price."` without calling the LLM. Store in `session["price_assessment"]`. Loop continues — a missing price assessment does not stop the agent. |
| suggest_outfit | Wardrobe is empty | Do not stop the loop. Check `wardrobe["items"]` — if empty, switch to the empty-wardrobe system prompt for general styling advice. Call the LLM and return the response string as normal. The loop continues to `create_fit_card`. |
| create_fit_card | Outfit input is missing or incomplete | The tool returns a descriptive error string without calling the LLM. `run_agent()` checks the `outfit` input after the call: if empty or whitespace, the return value is routed to `session["error"]`; otherwise to `session["fit_card"]`. Loop stops and session is returned with `fit_card` as None. |

**Malformed tool call (`tool_use_failed`):**
If Groq returns a `400 BadRequestError` with `code == "tool_use_failed"`, the LLM generated invalid function call syntax. Retry logic is encapsulated in `_chat()` in `tools.py` — it retries the same call up to `MAX_FAILED_RETRIES = 2` times using a bounded `for` loop. The error fires before any message is appended, so the message history is unchanged on each retry. If retries are exhausted, `_chat()` re-raises the `BadRequestError`. `run_agent` catches it at the outer level, logs the error, and sets `session["error"]` to `"FitFindr ran into an issue and couldn't complete your request. Please try again."`

**Incomplete session on early LLM exit:**
If the LLM returns no tool calls but `fit_card` is still `None` (the LLM gave up mid-pipeline), `session["error"]` is set to `"FitFindr couldn't complete your request. Please try again."`. This prevents `handle_query()` from attempting to render a partial session with `selected_item` or `outfit_suggestion` set but no `fit_card`.

**General exception handling:**
The entire `run_agent()` body is wrapped in a `try/except Exception` — any unhandled exception (e.g. file I/O error from `load_listings()`, Groq API failure) is caught and surfaced through `session["error"]` rather than crashing the app.

---

## Architecture

<!-- Draw a diagram of your agent showing how the components connect:
     User input → Planning Loop → Tools (search_listings, suggest_outfit, create_fit_card)
                                                                          ↕
                                                                   State / Session
     Show what triggers each tool, how state flows between them, and where error paths branch off.
     ASCII art, a Mermaid diagram (https://mermaid.js.org/syntax/flowchart.html), or an embedded
     sketch are all fine. You'll share this diagram with an AI tool when asking it to implement
     the planning loop and each individual tool. -->

```
User query + wardrobe choice
    │
    ▼
Gradio UI (handle_query)
    │ user_query, wardrobe
    ▼
Planning Loop (run_agent)
    │
    ▼
LLM Call (messages + TOOL_DEFINITIONS, tool_choice="auto") ◄─────────┐
    │                                                                │
    ├─► search_listings(description, size, max_price)                │
    │       │ sesssion["parsed"]={description, size, max_price}      │
    │       ├──────────────results=[]──────────────────────────────────────► [ERROR] set session["error"] → return early ──┐
    │       │                                                        │                                                     │
    │       │ results=[...]                                          │                                                     │
    │       ▼                                                        │                                                     │
    │   session["search_results"]=results                            │                                                     │
    │   session["selected_item"]=results[0]                          │                                                     │
    │       │ tool result appended to messages                       │                                                     │
    │       └───────────────────────────────────────────────────────►┤                                                     │
    │                                                                │                                                     │
    ├─► compare_price(selected_item)                                 │                                                     │
    │       │ filter for similar category & style listings and send  │                                                     │
    │       │ count, average, min, max price to LLM for assessment   │                                                     │
    |       | return no comparison if no comparables exist           |                                                     |
    │       ▼                                                        │                                                     │
    │   session["price_assessment"]="..."                            │                                                     │
    │       │ tool result appended to messages                       │                                                     │
    │       └───────────────────────────────────────────────────────►┤                                                     │
    │                                                                │                                                     │
    ├─► suggest_outfit(selected_item, wardrobe)                      │                                                     │
    │       │ wardrobe["items"]=[] → LLM: general styling advice     │                                                     │
    │       │ wardrobe["items"]!=[] → LLM: wardrobe-based suggestion │                                                     │
    │       ▼                                                        │                                                     │
    │   session["outfit_suggestion"]="..."                           │                                                     │
    │       │ tool result appended to messages                       │                                                     │
    │       └───────────────────────────────────────────────────────►┤                                                     │
    │                                                                │                                                     │
    ├─► create_fit_card(outfit_suggestion, selected_item)            │                                                     │
    │       │                                                        │                                                     │
    │       ├──────────────outfit empty/whitespace─────────────────────────► [ERROR] set session["error"] → return early ──┤
    │       │                                                        │                                                     │
    │       │ outfit valid                                           │                                                     │
    │       ▼                                                        │                                                     │
    │   session["fit_card"]="..."                                    │                                                     │
    │       │ tool result appended to messages                       │                                                     │
    │       │                                                        │                                                     │
    │       └───────────────────────────────────────────────────────►┘                                                     │
    │ LLM returns no tool_calls → exit loop                                                                                │
    ▼                                                                                                                      │
Return session ◄───────────────────────────────────────────────────────────────────────────────────────────────────────────┘
    │
    ├─ error set → Panel 1: error msg  | Panel 2: empty          | Panel 3: empty  | Panel 4: empty
    └─ success  → Panel 1: listing     | Panel 2: price assess   | Panel 3: outfit | Panel 4: fit card
```

---

## AI Tool Plan

<!-- For each part of the implementation below, describe:
     - Which AI tool you plan to use (Claude, Copilot, ChatGPT, etc.)
     - What you'll give it as input (which sections of this planning.md, your agent diagram)
     - What you expect it to produce
     - How you'll verify the output matches your spec before moving on

     "I'll use AI to help me code" is not a plan.
     "I'll give Claude my Tool 1 spec (inputs, return value, failure mode) and ask it to implement
     search_listings() using load_listings() from the data loader — then test it against 3 queries
     before trusting it" is a plan. -->

**Milestone 3 — Individual tool implementations:**

- **search_listings:** Give Claude Code the Tool 1 section (What it does, input table, return value, failure mode) and ask it to implement using `load_listings()`. Verify the generated code filters by all three parameters, weights style_tags higher than description, drops zero-score listings, and sorts descending. Test with direct function calls covering: (1) description only, (2) description + max_price only, (3) description + size only, (4) all three params, (5) a query that should return empty.
- **suggest_outfit:** Give Claude Code the Tool 2 section plus both system prompts. Verify the code branches on `wardrobe["items"]` being empty, calls the LLM with the correct prompt for each branch, and always returns a non-empty string. Test with direct function calls covering: (1) a valid item with example wardrobe, (2) a valid item with empty wardrobe.
- **create_fit_card:** Give Claude Code the Tool 3 section plus its system prompt. Verify the empty/whitespace outfit guard is present, the LLM call uses higher temperature, and the output mentions item name, price, and platform. Test with direct function calls covering: (1) a valid outfit string, (2) an empty string, (3) a whitespace-only string.

**Milestone 4 — Planning loop and state management:**

- **TOOL_DEFINITIONS:** Give Claude Code the input parameter tables for all four tools from the Tools section. Ask it to produce the Groq-compatible JSON schema definitions for each tool. Verify each definition matches the parameter names, types, and required fields in the spec.
- **run_agent() loop:** Give Claude Code the Initial LLM Call section, Planning Loop section, State Management section, and the Architecture diagram. Ask it to implement the LLM-driven loop with Groq tool calling. Verify: message history is appended correctly each iteration, early exit on empty search results sets `session["error"]` and returns without calling remaining tools, and the max iteration guard is present. Test using the two CLI cases already in `agent.py` — happy path and no-results path.
- **handle_query():** Give Claude Code the `app.py` TODO comments and the State Management section. Ask it to implement `handle_query()`. Verify: empty query is caught early, wardrobe is selected correctly based on `wardrobe_choice`, `session["error"]` routes to panel 1 with panels 2, 3, and 4 empty, and success routes all four fields to the correct panels. Test by running `app.py` and submitting both a valid query and the deliberate no-results example query.

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1:**
<!-- What does the agent do first? Which tool is called? With what input? -->
After reading user query, the agent capture the requirements of the item the user is looking for.
The captured requirements are "vintage graphic tee", "<=$30", missing size.  

The LLM then looks at the information it needs and calls tool to search for listings user can buy.
Agent calls search_listings(description="vintage graphic tee", max_price=30.0).
The tool returns a ranked list of listing dicts sorted by keyword relevance score. The tool result
is appended to messages and session["search_results"] is set to the returned list.
session["selected_item"] is set to results[0] — e.g. {title: "Vintage Graphic Tee", price: 24.0, platform: "Depop", ...}.

**Step 2:**
<!-- What happens next? What was returned from step 1? What tool is called now? -->
The LLM receives the search result.
a.) If the result is non-empty, it recognizes that price assessment and outfit suggestion are both
still missing, and may call `compare_price` and `suggest_outfit` in the same response
(parallel tool calls) since both only need `selected_item`.
`compare_price` result is stored in `session["price_assessment"]`.
`suggest_outfit` result is stored in `session["outfit_suggestion"]`.
b.) If the result is empty, the LLM stops calling tools and informs the user there is nothing to style.

**Step 3:**
<!-- Continue until the full interaction is complete -->
If the suggest_outfit() is made, the LLM receives back a string for the outfit suggestion.
a.) In the case where there is enough clothes in the wardrobe, the suggestion is based on
the existing wardrobe.
b.) If the wardrobe is minimal/does not have enough clothes for a full outfit (tops, bottoms, shoes), 
LLM suggests based on the wardrobe and offers a general styling for the missing item. 
This case is part of the non-empty wardrobe prompt.
c.) If the wardrobe is empty, LLM offers a general styling advice for the new item.

The outfit suggestion string is stored in session["outfit_suggestion"] and the tool result is 
appended to messages. The LLM then calls create_fit_card(outfit_suggestion, selected_item),
passing the full suggestion string and the selected listing dict.
The tool returns a 2-4 sentence Instagram-style caption — e.g. "Thrifted this faded graphic tee 
on Depop for $24 and I'm obsessed. Styled it with my baggy jeans and chunky sneakers for the 
ultimate 90s throwback look. This one's staying in rotation."
The caption is stored in session["fit_card"].

**Final output to user:**
<!-- What does the user actually see at the end? -->
4 things: 1. top listing match, 2. price assessment, 3. outfit idea, and 4. a fit card caption
for their instagram post