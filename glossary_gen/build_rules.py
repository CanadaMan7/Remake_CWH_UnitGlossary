"""
build_rules -- everything a player needs to know about *whether and
where* a unit can be built: build limits, required space station /
ground base level, required special structures (shipyards etc.),
required planets, required orbiting units, and whether the unit starts
locked.

Read straight from each unit's resolved XML (so inheritance through
Variant_Of_Existing_Type is honoured), then rendered as one compact
"Build requirements" panel near the top of every card -- instead of the
old separate Required Planets / Special Structures lines at the bottom
of the card, which were easy to miss and showed raw internal names.

Also loads the optional structure-name lookup (--structures-dirs /
--structure-name-overrides) that turns an internal structure Name such
as "U_Shipyard_3" into its in-game name ("Major Construction Yard").
"""

import os
import re
import sys
from html import escape

from .xml_io import first_text, all_texts, safe_parse
from .grouping import clean_required_planets, dedupe_preserve_order, get_affiliations


# ----------------------------------------------------------------------
# Structure names
# ----------------------------------------------------------------------
def load_structure_names(dirs, translations):
    """Scan every *.xml under each of `dirs` (in override order, later
    wins) for elements with a Name attribute, follow their
    Variant_Of_Existing_Type chain to find a Text_ID, and translate it.
    Returns {internal_name: display_name} for every Name whose Text_ID
    translates. Used only to label Required_Special_Structures values,
    so any element type (SpecialStructure, StarBase, ...) is accepted."""
    raw = {}  # name -> (text_id or None, parent or None)
    for d in dirs:
        if not os.path.isdir(d):
            print(f"  ! --structures-dirs: not a directory, skipping: {d}", file=sys.stderr)
            continue
        paths = []
        for root, _dirs, files in os.walk(d):
            for fname in files:
                if fname.lower().endswith(".xml"):
                    paths.append(os.path.join(root, fname))
        for path in sorted(paths):
            root_el = safe_parse(path)
            if root_el is None:
                continue
            for el in root_el.iter():
                name = el.get("Name")
                if not name:
                    continue
                text_id = (el.findtext("Text_ID") or "").strip() or None
                parent = (el.findtext("Variant_Of_Existing_Type") or "").strip() or None
                raw[name] = (text_id, parent)

    def text_id_for(name, depth=0):
        entry = raw.get(name)
        if entry is None or depth > 20:
            return None
        text_id, parent = entry
        return text_id or (text_id_for(parent, depth + 1) if parent else None)

    names = {}
    for name in raw:
        tid = text_id_for(name)
        if tid and tid in translations:
            names[name] = translations[tid]
    return names


def load_structure_name_overrides(path):
    """One `Internal_Name = Display name` per line; blank lines and
    lines starting with # are ignored. Overrides always win over the
    translated name from --structures-dirs."""
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() and value.strip():
                out[key.strip()] = value.strip()
    return out


# ----------------------------------------------------------------------
# Extraction
# ----------------------------------------------------------------------
_SPLIT_RE = re.compile(r"[\s,]+")


def _int_or_none(text):
    try:
        return int(float(text.strip()))
    except (ValueError, AttributeError):
        return None


def _positive(resolved, tag):
    """A limit/level value, or None when it's absent or means "no
    limit" (-1, 0 or anything unparseable)."""
    n = _int_or_none(first_text(resolved, tag, ""))
    return n if n is not None and n > 0 else None


def _yes(resolved, tag):
    return first_text(resolved, tag, "").strip().lower() == "yes"


def extract_build_info(resolved):
    """Everything build-related for one resolved unit, normalised.
    Values that mean "no restriction" are dropped (None / empty), so a
    falsy field always means "nothing to show"."""
    structures = []
    for raw in all_texts(resolved, "Required_Special_Structures"):
        structures.extend(t for t in _SPLIT_RE.split(raw) if t)
    orbiting = []
    for raw in all_texts(resolved, "Required_Orbiting_Units"):
        orbiting.extend(t for t in _SPLIT_RE.split(raw) if t)
    planets_raw = first_text(resolved, "Required_Planets", "")
    tech = _int_or_none(first_text(resolved, "Tech_Level", ""))
    # Engine quirk: for a squadron, Build_Limit_Current_Per_Player counts
    # individual craft, not squadrons -- the real cap in squadrons is
    # the limit divided by the number of Squadron_Units entries
    # (_squadron_size, set by grouping.merge_squadron_members).
    squad_size = resolved.get("_squadron_size") or 0
    # Named hero squadrons (Is_Named_Hero = Yes on the squadron or any
    # craft in it, e.g. Reaper_Z95CVMR_Fighter_Squadron) are capped by a
    # single unit, so their limit is shown as-is, not divided per craft.
    if _yes(resolved, "Is_Named_Hero") or any(
            _yes(r, "Is_Named_Hero") for _n, r in (resolved.get("_squadron_members") or [])):
        squad_size = 0
    has_cost = bool(first_text(resolved, "Build_Cost_Credits", ""))
    return {
        "buildable": has_cost and not (tech is not None and tech >= UNREACHABLE_TECH_LEVEL),
        "limit_current": _positive(resolved, "Build_Limit_Current_Per_Player"),
        "squad_size": squad_size if squad_size > 1 else None,
        "limit_lifetime": _positive(resolved, "Build_Limit_Lifetime_Per_Player"),
        "limit_allies": _positive(resolved, "Build_Limit_Current_For_All_Allies"),
        "star_base": _positive(resolved, "Required_Star_Base_Level"),
        "ground_base": _positive(resolved, "Required_Ground_Base_Level"),
        "tech": tech if tech is not None and tech >= 0 else None,
        "structures": tuple(dedupe_preserve_order(structures)),
        "planets": tuple(clean_required_planets(planets_raw)) if planets_raw else (),
        # Exact Required_Planets tokens (e.g. "Coruscant2_WW") for the
        # Galactic Map, which matches them against campaign planet Names.
        "planets_raw": tuple(dedupe_preserve_order(_SPLIT_RE.split(planets_raw.strip())))
                       if planets_raw.strip() else (),
        "orbiting": tuple(dedupe_preserve_order(orbiting)),
        "locked": _yes(resolved, "Build_Initially_Locked"),
        "slicer": _yes(resolved, "Build_Can_Be_Unlocked_By_Slicer"),
    }


# Tech levels at or above this are never reached in a campaign -- the
# mod uses Tech_Level 99 on garrison/spawned variants that share a
# card with the real buildable unit.
UNREACHABLE_TECH_LEVEL = 99


def _signature(info):
    return tuple(sorted(info.items()))


def has_limit(info):
    return bool(info["limit_current"] or info["limit_lifetime"] or info["limit_allies"])


def has_restriction(info):
    return bool(info["star_base"] or info["ground_base"] or info["structures"]
                or info["planets"] or info["orbiting"] or info["locked"])


# ----------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------
def _chip(label, value, kind, title=""):
    title_attr = f" title='{escape(title)}'" if title else ""
    return (f"<span class='build-chip build-chip--{kind}'{title_attr}>"
            f"<span class='build-chip-label'>{escape(label)}</span>"
            f"<span class='build-chip-value'>{value}</span></span>")


def limit_text(info):
    """Short plain-text summary of the build limit, or "" if none --
    used both in the card chip and the page's limited-units table."""
    parts = []
    if info["limit_current"] and info.get("squad_size"):
        squads = info["limit_current"] // info["squad_size"]
        noun = "squadron" if squads == 1 else "squadrons"
        parts.append(f"{squads} {noun} at a time ({info['limit_current']} craft "
                     f"\u00f7 {info['squad_size']} per squadron)")
    elif info["limit_current"]:
        parts.append(f"{info['limit_current']} at a time")
    if info["limit_lifetime"]:
        parts.append(f"{info['limit_lifetime']} per game")
    if info["limit_allies"]:
        parts.append(f"{info['limit_allies']} across all allies")
    return ", ".join(parts)


def requirement_texts(info, structure_names=None, unit_names=None):
    """Plain-text requirement phrases (no HTML), in display order."""
    structure_names = structure_names or {}
    unit_names = unit_names or {}
    out = []
    if info["tech"] is not None:
        out.append(f"Tech {info['tech']}")
    if info["star_base"]:
        out.append(f"Space station level {info['star_base']}")
    if info["ground_base"]:
        out.append(f"Ground base level {info['ground_base']}")
    if info["structures"]:
        out.append(", ".join(structure_names.get(s, s) for s in info["structures"]))
    if info["planets"]:
        out.append("Only at " + ", ".join(info["planets"]))
    if info["orbiting"]:
        out.append("With " + ", ".join(unit_names.get(u, u) for u in info["orbiting"]) + " in orbit")
    if info["locked"]:
        out.append("Locked at start")
    return out


def _render_one(info, structure_names, unit_names):
    chips = []
    if not info["buildable"]:
        chips.append(_chip("Build", "Not buildable", "muted",
                           "No build cost, or Tech_Level 99, in the XML -- a spawned, garrison "
                           "or story unit rather than one you can queue."))
        return "".join(chips)

    lim = limit_text(info)
    if lim:
        chips.append(_chip("Build limit", escape(lim), "limit",
                           "From Build_Limit_* in the unit XML."))
    else:
        chips.append(_chip("Build limit", "None", "muted"))

    if info["tech"] is not None:
        chips.append(_chip("Tech level", str(info["tech"]), "req"))
    if info["star_base"]:
        chips.append(_chip("Space station", f"Level {info['star_base']}+", "req"))
    if info["ground_base"]:
        chips.append(_chip("Ground base", f"Level {info['ground_base']}+", "req"))
    if info["structures"]:
        labels = []
        for s in info["structures"]:
            nice = structure_names.get(s)
            labels.append(
                f"<span title='{escape(s)}'>{escape(nice)}</span>" if nice else escape(s)
            )
        chips.append(_chip("Requires", ", ".join(labels), "req",
                           "Required_Special_Structures -- hover a name for its internal ID."))
    if info["planets"]:
        chips.append(_chip("Only at", escape(", ".join(info["planets"])), "req"))
    if info["orbiting"]:
        chips.append(_chip("Needs in orbit",
                           escape(", ".join(unit_names.get(u, u) for u in info["orbiting"])), "req"))
    if info["locked"]:
        note = "Unlocked by research or a story event"
        if info["slicer"]:
            note += "; a slicer can also unlock it"
        chips.append(_chip("Locked", "At start", "locked", note + "."))
    return "".join(chips)


def collect_build_lines(members_sorted, group_affiliations):
    """Group a merged card's members by identical build rules.

    Returns a list of {"info", "affs", "names"} dicts, one per distinct
    rule set, in member order. See lines_for_faction for which of
    these a given page actually shows."""
    by_sig = {}
    order = []
    for m in members_sorted:
        info = extract_build_info(m["resolved"])
        sig = _signature(info)
        if sig not in by_sig:
            by_sig[sig] = {"info": info, "affs": [], "names": []}
            order.append(sig)
        affs = get_affiliations(m["resolved"], m["name"]) or group_affiliations or [m["name"]]
        by_sig[sig]["affs"].extend(affs)
        by_sig[sig]["names"].append(m["name"])
    lines = [by_sig[s] for s in order]
    for line in lines:
        line["affs"] = dedupe_preserve_order(line["affs"])
    return lines


def lines_for_faction(lines, faction_key):
    """The lines to show on one faction page.

    1. Keep the lines whose affiliations include the faction
       (case-insensitive); if none do, or faction_key is None, keep all.
    2. Of those, drop variants that can't be built (no cost, or Tech
       99 -- e.g. a garrison copy merged into the same card) whenever
       at least one buildable line remains, so the panel describes the
       version a player actually queues. If nothing is buildable, a
       single "Not buildable" line is kept."""
    selected = lines
    if faction_key:
        matching = [l for l in lines if faction_key in {a.lower() for a in l["affs"]}]
        if matching:
            selected = matching
    buildable = [l for l in selected if l["info"]["buildable"]]
    return buildable if buildable else selected[:1]


def render_build_panel(lines, structure_names=None, unit_names=None, eras=None):
    """Return (html, summary, tokens) for a card's (already
    faction-filtered) build lines.

    One line per distinct rule set; when more than one remains, each
    is captioned with its affiliation(s) and the variants' internal
    names.

    summary: {"buildable", "limited", "restricted", "locked",
    "planets", "limit_text", "requirements"} -- any line counts.
    tokens: space-separated data-build filter tokens.
    eras: era labels for the card (see eras.eras_for_names), shown as
    an "Era" chip on its own line above the build rules; None = no chip."""
    structure_names = structure_names or {}
    unit_names = unit_names or {}

    captions = [", ".join(l["affs"]) for l in lines]
    html_lines = []
    for line, caption in zip(lines, captions):
        cap_html = ""
        if len(lines) > 1:
            # Several variants of this card are buildable by the same
            # faction with different rules -- name each one.
            caption = f"{caption} \u00b7 {', '.join(line['names'])}"
            cap_html = f"<span class='build-line-caption'>{escape(caption)}</span>"
        aff_attr = " ".join(a.lower() for a in line["affs"])
        html_lines.append(
            f"<div class='build-line' data-affs='{escape(aff_attr)}'>{cap_html}"
            f"{_render_one(line['info'], structure_names, unit_names)}</div>"
        )

    infos = [l["info"] for l in lines]
    summary = {
        "buildable": any(i["buildable"] for i in infos),
        "limited": any(i["buildable"] and has_limit(i) for i in infos),
        "restricted": any(i["buildable"] and has_restriction(i) for i in infos),
        "locked": any(i["buildable"] and i["locked"] for i in infos),
        "planets": any(i["planets"] for i in infos),
        "limit_text": " / ".join(dedupe_preserve_order(
            [limit_text(i) for i in infos if i["buildable"] and limit_text(i)])),
        "requirements": dedupe_preserve_order(
            [t for i in infos if i["buildable"] for t in requirement_texts(i, structure_names, unit_names)]),
    }
    tokens = []
    if not summary["buildable"]:
        tokens.append("notbuildable")
    else:
        for key in ("limited", "restricted", "locked", "planets"):
            if summary[key]:
                tokens.append(key)
        if not (summary["limited"] or summary["restricted"]):
            tokens.append("unrestricted")

    era_html = ""
    if eras:
        era_html = ("<div class='build-line build-line--era'>"
                    + _chip("Era", escape(" / ".join(eras)), "era",
                            "From the campaign story files and Unit_Filter scripts: which "
                            "era's campaigns this unit is available in. 'All' = not era-specific.")
                    + "</div>")
    html = (
        "<div class='row-build'>"
        "<div class='row-build-title'>Build requirements</div>"
        f"{era_html}{''.join(html_lines)}</div>"
    )
    return html, summary, " ".join(tokens)
