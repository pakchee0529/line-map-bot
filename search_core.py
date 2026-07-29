import re

from search_normalize import make_display_name, split_input_lines


def google_maps_url(latlon: str) -> str:
    return f"https://www.google.com/maps?q={latlon}"

BRANCH_LETTERS = "WNESGK"
NEAR_OFFSETS = [1, -1, 2, -2, 3, -3]
RANGE_PATTERN = re.compile(r"[～〜~]")
POLE_PATTERN = re.compile(rf"^(.*?)(\d+)((?:[{BRANCH_LETTERS}]\d+)*)$")


def parse_pole_name(name: str) -> dict[str, object] | None:
    m = POLE_PATTERN.match(name)
    if not m:
        return None

    place = m.group(1)
    parent = int(m.group(2))
    branch_str = m.group(3)

    branches: list[tuple[str, int]] = []
    for letter, num in re.findall(rf"([{BRANCH_LETTERS}])(\d+)", branch_str):
        branches.append((letter, int(num)))

    return {
        "place": place,
        "parent": parent,
        "branches": branches,
    }


def build_pole_name(place: str, parent: int, branches: list[tuple[str, int]]) -> str:
    s = f"{place}{parent}"
    for letter, num in branches:
        s += f"{letter}{num}"
    return s


def complete_back_key(front_raw: str, back_raw: str) -> str | None:
    front = parse_pole_name(front_raw)
    if not front:
        return None

    back_full = parse_pole_name(back_raw)
    if back_full and back_full["place"]:
        return build_pole_name(
            str(back_full["place"]),
            int(back_full["parent"]),
            list(back_full["branches"]),  # type: ignore[arg-type]
        )

    m_num = re.match(rf"^(\d+)((?:[{BRANCH_LETTERS}]\d+)*)$", back_raw)
    if m_num:
        parent = int(m_num.group(1))
        branch_str = m_num.group(2)
        branches = [(l, int(n)) for l, n in re.findall(rf"([{BRANCH_LETTERS}])(\d+)", branch_str)]
        return build_pole_name(str(front["place"]), parent, branches)

    m_branch_only = re.match(rf"^((?:[{BRANCH_LETTERS}]\d+)+)$", back_raw)
    if m_branch_only:
        back_branches = [(l, int(n)) for l, n in re.findall(rf"([{BRANCH_LETTERS}])(\d+)", back_raw)]
        front_branches: list[tuple[str, int]] = list(front["branches"])  # type: ignore[assignment]

        if not back_branches:
            return None

        first_back_letter = back_branches[0][0]
        first_back_num = back_branches[0][1]

        prefix: list[tuple[str, int]] = []
        matched_index: int | None = None

        for i, (fl, fn) in enumerate(front_branches):
            if fl == first_back_letter and fn == first_back_num:
                matched_index = i
                break

        if matched_index is not None:
            prefix = front_branches[:matched_index]
        else:
            prefix = front_branches

        return build_pole_name(
            str(front["place"]),
            int(front["parent"]),
            prefix + back_branches,
        )

    return None


def _has_hikikomi(text: str) -> bool:
    return "引込" in text or "引き込み" in text


def create_search_keys(line: str) -> dict[str, object]:
    display_name = make_display_name(line)
    hikikomi = _has_hikikomi(display_name)

    parts = RANGE_PATTERN.split(display_name, maxsplit=1)
    if len(parts) == 1:
        front_key = parts[0]
        return {
            "display_name": display_name,
            "is_range": False,
            "hikikomi": hikikomi,
            "front_key": front_key,
            "back_key": None,
        }

    front_raw = parts[0]
    back_raw = parts[1]

    front_key = front_raw
    back_key = complete_back_key(front_raw, back_raw)

    return {
        "display_name": display_name,
        "is_range": True,
        "hikikomi": hikikomi,
        "front_key": front_key,
        "back_key": back_key,
    }


def exact_match(name: str, pole_coords: dict[str, str]) -> str | None:
    if name and name in pole_coords:
        return name
    return None


def branch_neighbors(name: str) -> list[str]:
    parsed = parse_pole_name(name)
    if not parsed or not parsed["branches"]:
        return []

    branches: list[tuple[str, int]] = list(parsed["branches"])  # type: ignore[assignment]
    last_letter, last_num = branches[-1]
    result: list[str] = []

    for offset in NEAR_OFFSETS:
        new_num = last_num + offset
        if new_num <= 0:
            continue
        new_branches = branches[:-1] + [(last_letter, new_num)]
        result.append(build_pole_name(str(parsed["place"]), int(parsed["parent"]), new_branches))

    return result


def branch_reduction(name: str) -> list[str]:
    parsed = parse_pole_name(name)
    if not parsed or not parsed["branches"]:
        return []

    result: list[str] = []
    branches: list[tuple[str, int]] = list(parsed["branches"])  # type: ignore[assignment]

    while branches:
        branches = branches[:-1]
        result.append(build_pole_name(str(parsed["place"]), int(parsed["parent"]), branches))

    return result


def sibling_branch_search(name: str) -> list[str]:
    parsed = parse_pole_name(name)
    if not parsed or not parsed["branches"]:
        return []

    result: list[str] = []
    branches: list[tuple[str, int]] = list(parsed["branches"])  # type: ignore[assignment]
    last_letter, last_num = branches[-1]

    for offset in NEAR_OFFSETS:
        new_num = last_num + offset
        if new_num <= 0:
            continue
        result.append(
            build_pole_name(
                str(parsed["place"]),
                int(parsed["parent"]),
                branches[:-1] + [(last_letter, new_num)],
            )
        )

    return result


def parent_only_candidates(name: str, pole_coords: dict[str, str]) -> list[str]:
    parsed = parse_pole_name(name)
    if not parsed:
        return []

    if parsed["branches"]:
        return []

    result: list[str] = []
    place = str(parsed["place"])
    parent = int(parsed["parent"])

    # hazard_g9_candidate / hazard_g9_name 相当（Bot版挙動を維持）
    g9 = build_pole_name(place, parent, [("G", 9)])
    g8 = build_pole_name(place, parent, [("G", 8)])
    g10 = build_pole_name(place, parent, [("G", 10)])
    if g9 in pole_coords and g8 not in pole_coords and g10 not in pole_coords:
        result.append(g9)

    plus_1 = build_pole_name(place, parent + 1, [])
    minus_1 = build_pole_name(place, parent - 1, []) if parent - 1 > 0 else None

    if plus_1:
        result.append(plus_1)
    if minus_1:
        result.append(minus_1)

    for letter in ["W", "E", "N", "S", "G", "K"]:
        result.append(build_pole_name(place, parent, [(letter, 1)]))

    for d in range(2, 6):
        plus_name = build_pole_name(place, parent + d, [])
        minus_name = build_pole_name(place, parent - d, []) if parent - d > 0 else None

        if plus_name:
            result.append(plus_name)
        if minus_name:
            result.append(minus_name)

    return result


def non_parent_general_candidates(name: str) -> list[str]:
    parsed = parse_pole_name(name)
    if not parsed:
        return [name]

    seen: set[str] = set()
    result: list[str] = []

    def add(x: str) -> None:
        if x and x not in seen:
            seen.add(x)
            result.append(x)

    add(name)

    branches: list[tuple[str, int]] = list(parsed["branches"])  # type: ignore[assignment]
    if branches and branches[-1] != ("G", 9):
        add(
            build_pole_name(
                str(parsed["place"]),
                int(parsed["parent"]),
                branches + [("G", 9)],
            )
        )

    for x in branch_neighbors(name):
        add(x)

    for x in branch_reduction(name):
        add(x)

    for x in sibling_branch_search(name):
        add(x)

    return result


def general_search_order(name: str, pole_coords: dict[str, str]) -> list[str]:
    parsed = parse_pole_name(name)
    if not parsed:
        return [name]

    if not parsed["branches"]:
        seen: set[str] = set()
        result: list[str] = []

        def add(x: str) -> None:
            if x and x not in seen:
                seen.add(x)
                result.append(x)

        add(name)
        for x in parent_only_candidates(name, pole_coords):
            add(x)
        return result

    return non_parent_general_candidates(name)


def find_first_existing(candidates: list[str], pole_coords: dict[str, str]) -> str | None:
    for c in candidates:
        if c in pole_coords:
            return c
    return None


def _candidate_reason(name: str, original: str) -> str:
    if name == original:
        return "完全一致候補"
    parsed = parse_pole_name(name)
    original_parsed = parse_pole_name(original)
    if parsed and original_parsed:
        branches: list[tuple[str, int]] = list(parsed.get("branches") or [])  # type: ignore[arg-type]
        original_branches: list[tuple[str, int]] = list(original_parsed.get("branches") or [])  # type: ignore[arg-type]
        if branches and branches[-1] == ("G", 9) and branches != original_branches:
            return "G9補完候補（危険傾斜地の可能性）"
        if branches != original_branches and str(parsed.get("place")) == str(original_parsed.get("place")):
            return "枝番・近傍番号の補完候補"
        if int(parsed.get("parent") or 0) != int(original_parsed.get("parent") or 0):
            return "近い番号の候補"
    return "表記補正候補"


def _key_warnings(name: str) -> list[str]:
    parsed = parse_pole_name(name)
    if not parsed:
        return []
    branches: list[tuple[str, int]] = list(parsed.get("branches") or [])  # type: ignore[arg-type]
    warnings: list[str] = []
    if any(letter == "K" for letter, _ in branches):
        warnings.append("K枝番は仮想柱の可能性があります")
    if branches and branches[-1] == ("G", 9):
        warnings.append("G9枝番は危険傾斜地等の補正候補として扱います")
    return warnings


def candidate_details(
    name: str,
    pole_coords: dict[str, str],
    *,
    limit: int = 8,
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for candidate in general_search_order(name, pole_coords):
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate not in pole_coords:
            continue
        out.append(
            {
                "name": candidate,
                "reason": _candidate_reason(candidate, name),
            }
        )
        if len(out) >= limit:
            break
    return out


def resolve_key_with_details(
    name: str,
    pole_coords: dict[str, str],
) -> dict[str, object]:
    candidates = candidate_details(name, pole_coords)
    adopted = str(candidates[0]["name"]) if candidates else None
    return {
        "input": name,
        "adopted": adopted,
        "candidates": candidates,
        "warnings": _key_warnings(name) + (_key_warnings(adopted) if adopted else []),
    }


DISPLAY_SUGGESTION_LIMIT = 5


def display_suggestions_for_unresolved(
    line: str, pole_coords: dict[str, str], *, limit: int = DISPLAY_SUGGESTION_LIMIT
) -> list[str]:
    """該当なし時の表示専用。採用ロジックには使わない。

    同一冠称地名のうち GPS に登録がある別電柱名を最大 ``limit`` 件返す。
    """
    info = create_search_keys(line)
    front_key = str(info["front_key"])
    parsed = parse_pole_name(front_key)
    if not parsed:
        return []

    place = str(parsed.get("place") or "")
    if not place:
        return []

    out: list[str] = []
    for key in sorted(pole_coords.keys()):
        if key == front_key:
            continue
        other = parse_pole_name(key)
        if not other:
            continue
        if str(other.get("place") or "") != place:
            continue
        out.append(key)
        if len(out) >= limit:
            break
    return out


def detailed_suggestions_for_unresolved(
    line: str, pole_coords: dict[str, str], *, limit: int = DISPLAY_SUGGESTION_LIMIT
) -> list[dict[str, str]]:
    info = create_search_keys(line)
    front_key = str(info["front_key"])
    details = candidate_details(front_key, pole_coords, limit=limit)
    if details:
        return details[:limit]
    return [
        {"name": name, "reason": "同一冠称名の候補"}
        for name in display_suggestions_for_unresolved(line, pole_coords, limit=limit)
    ]


def resolve_one(line: str, pole_coords: dict[str, str]) -> dict[str, object]:
    info = create_search_keys(line)
    display_name = str(info["display_name"])
    is_range = bool(info["is_range"])
    hikikomi = bool(info["hikikomi"])
    front_key = str(info["front_key"])
    back_key = info["back_key"]

    adopted: str | None = None
    preferred_key: str | None = None
    warnings: list[str] = []
    candidate_notes: list[str] = []
    span_points: list[dict[str, str]] = []

    if is_range and isinstance(back_key, str) and back_key and not hikikomi:
        front_resolved = resolve_key_with_details(front_key, pole_coords)
        back_resolved = resolve_key_with_details(back_key, pole_coords)
        front_adopted = front_resolved.get("adopted")
        back_adopted = back_resolved.get("adopted")
        if isinstance(front_adopted, str) and front_adopted:
            span_points.append(
                {"role": "若", "input": front_key, "adopted": front_adopted}
            )
        else:
            warnings.append(f"若側がGPS未登録: {front_key}")
        if isinstance(back_adopted, str) and back_adopted:
            span_points.append(
                {"role": "老", "input": back_key, "adopted": back_adopted}
            )
        else:
            warnings.append(f"老側がGPS未登録: {back_key}")

        warnings.extend(str(x) for x in front_resolved.get("warnings") or [])
        warnings.extend(str(x) for x in back_resolved.get("warnings") or [])
        for input_key, resolved in (
            (front_key, front_resolved),
            (back_key, back_resolved),
        ):
            selected = str(resolved.get("adopted") or "")
            if selected and selected != input_key:
                candidate_notes.append(
                    f"{selected}: {_candidate_reason(selected, input_key)}"
                )

        if isinstance(back_adopted, str) and back_adopted:
            adopted = back_adopted
            preferred_key = back_key
        elif isinstance(front_adopted, str) and front_adopted:
            adopted = front_adopted
            preferred_key = front_key
    else:
        resolved = resolve_key_with_details(front_key, pole_coords)
        maybe_adopted = resolved.get("adopted")
        adopted = maybe_adopted if isinstance(maybe_adopted, str) else None
        preferred_key = front_key
        warnings.extend(str(x) for x in resolved.get("warnings") or [])
        if adopted and adopted != front_key:
            candidate_notes.append(
                f"{adopted}: {_candidate_reason(adopted, front_key)}"
            )

    if not adopted:
        return {
            "found": False,
            "display_name": display_name,
            "url": None,
            "note": None,
            "is_range": is_range,
            "map_url": None,
            "adopted": None,
            "suggestions": display_suggestions_for_unresolved(line, pole_coords),
            "suggestion_details": detailed_suggestions_for_unresolved(line, pole_coords),
            "warnings": sorted(set(warnings)),
            "candidate_notes": candidate_notes,
            "span_points": span_points,
        }

    latlon = pole_coords[adopted]
    url = google_maps_url(latlon)
    note = None

    if adopted != preferred_key:
        note = f"（{display_name} → {adopted}）"
        candidate_notes.insert(0, f"{adopted}: {_candidate_reason(adopted, preferred_key or display_name)}")

    return {
        "found": True,
        "display_name": display_name,
        "url": url,
        "note": note,
        "is_range": is_range,
        "map_url": None,
        "adopted": adopted,
        "warnings": sorted(set(warnings)),
        "candidate_notes": candidate_notes,
        "span_points": span_points,
    }


def resolve_lines(text: str, pole_coords: dict[str, str]) -> list[dict[str, object]]:
    lines = split_input_lines(text)
    results: list[dict[str, object]] = []
    for line in lines:
        results.append(resolve_one(line, pole_coords))
    return results


__all__ = [
    "BRANCH_LETTERS",
    "NEAR_OFFSETS",
    "RANGE_PATTERN",
    "POLE_PATTERN",
    "parse_pole_name",
    "build_pole_name",
    "complete_back_key",
    "create_search_keys",
    "exact_match",
    "branch_neighbors",
    "branch_reduction",
    "sibling_branch_search",
    "parent_only_candidates",
    "non_parent_general_candidates",
    "general_search_order",
    "find_first_existing",
    "candidate_details",
    "resolve_key_with_details",
    "DISPLAY_SUGGESTION_LIMIT",
    "display_suggestions_for_unresolved",
    "detailed_suggestions_for_unresolved",
    "resolve_one",
    "resolve_lines",
]
