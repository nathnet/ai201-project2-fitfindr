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
You are FitFindr, a thrift shopping assistant. Use the available tools to help the user find a
secondhand item and build an outfit around it.

You are done only when you have all three of the following ready for the user:
- A matching thrift listing
- An outfit suggestion for that item
- An Instagram-style fit card caption

Do not give a final response until all three are ready.
If search returns no results, stop and inform the user — there is nothing to style.
```

> **Note:** The prompt was revised from a prescriptive step-by-step sequence to a goal-oriented exit condition. This gives the LLM room to reason about what is still missing each iteration rather than following fixed steps — more aligned with the course's intent of LLM-driven planning.

**Groq call structure:**
```python
response = client.chat.completions.create(
    model=LLM_MODEL,
    messages=messages,
    tools=TOOL_DEFINITIONS,
    tool_choice="auto",
)
```

- `messages` — starts with the system prompt and user query; assistant tool call responses and tool results are appended each iteration
- `TOOL_DEFINITIONS` — JSON schemas for all available tools (search_listings, suggest_outfit, create_fit_card)
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
If an empty list is returned, the LLM stops the planning loop, sets `session["error"]` to "No listings found matching your description. Try broadening your search — remove the size or price filter, or use different keywords.", and returns the session early without calling `suggest_outfit` or `create_fit_card`.

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
If `outfit` is empty or whitespace, the tool returns a descriptive error string without calling the LLM. `run_agent()` routes the result by checking the `outfit` input: if empty or whitespace, the return value goes into `session["error"]`; otherwise into `session["fit_card"]`. The session is returned early with `fit_card` as None, and `app.py` surfaces the error in panel 1 with panels 2 and 3 left empty.

**Limitation:** the tool returns `str` in both success and failure paths — the assignment's required signature prevents returning `None` (the idiomatic Python failure signal). `run_agent()` must therefore check the input, not the output, to distinguish an error from a valid caption.

---

### Additional Tools (if any)

<!-- Copy the block above for any tools beyond the required three -->

---

## Planning Loop

**How does your agent decide which tool to call next?**
<!-- Describe the logic your planning loop uses. What does it look at? What conditions change its behavior? How does it know when it's done? -->
The planning loop is LLM-driven. The first call is initialized with just the system prompt and the user's message. On each subsequent iteration, the full message history (including previous tool calls and results) is passed to the LLM with `tool_choice="auto"`.

The LLM decides which tool to call next based on the message history:
- No search result yet → calls `search_listings`
- Listing found, no outfit yet → calls `suggest_outfit`
- Outfit found, no fit card yet → calls `create_fit_card`
- Fit card done → returns a final response with no tool calls → loop exits

**Early exits:**
- `search_listings` returns empty results → set `session["error"]`, call no further tools, return session immediately
- `create_fit_card` receives an empty outfit string → set `session["error"]`, call no further tools, return session immediately

**Loop termination:**
The loop exits when the LLM returns a response with no `tool_calls`. A max iteration guard of **5** is set (3 required tools + 2 buffer, increasing as new tools are introduced). If the guard is hit, `session["error"]` is set to a generic failure message and the session is returned.

---

## State Management

**How does information from one tool get passed to the next?**
<!-- Describe how your agent stores and accesses state within a session. What data is tracked? How is it passed between tool calls? -->
Each call to `run_agent()` creates a fresh session dict via `_new_session()`. The session is the single source of truth for all state within one interaction and is never shared across calls.

| Field | Set by | Used by |
|---|---|---|
| `query` | `_new_session()` | LLM initial message |
| `wardrobe` | `_new_session()` | `suggest_outfit` |
| `parsed` | `search_listings` input | `search_listings` |
| `search_results` | `search_listings` result | agent to select `selected_item` |
| `selected_item` | agent (top of `search_results`) | `suggest_outfit`, `create_fit_card` |
| `outfit_suggestion` | `suggest_outfit` result | `create_fit_card` |
| `fit_card` | `create_fit_card` result | `app.py` (panel 3) |
| `error` | early exit or exception handler | `app.py` (panel 1) |

Tool results are also appended to the `messages` list each iteration so the LLM can read them in the next loop. The session dict is the Python-side record used to populate the Gradio UI on return; the message history is the LLM-side record used to drive tool selection.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Set `session["error"]` to "No listings found matching your description. Try broadening your search — remove the size or price filter, or use different keywords." Stop the loop immediately. Do not call `suggest_outfit` or `create_fit_card`. Return the session. |
| suggest_outfit | Wardrobe is empty | Do not stop the loop. Check `wardrobe["items"]` — if empty, switch to the empty-wardrobe system prompt for general styling advice. Call the LLM and return the response string as normal. The loop continues to `create_fit_card`. |
| create_fit_card | Outfit input is missing or incomplete | The tool returns a descriptive error string without calling the LLM. `run_agent()` checks the `outfit` input after the call: if empty or whitespace, the return value is routed to `session["error"]`; otherwise to `session["fit_card"]`. Loop stops and session is returned with `fit_card` as None. |

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
    ├─ error set → Panel 1: error msg  | Panel 2: empty   | Panel 3: empty
    └─ success  → Panel 1: listing     | Panel 2: outfit  | Panel 3: fit card
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

- **TOOL_DEFINITIONS:** Give Claude Code the input parameter tables for all three tools from the Tools section. Ask it to produce the Groq-compatible JSON schema definitions for each tool. Verify each definition matches the parameter names, types, and required fields in the spec.
- **run_agent() loop:** Give Claude Code the Initial LLM Call section, Planning Loop section, State Management section, and the Architecture diagram. Ask it to implement the LLM-driven loop with Groq tool calling. Verify: message history is appended correctly each iteration, early exit on empty search results sets `session["error"]` and returns without calling remaining tools, and the max iteration guard is present. Test using the two CLI cases already in `agent.py` — happy path and no-results path.
- **handle_query():** Give Claude Code the `app.py` TODO comments and the State Management section. Ask it to implement `handle_query()`. Verify: empty query is caught early, wardrobe is selected correctly based on `wardrobe_choice`, `session["error"]` routes to panel 1 with panels 2 and 3 empty, and success routes all three fields to the correct panels. Test by running `app.py` and submitting both a valid query and the deliberate no-results example query.

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
The LLM receives a new list of listings matching description and max_price it searched.  
a.) If the returned result contains one or more listings, the LLM selects the most relevant and 
queues up one tool call for suggest_outfit(selected_item, wardrobe).  
b.) If an empty result is returned, the LLM stops calling tools, informs the user of unavailability 
of the clothes the user is looking for, suggesting the user change their requirements. 

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
3 things: 1. top listing match, 2. outfit idea, and 3. a nice caption 
for their instagram post (fit card)