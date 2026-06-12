"""Tests for the pure slugify helper."""

import pytest

from cress.slugify import slugify


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Hello World", "hello-world"),
        ("hello world", "hello-world"),
        ("HELLO WORLD", "hello-world"),
        ("Multiple   Spaces", "multiple-spaces"),
        ("hello-world", "hello-world"),
        ("a---b", "a-b"),
        ("Café Résumé", "cafe-resume"),
        ("Niño Pingüino", "nino-pinguino"),
        ("naïve façade", "naive-facade"),
        ("Hello, World!", "hello-world"),
        ("What's up?", "what-s-up"),
        ("100% cotton", "100-cotton"),
        ("Hello 😀 World", "hello-world"),
        ("---leading", "leading"),
        ("trailing---", "trailing"),
        ("  spaces around  ", "spaces-around"),
        ("Machine Learning", "machine-learning"),
    ],
)
def test_slugify_known_cases(raw: str, expected: str) -> None:
    assert slugify(raw) == expected


@pytest.mark.parametrize(
    "empty_ish",
    ["", "   ", "\t\n", "!!!", "---", "😀😀😀"],
)
def test_slugify_empty_ish_returns_untitled(empty_ish: str) -> None:
    assert slugify(empty_ish) == "untitled"


def test_slugify_is_idempotent() -> None:
    text = "Hello World"
    assert slugify(slugify(text)) == slugify(text)
