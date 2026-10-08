"""
Trust score (S6): the pure maths. No database, no clock reads, so every rule can be tested alone.

How a score is built
--------------------
Every active checklist item of a course file gets a CREDIT between 0 and 1 in each of four parts:

    Completeness   Timeliness   Format   Content

A part's points = (its effective weight) x (average credit of all items). The total is the sum of the four parts.
Only OPEN flags cost credit. A CLEARED or WAIVED flag costs nothing (but lateness can only be WAIVED, never cleared).

    MISSING open      Completeness 0, Timeliness 0       (doc: a missing document is a hard fail)
    INCOMPLETE open   Completeness 0.5                   (a file exists but is unusable, so half credit)
    LATE open         Timeliness 0                       (never recovers by itself)
    FORMAT open       Format 0                           (no double loss with INCOMPLETE: that one is only half)
    CONTENT/MISMATCH  Content 0                          (only counts once content scoring is switched on)

An item with no flag and no problem is full credit, also when its deadline has not come yet ("pending").
So a score only goes down when something went wrong.
"""
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
import hashlib
import json

D = Decimal
PARTS = ("completeness", "timeliness", "format", "content")
SCORED, NO_DEADLINES, NO_ITEMS = "SCORED", "NO_DEADLINES", "NO_ITEMS"
SCORED_KINDS = ("LATE", "MISSING", "INCOMPLETE", "FORMAT", "CONTENT", "MISMATCH")
INCOMPLETE_CREDIT = D("0.5")
CENT = D("0.01")
ONE, ZERO = D(1), D(0)

CONTENT_OFF_NOTE = (
    "Content checks are not live yet. The {c} points reserved for Content are shared between Completeness, "
    "Timeliness and Format in the same proportion, so the three parts below add up to 100."
)
NO_DEADLINES_NOTE = "No deadline is set for any item yet, so there is nothing to judge. No score is shown."
NO_ITEMS_NOTE = "This course file has no active checklist items. No score is shown."


def q2(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def apportion(values: list[Decimal], target: Decimal) -> list[Decimal]:
    """
    Round non-negative numbers to 2 decimals so that they add up to `target` exactly (largest remainder).
    Only entries above zero can receive or lose a cent, so a part that lost nothing never shows a loss.
    """
    n = len(values)
    cents = [int((v * 100).to_integral_value(rounding=ROUND_FLOOR)) for v in values]
    frac = [v * 100 - c for v, c in zip(values, cents)]
    need = int((target * 100).to_integral_value(rounding=ROUND_HALF_UP)) - sum(cents)
    eligible = [i for i in range(n) if values[i] > 0]
    if need > 0 and eligible:
        order = sorted(eligible, key=lambda i: (-frac[i], i))
        k = 0
        while need > 0:
            cents[order[k % len(order)]] += 1
            need -= 1
            k += 1
    elif need < 0:
        order = sorted((i for i in eligible if cents[i] > 0), key=lambda i: (frac[i], i))
        k, guard = 0, 0
        while need < 0 and order and guard < 1000:
            idx = order[k % len(order)]
            if cents[idx] > 0:
                cents[idx] -= 1
                need += 1
            k += 1
            guard += 1
    return [D(c) / 100 for c in cents]


def effective_weights(weights: dict, content_active: bool) -> dict:
    """The weights actually used. While Content is off, its weight is shared out in proportion (adds up to 100)."""
    if content_active:
        return {p: D(int(weights[p])).quantize(CENT) for p in PARTS}
    base = int(weights["completeness"]) + int(weights["timeliness"]) + int(weights["format"])
    if base <= 0:
        raise ValueError("Completeness, Timeliness and Format weights cannot all be zero.")
    raw = [D(int(weights[p])) * 100 / base for p in ("completeness", "timeliness", "format")]
    shares = apportion(raw, D(100))
    return {"completeness": shares[0], "timeliness": shares[1], "format": shares[2], "content": D("0.00")}


# ---------------------------------------------------------------- one item
def score_item(item: dict) -> dict:
    """
    item: {has_file, newest_ok, due_at, due_passed, flags: [{id, kind, status, reason}]}
    Returns {state, credits{part: Decimal}, reasons[str], open_kinds[str]}.
    """
    flags = [f for f in item["flags"] if f["kind"] in SCORED_KINDS]
    open_ = {f["kind"]: f for f in flags if f["status"] == "OPEN"}
    waived = sorted({f["kind"] for f in flags if f["status"] == "WAIVED" and f["kind"] not in open_})
    cleared = sorted({f["kind"] for f in flags if f["status"] == "CLEARED" and f["kind"] not in open_})

    credits = {p: ONE for p in PARTS}
    reasons: list[str] = []

    if "MISSING" in open_:
        credits["completeness"] = ZERO
        credits["timeliness"] = ZERO
        reasons.append(f"MISSING: {open_['MISSING']['reason']} Completeness and Timeliness of this item are 0.")
    if "INCOMPLETE" in open_:
        credits["completeness"] = min(credits["completeness"], INCOMPLETE_CREDIT)
        extra = " The unusable file is penalised once more under Format, never twice under Completeness." \
            if "FORMAT" in open_ else ""
        reasons.append(f"INCOMPLETE: {open_['INCOMPLETE']['reason']} A file was submitted, so Completeness "
                       f"gets half credit (0.5).{extra}")
    if "FORMAT" in open_:
        credits["format"] = ZERO
        reasons.append(f"FORMAT: {open_['FORMAT']['reason']} Format of this item is 0 until a valid file is uploaded.")
    if "LATE" in open_:
        credits["timeliness"] = ZERO
        reasons.append(f"LATE: {open_['LATE']['reason']} Timeliness of this item is 0. Lateness never clears; "
                       "only a waiver with a reason can set it aside.")
    for kind in ("CONTENT", "MISMATCH"):
        if kind in open_:
            credits["content"] = ZERO
            reasons.append(f"{kind}: {open_[kind]['reason']} Content of this item is 0 once content scoring is on.")
    for kind in waived:
        reasons.append(f"{kind} was waived with a reason, so it costs nothing (full credit).")
    for kind in cleared:
        reasons.append(f"{kind} was cleared by a later valid upload (full credit).")

    for kind in ("MISSING", "INCOMPLETE", "FORMAT", "LATE", "CONTENT", "MISMATCH"):
        if kind in open_:
            state = kind
            break
    else:
        if waived:
            state = "WAIVED"
        elif item["has_file"]:
            state = "OK"
        else:
            state = "PENDING"

    if state == "OK" and not reasons:
        reasons.append("A valid file is submitted. Full credit.")
    if state == "PENDING":
        if item.get("due_at") is None:
            reasons.append("No deadline is set for this item and nothing was submitted. No penalty yet.")
        elif item.get("due_passed"):
            reasons.append("The deadline has passed but the automatic check has not flagged it yet "
                           "(it runs every few minutes). No penalty so far.")
        else:
            reasons.append("Not due yet. No penalty so far.")
    return {"state": state, "credits": credits, "reasons": reasons, "open_kinds": sorted(open_)}


# ---------------------------------------------------------------- whole course file
def compute(items: list[dict], weights: dict, content_active: bool) -> dict:
    """
    items: list of dicts for score_item() plus {submission_id, code, title, sort_order}.
    weights: {id, completeness, timeliness, format, content}.
    Returns a JSON-safe dict (numbers are floats with 2 decimals) that is stored as the snapshot breakdown.
    """
    eff = effective_weights(weights, content_active)
    notes: list[str] = []
    if not content_active:
        notes.append(CONTENT_OFF_NOTE.format(c=int(weights["content"])))

    scored = [(it, score_item(it)) for it in items]
    n = len(scored)
    has_deadline = any(it.get("due_at") is not None for it, _ in scored)
    has_flag = any(f["kind"] in SCORED_KINDS for it, _ in scored for f in it["flags"])

    if n == 0:
        status = NO_ITEMS
        notes.append(NO_ITEMS_NOTE)
    elif not has_deadline and not has_flag:
        status = NO_DEADLINES
        notes.append(NO_DEADLINES_NOTE)
    else:
        status = SCORED

    out_items = []
    parts_out = {}
    total = None
    if status == SCORED:
        points, lost_part = {}, {}
        for p in PARTS:
            avg = sum((r["credits"][p] for _, r in scored), ZERO) / n
            points[p] = q2(eff[p] * avg)
            lost_part[p] = eff[p] - points[p]
        total = sum(points.values(), ZERO)
        item_lost = {}
        for p in PARTS:
            exact = [eff[p] * (ONE - r["credits"][p]) / n for _, r in scored]
            item_lost[p] = apportion(exact, lost_part[p])
        for idx, (it, r) in enumerate(scored):
            out_items.append(_item_out(it, r, {p: item_lost[p][idx] for p in PARTS}))
        for p in PARTS:
            parts_out[p] = {"weight": int(weights[p]), "effective_weight": float(eff[p]),
                            "points": float(points[p]), "lost": float(lost_part[p])}
    else:
        for it, r in scored:
            out_items.append(_item_out(it, r, {p: ZERO for p in PARTS}))
        for p in PARTS:
            parts_out[p] = {"weight": int(weights[p]), "effective_weight": float(eff[p]),
                            "points": None, "lost": None}

    result = {
        "status": status,
        "total": float(total) if total is not None else None,
        "parts": parts_out,
        "weights": {"id": weights.get("id"), **{p: int(weights[p]) for p in PARTS}},
        "content_active": bool(content_active),
        "items_total": n,
        "items_pending": sum(1 for _, r in scored if r["state"] == "PENDING"),
        "items": out_items,
        "notes": notes,
    }
    result["fingerprint"] = fingerprint(result)
    return result


def _item_out(item: dict, r: dict, lost: dict) -> dict:
    return {
        "submission_id": str(item["submission_id"]),
        "code": item["code"],
        "title": item["title"],
        "sort_order": item.get("sort_order"),
        "state": r["state"],
        "due_at": item["due_at"].isoformat() if item.get("due_at") is not None else None,
        "credits": {p: float(r["credits"][p]) for p in PARTS},
        "lost": {p: float(lost[p]) for p in PARTS},
        "reasons": r["reasons"],
        "flags": [{"id": str(f["id"]), "kind": f["kind"], "status": f["status"]}
                  for f in item["flags"] if f["kind"] in SCORED_KINDS],
    }


def fingerprint(result: dict) -> str:
    """Identifies a result by its numbers and item states, not by wording, so wording changes make no new snapshot."""
    core = {
        "status": result["status"],
        "total": result["total"],
        "weights": result["weights"],
        "content_active": result["content_active"],
        "parts": {p: [v["effective_weight"], v["points"]] for p, v in result["parts"].items()},
        "items": [[i["submission_id"], i["state"], sorted(i["credits"].items())] for i in result["items"]],
    }
    return hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
