"""tests/test_tools.py — unit tests for the three FitFindr tools.

Run from the project root:
    pytest tests/
"""

import pytest
from unittest.mock import MagicMock, patch

from tools import (
    CREATE_FIT_CARD_PROMPT,
    SUGGEST_OUTFIT_PROMPT_GENERAL,
    SUGGEST_OUTFIT_PROMPT_WARDROBE,
    create_fit_card,
    search_listings,
    suggest_outfit,
)

# ── Shared fixtures ───────────────────────────────────────────────────────────

SAMPLE_ITEM = {
    "id": "lst_002",
    "title": "Y2K Baby Tee — Butterfly Print",
    "description": "Super cute early 2000s baby tee with butterfly graphic.",
    "category": "tops",
    "style_tags": ["y2k", "vintage", "graphic tee", "cottagecore"],
    "size": "S/M",
    "condition": "excellent",
    "price": 18.00,
    "colors": ["white", "pink", "purple"],
    "brand": None,
    "platform": "depop",
}

SAMPLE_WARDROBE = {
    "items": [
        {
            "id": "w_001",
            "name": "Baggy straight-leg jeans, dark wash",
            "category": "bottoms",
            "colors": ["dark blue", "indigo"],
            "style_tags": ["denim", "streetwear", "baggy"],
            "notes": "High-waisted, sits above the hip",
        },
        {
            "id": "w_007",
            "name": "Chunky white sneakers",
            "category": "shoes",
            "colors": ["white"],
            "style_tags": ["sneakers", "chunky", "streetwear"],
            "notes": None,
        },
    ]
}

EMPTY_WARDROBE = {"items": []}


def _mock_client(content: str) -> MagicMock:
    """Return a MagicMock Groq client whose .chat.completions.create() returns content."""
    mock = MagicMock()
    mock.chat.completions.create.return_value.choices[0].message.content = content
    return mock


# ── search_listings ───────────────────────────────────────────────────────────

def test_search_empty_results():
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_description_only():
    results = search_listings("vintage")
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_price_filter():
    results = search_listings("vintage", size=None, max_price=20)
    assert len(results) > 0
    assert all(item["price"] <= 20 for item in results)


def test_search_size_filter():
    results = search_listings("vintage", size="M")
    assert len(results) > 0
    assert all("m" in item["size"].lower() for item in results)


def test_search_all_filters():
    results = search_listings("vintage", size="M", max_price=30.0)
    assert len(results) > 0
    assert all(item["price"] <= 30.0 for item in results)
    assert all("m" in item["size"].lower() for item in results)


# ── suggest_outfit ────────────────────────────────────────────────────────────

def test_suggest_outfit_non_empty_wardrobe_uses_wardrobe_prompt():
    mock = _mock_client("Pair with your baggy jeans and chunky sneakers.")
    with patch("tools._get_groq_client", return_value=mock):
        result = suggest_outfit(SAMPLE_ITEM, SAMPLE_WARDROBE)
    system_prompt = mock.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert system_prompt == SUGGEST_OUTFIT_PROMPT_WARDROBE
    assert result == "Pair with your baggy jeans and chunky sneakers."


def test_suggest_outfit_empty_wardrobe_uses_general_prompt():
    mock = _mock_client("This piece pairs well with wide-leg trousers.")
    with patch("tools._get_groq_client", return_value=mock):
        result = suggest_outfit(SAMPLE_ITEM, EMPTY_WARDROBE)
    system_prompt = mock.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert system_prompt == SUGGEST_OUTFIT_PROMPT_GENERAL
    assert result == "This piece pairs well with wide-leg trousers."


# ── create_fit_card ───────────────────────────────────────────────────────────

def test_create_fit_card_valid_outfit_calls_llm():
    mock = _mock_client("Thrifted this butterfly tee on depop for $18 and I'm obsessed.")
    with patch("tools._get_groq_client", return_value=mock):
        result = create_fit_card("Pair with baggy jeans and chunky sneakers.", SAMPLE_ITEM)
    assert result == "Thrifted this butterfly tee on depop for $18 and I'm obsessed."
    mock.chat.completions.create.assert_called_once()


@pytest.mark.parametrize("bad_outfit_input", ["", "   ", "\t", "\n"])
def test_create_fit_card_bad_outfit_input(bad_outfit_input):
    mock = _mock_client("should not be reached")
    with patch("tools._get_groq_client", return_value=mock):
        result = create_fit_card(bad_outfit_input, SAMPLE_ITEM)
    assert result == "Something went wrong generating your fit card. Please try your search again."
    mock.chat.completions.create.assert_not_called()
