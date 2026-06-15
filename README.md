# FitFindr

A multi-tool thrift shopping AI agent. Give it a natural language query and it finds matching secondhand listings, assesses the price against comparable items, suggests outfits using your wardrobe, and generates a shareable Instagram caption — all in one interaction.

Built with Groq, orchestrated by an LLM-driven planning loop, and served through a Gradio UI.

## Demo

<!-- Add demo video link or GIF here -->

---

## Running FitFindr

Run the Gradio UI:

```bash
python app.py
```

Run the CLI test (happy path + no-results path):

```bash
python agent.py
```

Run the test suite:

```bash
pytest tests/
```

---

## Initial LLM Call

Every iteration of the planning loop calls Groq with the same structure:

```python
response = client.chat.completions.create(
    model=GROQ_MODEL,
    messages=messages,
    tools=TOOL_DEFINITIONS,
    tool_choice="auto",
)
```

- `messages` — starts with the system prompt and user query; assistant tool call messages and tool results are appended each iteration so the LLM has the full history
- `TOOL_DEFINITIONS` — JSON schemas for all four tools (`search_listings`, `compare_price`, `suggest_outfit`, `create_fit_card`) describing their parameters and when to use them
- `tool_choice="auto"` — the LLM decides whether to call a tool or return a final text response

The system prompt defines the exit condition rather than a fixed sequence:

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

---

## Tool Inventory

### Tool 1: `search_listings`

**Purpose:** Searches the mock thrift dataset for items matching the user's description, with optional size and price filters. Scores each listing by keyword overlap against its `description` field (weight 1×) and `style_tags` (weight 2×), drops zero-score listings, and returns results sorted by score descending.

**Input parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `description` | `str` | Yes | Keywords describing the item (e.g. `"vintage graphic tee"`) |
| `size` | `str \| None` | No | Size string to filter by; case-insensitive substring match. Formats: letter sizes for tops (`"S"`, `"M"`, `"L/XL"`), waist/length for bottoms (`"W30"`, `"W30 L30"`), US sizing for shoes (`"US 8"`). Pass `None` to skip. |
| `max_price` | `float \| None` | No | Maximum price inclusive. Pass `None` to skip. |

**Returns:** `list[dict]` — a ranked list of matching listing dicts sorted by keyword relevance score. Returns an empty list if nothing matches — does not raise an exception for zero results.

Each dict contains:

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Unique listing identifier |
| `title` | `str` | Listing title |
| `description` | `str` | Full item description |
| `category` | `str` | Item category (e.g. `"tops"`, `"bottoms"`, `"shoes"`) |
| `style_tags` | `list[str]` | Style keywords (e.g. `["vintage", "graphic tee"]`) |
| `size` | `str` | Size string (format varies by category) |
| `condition` | `str` | Item condition (e.g. `"excellent"`, `"good"`) |
| `price` | `float` | Listing price |
| `colors` | `list[str]` | Color(s) of the item |
| `brand` | `str \| None` | Brand name, or `None` if unbranded |
| `platform` | `str` | Resale platform (e.g. `"depop"`, `"poshmark"`) |

**What happens if it returns nothing:** `dispatch_tool` sets `session["error"]` to `"No listings found matching your description. Try broadening your search — remove the size or price filter, or use different keywords."` and the loop exits immediately — `compare_price`, `suggest_outfit`, and `create_fit_card` are never called.

---

### Tool 2: `suggest_outfit`

**Purpose:** Given a thrifted item and the user's wardrobe, calls the LLM to suggest 1–2 complete outfit combinations. If the wardrobe is empty, returns general styling advice instead.

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

| Parameter | Type | Required | Description |
|---|---|---|---|
| `new_item` | `dict` | Yes | A listing dict from `search_listings` — the item the user is considering |
| `wardrobe` | `dict` | Yes | A wardrobe dict with an `"items"` key containing a list of wardrobe item dicts. May be empty. |

**Returns:** `str` — a non-empty outfit suggestion. If `wardrobe["items"]` is non-empty, suggestions reference specific named pieces from the wardrobe and flag any missing key categories (tops, bottoms, shoes). If the wardrobe is empty, returns general styling advice for the item type and vibe.

**What happens if it returns nothing:** An empty wardrobe is not a failure — the tool switches to a general styling prompt and always returns a non-empty string. The loop continues to `create_fit_card`.

**What happens if `new_item` is empty:** Raises `ValueError("suggest_outfit called with empty new_item")`. This is intentional — calling `suggest_outfit` without a valid item is a programmatic error, not a user-facing case. The agent guards against this by only calling `suggest_outfit` after `search_listings` returns at least one result.

---

### Tool 3: `create_fit_card`

**Purpose:** Given an outfit suggestion and the thrifted item, calls the LLM to generate a 2–4 sentence Instagram-style OOTD caption that mentions the item name, price, and platform naturally.

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

| Parameter | Type | Required | Description |
|---|---|---|---|
| `outfit` | `str` | Yes | The outfit suggestion string returned by `suggest_outfit` |
| `new_item` | `dict` | Yes | The selected listing dict (for item name, price, and platform in the caption) |

**Returns:** `str` — a casual 2–4 sentence Instagram caption. Does not raise an exception.

**What happens if it returns nothing:** If `outfit` is empty or whitespace, the tool returns `"Something went wrong generating your fit card. Please try your search again."` without calling the LLM. `dispatch_tool` checks the `outfit` input and routes that string to `session["error"]`, and the loop exits with `fit_card` as `None`.

**Course limitation:** The required function signature is `-> str`, which means both success and failure must return a string. The idiomatic Python approach would be to return `None` on failure and let the caller check. Instead, `dispatch_tool` checks the *input* (`outfit`) rather than the output to distinguish an error from a valid caption, and routes accordingly.

### Tool 4: `compare_price`

**Purpose:** Given a selected listing, finds comparable items in the dataset — same category with at least one overlapping style tag — and calls the LLM to generate a 2–3 sentence price assessment based on price statistics across those comparables.

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
| `item` | `dict` | Yes | The selected listing dict from `search_listings` |

**How comparables are found:**
1. Filter all listings to the same `category` as the item, excluding the item itself.
2. Score each by style_tag overlap — count how many of the item's `style_tags` appear in the comparable's `style_tags`.
3. Drop listings with a score of 0 (no shared tags → not stylistically comparable).
4. Compute count, average price, min price, and max price across all remaining comparables.

**Returns:** `str` — a 2–3 sentence price assessment. If no comparables are found, returns `"No comparable {category} listings found to assess this price."` without calling the LLM.

**What happens if no comparables exist:** Returns a fixed no-comparables string without calling the LLM. Stored in `session["price_assessment"]` (defaults to `""`). The loop continues — a missing price assessment does not stop the agent.

**What happens if `item` is empty:** Raises `ValueError("compare_price called with empty item")`. This is intentional — calling `compare_price` without a valid item is a programmatic error, not a user-facing case. The agent guards against this by only calling `compare_price` after `search_listings` returns at least one result.

---

## Planning Loop

The loop is LLM-driven — not a fixed sequential pipeline. On each iteration, the full message history (system prompt, user query, all previous tool calls and results) is sent to Groq with `tool_choice="auto"`, and the LLM decides what to do next.

**Conditional logic:**

| LLM observes in message history | Decision |
|---|---|
| No search has been run yet | Call `search_listings` with parsed parameters |
| Listing found, no price assessment or outfit yet | May call `compare_price` and `suggest_outfit` in the same response — both only need `selected_item` |
| Outfit found, no fit card yet | Call `create_fit_card` |
| All four outputs ready | Return a final response — no tool calls, loop exits |

The system prompt defines the exit condition rather than the sequence: the LLM is told it is done only when all four outputs (listing, price assessment, outfit, fit card) are ready. This lets the model reason about what is still missing on each iteration rather than following fixed steps.

**Early exits (Python-side, not LLM-driven):**

| Condition | Action |
|---|---|
| `search_listings` returns empty list | `session["error"]` is set, loop returns immediately — LLM is not called again |
| `outfit` is empty/whitespace when `create_fit_card` is called | `session["error"]` is set, loop returns immediately |

**Loop termination:** exits when the LLM returns a response with no `tool_calls`. If `fit_card` is still `None` at that point, `session["error"]` is set to `"FitFindr couldn't complete your request. Please try again."` so the UI surfaces an error rather than rendering a partial result. A hard limit of 5 iterations guards against runaway loops — if hit, `session["error"]` is set to `"FitFindr ran into an issue and couldn't complete your request. Please try again."` and the session is returned.

**Malformed tool call retry:** if Groq returns a `400 BadRequestError` with `code == "tool_use_failed"`, the LLM generated invalid function call syntax. Retry logic is encapsulated in `_chat()` in `tools.py` — it retries the same call up to `MAX_FAILED_RETRIES = 2` times using a bounded `for` loop. Because the error fires before `messages.append(message)`, the message history is unchanged on each retry. If retries are exhausted, `_chat()` re-raises the `BadRequestError`. `run_agent` catches it at the outer level, logs the error, and sets `session["error"]` to `"FitFindr ran into an issue and couldn't complete your request. Please try again."`

---

## State Management

Each `run_agent()` call creates a fresh session dict via `_new_session()`. The session is the single source of truth for all Python-side state within one interaction and is never shared across calls.

| Field | Set by | Used by |
|---|---|---|
| `query` | `_new_session()` | Initial LLM message |
| `wardrobe` | `_new_session()` | `suggest_outfit` via `dispatch_tool` |
| `parsed` | `dispatch_tool` (search branch) | `search_listings` |
| `search_results` | `dispatch_tool` (search branch) | `dispatch_tool` to select `selected_item` |
| `selected_item` | `dispatch_tool` (search branch) | `suggest_outfit`, `create_fit_card` via `dispatch_tool` |
| `outfit_suggestion` | `dispatch_tool` (suggest branch) | `create_fit_card` via `dispatch_tool` |
| `price_assessment` | `dispatch_tool` (compare_price branch); defaults to `""` | `app.py` — rendered in panel 2 |
| `fit_card` | `dispatch_tool` (fit card branch) | `app.py` — rendered in panel 4 |
| `error` | `dispatch_tool` or exception handler | `app.py` — rendered in panel 1, panels 2, 3, and 4 left empty |
| `retry_note` | `dispatch_tool` (search branch) | `app.py` — prepended to panel 1 when filters were relaxed |

**Key design:** `dispatch_tool()` reads from and writes to the session directly — tool functions receive only what they need as function arguments, while state like `session["selected_item"]` and `session["wardrobe"]` is carried invisibly between steps. The user never re-enters data between tools.

Tool results are also appended to `messages` each iteration so the LLM can read them and reason about what to do next. The session dict is the Python-side record used to populate the UI; `messages` is the LLM-side record used to drive tool selection.

---

## Error Handling

| Tool | Failure mode | Agent response |
|---|---|---|
| `search_listings` | Returns empty list after all retries (description only, no filters left) | `dispatch_tool` sets `session["error"]` to `"No listings found matching your description. Try broadening your search — remove the size or price filter, or use different keywords."` Loop exits immediately. No further tools are called. |
| `compare_price` | No same-category listings share any style tags with the item | Returns `"No comparable {category} listings found to assess this price."` without calling the LLM. Stored in `session["price_assessment"]`. Loop continues — a missing price assessment does not stop the agent. |
| `suggest_outfit` | `wardrobe["items"]` is empty | Not treated as a failure — the tool switches to a general styling prompt and returns advice as normal. The loop continues to `create_fit_card`. |
| `create_fit_card` | `outfit` argument is empty or whitespace | The tool returns a descriptive error string without calling the LLM. `dispatch_tool` checks the `outfit` input: if empty/whitespace, routes the return value to `session["error"]`; otherwise to `session["fit_card"]`. |
| LLM — any iteration | `400 BadRequestError` with `code == "tool_use_failed"` (malformed tool call syntax) | `_chat()` retries the call up to `MAX_FAILED_RETRIES = 2` times (message history unchanged since error fires before append). On exhaustion, re-raises `BadRequestError`. `run_agent` catches it, logs the error, and sets `session["error"]` to `"FitFindr ran into an issue and couldn't complete your request. Please try again."` |
| LLM — no tool calls | LLM exits loop before `fit_card` is set (gave up mid-pipeline) | `session["error"]` is set to `"FitFindr couldn't complete your request. Please try again."` Prevents `handle_query()` from rendering a partial session. |
| Any tool / LLM call | Unhandled exception (e.g. API failure, I/O error) | The entire `run_agent()` body is wrapped in `try/except Exception` — any uncaught exception sets `session["error"]` to `"FitFindr ran into an unexpected error. Please try again."` rather than crashing the app. |

**Concrete failure example tested:** Querying `"designer ballgown size XXS under $5"` against the 40-listing dataset returns zero results from `search_listings`. The agent sets `session["error"]` and returns immediately. The Gradio UI shows the error message in panel 1 with panels 2, 3, and 4 empty, rather than proceeding to suggest an outfit for a nonexistent item.

---

## Architecture

The diagram below shows data and control flow through the agent. The left branch traces the happy path — all three tools called in sequence, session populated, results rendered in the UI. The right branch shows the two early exit points where the Python loop returns before the LLM is called again. The session dict runs as a parallel track alongside the LLM message history — the session holds Python-side state for the UI; the messages hold LLM-side state for tool selection.

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

## Stretch Feature: Retry Logic with Fallback

If `search_listings` returns no results, `dispatch_tool` automatically retries with progressively looser filters before surfacing an error:

1. Run the original search with all filters (description + size + max_price).
2. If empty and `size` was specified → append `"No results found for size {size} — size filter removed.\n"` to `session["retry_note"]`, then retry with size removed.
3. If still empty and `max_price` was specified → append `"No results found under ${max_price} — price filter removed.\n"` to `session["retry_note"]`, then retry with price removed as well.
4. If still empty after all retries → set `session["error"]` to `"No listings found matching your description. Try broadening your search — remove the size or price filter, or use different keywords."` and stop the loop.

**Tool result format:** `dispatch_tool` returns a structured JSON payload rather than a raw list so the LLM understands why the returned item may not match the original filters:

```python
payload = {"results": results[:1]}
if session["retry_note"]:
    payload["note"] = session["retry_note"].strip()
return json.dumps(payload)
```

The `note` key is present only when filters were relaxed. The system prompt instructs the LLM: *"If the search result includes a 'note' field, the filters were already relaxed to find the best available match — treat the returned listing as the working item."* This prevents the LLM from re-calling `search_listings` with adjusted parameters.

**What the user sees:** `handle_query()` checks `session["retry_note"]` and prepends it to the listing panel so the user knows which filters were dropped. The LLM is not responsible for surfacing this — the UI layer handles it directly.

**Sample result** (query: `"vintage graphic tee size XXS under $5"`):
```
No results found for size XXS — size filter removed.
No results found under $5.00 — price filter removed.

Graphic Tee — 2003 Tour Bootleg Style

Platform: depop
Price: $24.00
Size: L
Condition: good
Brand: Unknown
Colors: black
Style: graphic tee, vintage, grunge, streetwear, band tee

Vintage-style bootleg tee with faded graphic. Slightly boxy fit. 100% cotton, soft and worn-in.
```

---

## Stretch Feature: Price Comparison Tool

`compare_price` compares a found listing's price against similar items in the dataset and returns a 2–3 sentence LLM-generated assessment. It is called by the agent as part of the standard planning loop — the system prompt lists a price assessment as one of the four required outputs before the task is considered done.

**How comparisons are made:**
1. Filter all listings to the same category as the found item, excluding the item itself.
2. Score remaining listings by style_tag overlap — count how many of the item's `style_tags` appear in each comparable's `style_tags`. Drop zero-score listings (no shared tags → not stylistically comparable).
3. Compute count, average price, min price, and max price across all remaining comparables.
4. Pass those stats to the LLM, which generates a plain-text assessment referencing the average, range, and count. If count is very low (1–2), the LLM is instructed to acknowledge the limited sample.

If no comparables are found after filtering, a fixed no-comparables string is returned without calling the LLM. `session["price_assessment"]` defaults to `""` so the UI panel renders empty rather than erroring if the tool is not called.

**Sample result:**
```
At $24.00, this graphic tee is priced above the comparable average of $20.42 but still falls
within the typical range of $15.00 to $28.00 for similar tops. While it isn't a great deal,
the price is fair given its placement near the higher end of the market spectrum.
```

---

## Spec Reflection

**One way the spec helped:**

Writing the State Management table in `planning.md` before implementing the loop forced a clear answer to "how does the item from `search_listings` get into `suggest_outfit` without the user re-entering it?" The answer — a `session` dict managed by `dispatch_tool()`, distinct from the LLM message history — emerged directly from speccing out the state flow. Without that table, it would have been easy to accidentally pass data through the LLM messages instead, which would be fragile and token-heavy.

**One divergence and why:**

`planning.md` originally described the system prompt as a prescriptive step-by-step sequence ("call tools in order, only call suggest_outfit and create_fit_card if a listing was found"). During testing, the LLM would stop after `search_listings` returned results and not continue to the next tools — treating "found a listing" as task-complete. The prompt was revised to a goal-oriented exit condition ("you are done only when all three outputs are ready"), which lets the model reason about what is still missing each iteration rather than mechanically following steps. This better matches the course's intent of LLM-driven planning.

---

## AI Usage Transparency

**Instance 1 — Implementing the three tools:**

Directed Claude Code to implement each tool from its respective spec in `planning.md`. Key reviews and overrides across all three:

- `search_listings`: confirmed filters are applied before scoring so irrelevant listings don't accumulate score, style_tags are joined into a single string before tokenizing, and `score == 0` listings are dropped before sorting. Revised the test case for `test_search_price_filter` after the first generated version used a query/price combination that returned zero results against the actual dataset.
- `suggest_outfit`: confirmed the empty-wardrobe branch checks `wardrobe["items"]` rather than the wardrobe dict itself. Overrode the initial error-string return for an empty `new_item` with a `ValueError` raise — an empty item is a programmatic failure that should never reach this function, not a user-facing case to handle gracefully.
- `create_fit_card`: confirmed the guard uses `outfit.strip()` rather than just `not outfit`, covering whitespace-only strings. Accepted the error-string return on failure (instead of `None`) as a constraint of the school's `-> str` signature, and directed Claude Code to document it as a known limitation in `planning.md`.

**Instance 2 — Implementing `TOOL_DEFINITIONS`:**

Directed Claude Code to generate the Groq-compatible JSON schema for all three tools from the input parameter tables in `planning.md`. Reviewed each definition to confirm parameter names and types matched the actual function signatures. Revised the `size` parameter description after the initial version was too vague — added concrete format examples for each category (tops, bottoms, shoes) by cross-referencing the actual values in `data/listings.json`. Added "Use when" guidance to each tool description so the LLM knows the intended call order without being hard-coded into a sequence.

**Instance 3 — Implementing `dispatch_tool`:**

Directed Claude Code to implement `dispatch_tool()` to centralize all tool routing and session updates in one place, based on the State Management table in `planning.md`. Reviewed the generated code to confirm: (1) all tools read their inputs from session state rather than directly from LLM-supplied arguments — `search_listings` args are parsed into `session["parsed"]` first, while `suggest_outfit` and `create_fit_card` pull from `session["selected_item"]`, `session["wardrobe"]`, and `session["outfit_suggestion"]` — making the agent resilient to the LLM passing stale or incorrect argument values; (2) `json.loads()` output is checked with `isinstance(args, dict)` to handle the edge case where the LLM serializes `null` arguments. Overrode the initial generated version that used `Any` type annotation for the return — narrowed it to `str` since all tool results must be strings for the Groq message history.

**Instance 4 — Implementing `run_agent`:**

Directed Claude Code to implement `run_agent()` using the Planning Loop and State Management sections of `planning.md`, including the `session["error"]` early exit check at the top of each iteration and the max iteration guard. Reviewed the generated code to confirm: (1) the assistant message is appended as a Pydantic object directly rather than manually converted to a dict, which the Groq SDK accepts; (2) the error check runs after each individual tool dispatch inside the inner loop, not just at the top of the outer loop, so a failed tool stops the loop immediately without processing remaining tool calls in the same batch. Added print statements to monitor iteration count and tool results during testing.

**Instance 5 — System prompt for the planning loop:**

Initially directed Claude Code to write a prescriptive system prompt ("call all three tools in this exact order, never stop after step 1 or step 2"). During testing, the model complied but it felt like a fixed pipeline rather than an agent reasoning about what to do — the course's intent was LLM-driven planning. Overrode the generated prompt with a goal-oriented version: the LLM is told what outputs it must have ready before responding, not which tools to call in which order. Verified the revised prompt still prevented early termination (the LLM stopping after `search_listings`) while giving the model room to reason about what was still missing each iteration.

**Instance 6 — Retry logic with fallback (stretch feature):**

Directed Claude Code to implement the retry fallback in `dispatch_tool`'s search branch — drop size first, then price, appending to `session["retry_note"]` before each retry so the note reflects what was attempted regardless of outcome. Overrode the initial approach of prepending the retry note as plain text in the tool result (caused `tool_use_failed` 400 errors from Llama) with a structured JSON payload `{"results": [...], "note": "..."}` so the LLM receives the filter relaxation context in a clean, parseable format. Added a corresponding instruction to the system prompt so the LLM accepts the relaxed result rather than re-calling `search_listings`.

**Instance 7 — `_chat()` abstraction for malformed tool call retry:**

Directed Claude Code to extract the `BadRequestError` retry logic from inline in `run_agent` into a reusable `_chat()` helper in `tools.py`. The function encapsulates `_get_groq_client()`, the bounded retry loop (`for` loop capped at `MAX_FAILED_RETRIES = 2` to prevent infinite loops), and re-raises on exhaustion. Overrode the initial `while True` loop with a `for` loop after identifying that an unchecked loop is a maintenance hazard. `run_agent` now catches `BadRequestError` at the outer level and logs the error before setting `session["error"]`, keeping retry mechanics out of the planning loop.

**Instance 8 — Price comparison tool (stretch feature):**

Directed Claude Code to implement `compare_price()` from the Tool 4 spec in `planning.md`. Reviewed and overrode several design decisions: (1) rejected passing example comparable titles and prices to the LLM — count, avg, min, and max are sufficient for a price verdict and title names add tokens without improving reasoning; (2) revised the comparables algorithm from "sort by overlap and take top N" to "drop zero-score listings and use all remaining" — more consistent with how `search_listings` works and avoids an arbitrary cap; (3) confirmed variable names use `listing` throughout rather than the abbreviation `l`. Updated the system prompt to instruct the LLM to acknowledge a limited sample when comparables are 1–2, so the assessment reflects the confidence level of the underlying data.
