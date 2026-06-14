"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from config import GROQ_MODEL
from utils.data_loader import load_listings

load_dotenv()


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Prompt constants ─────────────────────────────────────────────────────────

SUGGEST_OUTFIT_PROMPT_WARDROBE = (
    "You are a personal stylist. Given the thrift item and the user's wardrobe below, suggest 1–2 "
    "complete outfit combinations that each include the new thrift item paired with specific named pieces "
    "from the wardrobe. If any key categories (tops, bottoms, shoes) are missing from the wardrobe, "
    "mention what type of piece would complete the look. "
    "Be concise — 3–5 sentences per outfit. Plain text only — no bullet points, no headers, no markdown."
)

SUGGEST_OUTFIT_PROMPT_GENERAL = (
    "You are a personal stylist. Given the thrift item below, suggest general styling advice — "
    "what types of pieces pair well with it based on its category, what vibe it suits, "
    "and how to build an outfit around it. "
    "Be concise — 3–5 sentences. Plain text only — no bullet points, no headers, no markdown."
)

CREATE_FIT_CARD_PROMPT = (
    "You are a fashion-forward social media writer. Given the outfit suggestion and thrift item below, "
    "pick the single most interesting outfit combination and write a 2–4 sentence Instagram caption for it. "
    "Make it casual and authentic — like a real OOTD post, not a product description. "
    "Mention the item name, price, and platform naturally. "
    "Capture the outfit vibe in specific terms. Sound different each time. "
    "Output the caption text only — no headers, no labels, no preamble."
)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()

    if max_price is not None:
        listings = [listing for listing in listings if listing["price"] <= max_price]
    if size is not None:
        listings = [listing for listing in listings if size.lower() in listing["size"].lower()]

    query_keywords = set(re.findall(r"\b\w+\b", description.lower()))

    scored_listings = []
    for listing in listings:
        listing_desc_words = set(re.findall(r"\b\w+\b", listing["description"].lower()))
        desc_score = sum(1 for keyword in query_keywords if keyword in listing_desc_words)

        listing_tag_words = set(re.findall(r"\b\w+\b", " ".join(listing["style_tags"]).lower()))
        tag_score = sum(2 for keyword in query_keywords if keyword in listing_tag_words)

        total_score = desc_score + tag_score
        if total_score > 0:
            scored_listings.append((total_score, listing))

    scored_listings.sort(key=lambda x: x[0], reverse=True)
    return [listing for _, listing in scored_listings]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    # Raises rather than returns an error string — empty new_item is a
    # programmatic failure; this function is not meant to be called without a valid item.
    if not new_item:
        raise ValueError("suggest_outfit called with empty new_item")

    client = _get_groq_client()

    item_text = (
        f"New thrift item: {new_item['title']}\n"
        f"- Category: {new_item['category']}\n"
        f"- Description: {new_item['description']}\n"
        f"- Colors: {', '.join(new_item['colors'])}\n"
        f"- Style tags: {', '.join(new_item['style_tags'])}\n"
        f"- Size: {new_item['size']}\n"
        f"- Condition: {new_item['condition']}\n"
        f"- Price: ${new_item['price']:.2f} on {new_item['platform']}\n"
    )

    if not wardrobe["items"]:
        system_prompt = SUGGEST_OUTFIT_PROMPT_GENERAL
        user_message = item_text
    else:
        system_prompt = SUGGEST_OUTFIT_PROMPT_WARDROBE
        wardrobe_lines = "\n".join(
            f"- {item['name']} ({item['category']}) — colors: {', '.join(item['colors'])}"
            f" — style: {', '.join(item['style_tags'])}"
            + (f" — notes: {item['notes']}" if item.get("notes") else "")
            for item in wardrobe["items"]
        )
        user_message = f"{item_text}\nUser's wardrobe:\n{wardrobe_lines}"

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )

    return response.choices[0].message.content


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    if not outfit or not outfit.strip():
        return "Something went wrong generating your fit card. Please try your search again."

    client = _get_groq_client()

    item_details = (
        f"Item: {new_item['title']}\n"
        f"Price: ${new_item['price']:.2f}\n"
        f"Platform: {new_item['platform']}\n"
    )

    user_message = f"{item_details}\nOutfit suggestion:\n{outfit}"

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": CREATE_FIT_CARD_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=1.0,
    )

    return response.choices[0].message.content
