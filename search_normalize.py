import re
import unicodedata


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text))
    return text.upper()


def remove_spaces(text: str) -> str:
    return re.sub(r"[ \u3000]+", "", str(text))


def normalize_key(text: str) -> str:
    return remove_spaces(normalize_text(text))


def normalize_input_line(text: str) -> str:
    return remove_spaces(normalize_text(text.strip()))


def split_input_lines(text: str) -> list[str]:
    lines = [normalize_input_line(line) for line in text.splitlines()]
    return [line for line in lines if line]


def make_display_name(text: str) -> str:
    return remove_spaces(normalize_text(text))


__all__ = [
    "normalize_text",
    "remove_spaces",
    "normalize_key",
    "normalize_input_line",
    "split_input_lines",
    "make_display_name",
]
