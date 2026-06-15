"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import json

from groq import BadRequestError
from groq.types.chat import ChatCompletionMessageToolCall

from config import GROQ_MODEL
from tools import _chat, create_fit_card, search_listings, suggest_outfit


# ── tool definitions ──────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_listings",
            "description": (
                "Search thrift listings by description with optional size and price filters. "
                "Returns a ranked list of matching listings sorted by keyword relevance. "
                "Use this first whenever the user asks about finding a thrift item."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Keywords describing the item (e.g. 'vintage graphic tee')",
                    },
                    "size": {
                        "type": ["string", "null"],
                        "description": (
                            "Size to filter by. Formats vary by category — "
                            "tops/outerwear: letter sizes (e.g. 'S', 'M', 'L', 'XL', 'S/M', 'M/L', 'L/XL', "
                            "'XL (oversized)', 'XL (fits oversized)', 'One Size', 'One Size / Oversized', 'Oversized'); "
                            "bottoms: waist only (e.g. 'W27', 'W28', 'W29', 'W30', 'W32') or waist/length (e.g. 'W30 L30'); "
                            "shoes: US sizing (e.g. 'US 7', 'US 8', 'US 8.5', 'US 9'). "
                            "Pass the size closest to what the user states. Pass null if no size is mentioned."
                        ),
                    },
                    "max_price": {
                        "type": ["number", "null"],
                        "description": "Maximum price inclusive. Pass null to skip.",
                    },
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_outfit",
            "description": (
                "Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfit "
                "combinations. If the wardrobe is empty, returns general styling advice instead. "
                "Use this after search_listings returns at least one result."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "new_item": {
                        "type": "object",
                        "description": "The selected listing dict from search_listings.",
                    },
                    "wardrobe": {
                        "type": "object",
                        "description": "The user's wardrobe dict with an 'items' key.",
                    },
                },
                "required": ["new_item", "wardrobe"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_fit_card",
            "description": (
                "Generate a 2–4 sentence Instagram-style caption for the thrifted outfit. "
                "Mentions the item name, price, and platform naturally. "
                "Use this after suggest_outfit returns an outfit suggestion."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "outfit": {
                        "type": "string",
                        "description": "The outfit suggestion string returned by suggest_outfit.",
                    },
                    "new_item": {
                        "type": "object",
                        "description": "The selected listing dict (for item name, price, and platform).",
                    },
                },
                "required": ["outfit", "new_item"],
            },
        },
    },
]


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
        "retry_note": "",             # appended to if search was retried with loosened filters
    }


# ── tool dispatch ────────────────────────────────────────────────────────────

def dispatch_tool(tool_call: ChatCompletionMessageToolCall, session: dict) -> str:
    """
    Execute a single tool call and update the session in place.

    Returns the tool result as a string for appending to the message history.
    Sets session["error"] on failure — caller should check after each dispatch.
    """
    name = tool_call.function.name
    args = json.loads(tool_call.function.arguments or "{}")
    if not isinstance(args, dict):
        args = {}

    if name == "search_listings":
        session["retry_note"] = ""  # reset on each search dispatch
        session["parsed"] = {
            "description": args.get("description"),
            "size": args.get("size"),
            "max_price": args.get("max_price"),
        }

        results = search_listings(
            description=session["parsed"]["description"],
            size=session["parsed"]["size"],
            max_price=session["parsed"]["max_price"],
        )

        if not results and session["parsed"]["size"] is not None:
            session["retry_note"] += (
                f"No results found for size {session['parsed']['size']} — size filter removed.\n"
            )
            results = search_listings(
                description=session["parsed"]["description"],
                size=None,
                max_price=session["parsed"]["max_price"],
            )

        if not results and session["parsed"]["max_price"] is not None:
            session["retry_note"] += (
                f"No results found under ${session['parsed']['max_price']:.2f} — price filter removed.\n"
            )
            results = search_listings(
                description=session["parsed"]["description"],
                size=None,
                max_price=None,
            )

        session["search_results"] = results
        session["selected_item"] = results[0] if results else None
        if not results:
            session["error"] = (
                "No listings found matching your description. Try broadening your search — "
                "remove the size or price filter, or use different keywords."
            )
        # Return only the top result to keep token usage low — full results are in session.
        # Structured payload so the LLM understands any filter relaxation without being re-prompted.
        payload = {"results": results[:1]}
        if session["retry_note"]:
            payload["note"] = session["retry_note"].strip()
        return json.dumps(payload)

    if name == "suggest_outfit":
        outfit = suggest_outfit(session["selected_item"], session["wardrobe"])
        session["outfit_suggestion"] = outfit
        return outfit

    if name == "create_fit_card":
        outfit = session["outfit_suggestion"]
        fit_card = create_fit_card(outfit, session["selected_item"])
        if not outfit or not outfit.strip():
            session["error"] = fit_card
        else:
            session["fit_card"] = fit_card
        return fit_card

    session["error"] = f"Unknown tool called: {name}"
    return ""


# ── constants ────────────────────────────────────────────────────────────────

MAX_ITERATIONS = 5

SYSTEM_PROMPT = (
    "You are FitFindr, a thrift shopping assistant. "
    "You are done when you have all three of the following ready for the user:\n\n"
    "1. A thrift listing that matches the user's request.\n"
    "2. An outfit suggestion built around that listing.\n"
    "3. An Instagram-style fit card caption for the outfit.\n\n"
    "Finding the listing is only the first step — all three must be ready before the task is done. "
    "If search returns no results, the task is complete — inform the user there is nothing to style. "
    "If the search result includes a 'note' field, the filters were already relaxed to find "
    "the best available match — treat the returned listing as the working item."
)


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    Done - implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    session = _new_session(query, wardrobe)

    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ]

        for iteration in range(MAX_ITERATIONS):
            print(f"\n[FitFindr] Iteration {iteration + 1}/{MAX_ITERATIONS}")
            if session["error"]:
                return session

            response = _chat(messages, tools=TOOL_DEFINITIONS, tool_choice="auto")

            message = response.choices[0].message

            if not message.tool_calls:
                if session["fit_card"] is None:
                    session["error"] = "FitFindr couldn't complete your request. Please try again."
                print("[FitFindr] No tool calls — loop complete")
                return session

            # Append assistant message with tool calls to history
            messages.append(message)

            for tool_call in message.tool_calls:
                print(f"[FitFindr] Calling tool: {tool_call.function.name}")
                result = dispatch_tool(tool_call, session)
                print(f"[FitFindr] Tool result: {result}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })
                if session["error"]:
                    return session

        session["error"] = "FitFindr ran into an issue and couldn't complete your request. Please try again."

    except BadRequestError as e:
        print(f"[FitFindr] Malformed tool call retries exhausted: {e}")
        session["error"] = "FitFindr ran into an issue and couldn't complete your request. Please try again."
    except Exception as e:
        print(f"[FitFindr] Unexpected error: {e}")
        session["error"] = "FitFindr ran into an unexpected error. Please try again."

    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
