"""
html_output.py -- top-level page generation: turning the parsed
registry into a set of self-contained glossary HTML documents -- one
intro/splash page plus one page per faction (replacing what used to be
a single giant page with a client-side Affiliation filter, which had
gotten too large to load comfortably).

Covers: candidate filtering (exclusions, squadron/container folding,
passthrough/orphan-modifier hiding, Neutral-affiliation handling),
bucketing candidates into variant groups and calling render.py's
render_group_row for each (exactly once per group, regardless of how
many faction pages it ends up appearing on), sorting rows by class
then cost within each source-file group, distributing rows across
per-faction pages by their own affiliation(s), building each page's
Class/Required-Planets/Unit-Type filter bar (no more Affiliation
filter -- the page itself is the filter now) and the splash page's
links, and the final PAGE_TEMPLATE/SPLASH_TEMPLATE.format() assembly.
"""

import os
import re
from html import escape

from . import xml_io
from .xml_io import first_text, resolve_unit
from .model import has_translated_name, CLASS_FILTER_EXCLUDE
from .grouping import (
    compute_membership, compute_passthrough_names, compute_referenced_parents,
    compute_orphan_planet_modifiers, compute_garrison_spawners,
    variant_group_key_for, pick_primary_member, merge_squadron_members,
    get_affiliations, NEUTRAL_AFFILIATION_VALUES,
)
from .render import render_group_row, icon_src, BUILD_PANEL_PLACEHOLDER, BUILD_ATTR_PLACEHOLDER
from .build_rules import lines_for_faction, render_build_panel
from .render import MAP_START, MAP_END
from .galaxy import build_page_data, map_rules_attr, faction_start_names
from .eras import eras_for_names
from .upgrades import UpgradeIndex, render_upgrade_panel
import json

_MAP_SLOT_RE = re.compile(re.escape(MAP_START) + r".*?" + re.escape(MAP_END), re.S)


def render_map_box(lines, names, start_names, eras=None, upgrade_markers=None):
    """The Galactic Map container for a card (drawn client-side by
    page_script.py from the page's galaxy data), or "" when the card
    is neither buildable nor among the faction's starting forces in
    any campaign. names: the card's variant Names for this faction."""
    if not any(l["info"]["buildable"] for l in lines) and not (set(names) & start_names) \
            and not upgrade_markers:
        return ""
    rules = map_rules_attr(lines)
    upg_note = ""
    if upgrade_markers:
        upg_note = ("<div class='map-note'><span class='lg-dot lg-upg'></span>"
                    "Red worlds: upgrade requirement (see Forms &amp; upgrades).</div>")
    return (
        f"<div class='map-box' data-map='{escape(rules)}' "
        f"data-names='{escape(json.dumps(sorted(names), separators=(',', ':')))}' "
        f"data-eras='{escape(json.dumps(eras or ['All'], separators=(',', ':')))}' "
        f"data-upg='{escape(json.dumps(upgrade_markers or [], separators=(',', ':')))}'>"
        f"<div class='formation-label'>Galactic Map</div>"
        f"<select class='map-campaign' aria-label='Campaign for this map'></select>"
        f"<svg class='galaxy-svg' xmlns='http://www.w3.org/2000/svg'></svg>"
        f"<div class='map-caption'></div>"
        f"<div class='map-hover'>&nbsp;</div>"
        f"<div class='map-note'><span class='lg-dot lg-own'></span>"
        f"Ringed worlds are faction starting worlds.</div>"
        f"<div class='map-note'><span class='lg-dot lg-start'></span>"
        f"Blue worlds: this unit starts there.</div>"
        f"{upg_note}"
        f"</div>"
    )
from .styles import PAGE_CSS
from .page_script import PAGE_SCRIPT
from .page_template import PAGE_TEMPLATE, SPLASH_TEMPLATE

# Sentinel faction key for rows with no affiliation at all (should be
# rare -- see get_affiliations, which normally falls back to a unit's
# own Affiliation tag, including literal "Neutral", before ever
# returning an empty list) -- gets its own page rather than being
# silently dropped, since every card render.py produces has to end up
# SOMEWHERE reachable.
UNAFFILIATED_KEY = "__unaffiliated__"
UNAFFILIATED_LABEL = "Unaffiliated"


def _slugify(text):
    """Turn a faction display label into a safe filename fragment --
    lowercased, non-alphanumeric runs collapsed to a single hyphen,
    leading/trailing hyphens trimmed. Falls back to "page" for the
    degenerate case of a label with no alphanumeric characters at all
    (shouldn't happen for a real faction name, but a derived filename
    should never come out empty)."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "page"


def _faction_filename(output_basename, label):
    """Derive a per-faction page's filename from the splash page's own
    --output filename -- "glossary.html" + "Empire" -> "glossary_empire.html"
    -- so every generated file for one run shares a recognizable prefix
    and lives in the same output directory (see cli.py, which writes
    every returned (filename, html) pair into os.path.dirname(--output))."""
    root, ext = os.path.splitext(output_basename)
    return f"{root}_{_slugify(label)}{ext}"




def _row_sort_key(hp, sort_name):
    """Sort key for row ordering within a file-group: ascending HP
    (Tactical_Health -- the LARGEST value when a card displays more
    than one, e.g. a mixed squadron's comma-joined Hull figures; see
    render_group_row's own "hp" field), with a missing/unparseable HP
    pushed to the very END rather than the front -- (True, 0.0) for a
    missing HP compares greater than every (False, x) tuple no matter
    what x is, so "no HP data" is never conflated with a unit
    genuinely at 0 HP. sort_name (the row's own lowercased display
    label) is the final tie-break, keeping the order fully
    deterministic when HP matches."""
    return (hp is None, hp if hp is not None else 0.0, sort_name)


DEFAULT_TITLE = "EAW Remake: Clone Wars Holdouts, French Fried Taters"


# "Build rules" filter chips, in display order. Only chips that match at
# least one row on the page are shown (see generate_html).
BUILD_FILTER_OPTIONS = [
    ("limited", "Has a build limit"),
    ("restricted", "Has build requirements"),
    ("locked", "Locked at start"),
    ("planets", "Only at specific planets"),
    ("unrestricted", "No limit or requirements"),
    ("notbuildable", "Not buildable"),
]


# Splash page faction rows: (title, affiliation keys in display order).
# Keys are lowercased Affiliation values -- "neutral" is the page shown
# as "Pirates" via faction_images.txt.
SPLASH_FACTION_ROWS = [
    ("Major Factions", ["empire", "rebel", "underworld", "republic", "cis"]),
    ("Minor Factions", ["neutral", "cartels", "mandalorians", "sith", "csa", "hapan", "warlords"]),
]


def _splash_row(title, cards):
    return (
        f"<div class='splash-section-title'>{escape(title)}</div>"
        # One column per card so each row fills the width -- except a
        # short leftover row, which keeps minor-faction-sized cards.
        f"<div class='splash-faction-grid' style='grid-template-columns:repeat({len(cards) if len(cards) >= 5 else 7}, 1fr)'>"
        f"{''.join(cards)}</div>"
    )


GALAXY_CONTROLS = """
<div class="campaign-control">
  <label for="campaign-select">All maps: campaign</label>
  <select id="campaign-select"></select>
  <span class="campaign-legend">
    <span class="lg-dot lg-ok"></span> recruitable
    <span class="lg-dot lg-no"></span> not recruitable
    <span class="lg-dot lg-own"></span> this faction's starting planets
    <span class="lg-dot lg-start"></span> unit starts there
  </span>
  <span class="campaign-hint">Sets every map on the page; each map also has its own campaign menu.</span>
</div>"""


# Era filter chips (value token, label) in display order; tokens match
# the data-era attribute on each row.
ERA_TOKENS = {
    "Clone Wars": "cw", "Galactic Civil War": "gcw",
    "Rise of the Empire": "rote", "All": "all",
}
ERA_FILTER_OPTIONS = [
    ("cw", "Clone Wars"), ("gcw", "Galactic Civil War"),
    ("rote", "Rise of the Empire"), ("all", "All eras"),
]

# "Sort by: Unit Class" order. A card sorts by the first of its classes
# found here; anything else (Transport, SpaceStructure, no class...)
# goes after, then alphabetically.
SORT_CLASS_ORDER = ["fighter", "bomber", "gunship", "corvette", "frigate", "capital"]


def class_sort_rank(classes):
    for c in classes or []:
        if c.strip().lower() in SORT_CLASS_ORDER:
            return SORT_CLASS_ORDER.index(c.strip().lower())
    return len(SORT_CLASS_ORDER)


def tech_sort_value(lines):
    """'Sort by: Tech level' key: the lowest Tech_Level among the card's
    buildable lines for this page; 999 (sorts last) when nothing on the
    card can be built or no tech level is set."""
    techs = [l["info"]["tech"] for l in lines
             if l["info"]["buildable"] and l["info"]["tech"] is not None]
    return min(techs) if techs else 999


def _sort_attr(value):
    """A Sort By number as an HTML attribute value; "" when missing
    (page_script puts those cards last)."""
    if value is None:
        return ""
    return str(int(value)) if float(value).is_integer() else str(value)


def render_limits_summary(limited_rows):
    """A collapsible at-a-glance table of every build-limited unit on
    the page, each name linking down to its card. "" if none."""
    if not limited_rows:
        return ""
    seen = set()
    body = []
    for row in sorted(limited_rows, key=lambda r: r["display_label"].lower()):
        if row["row_id"] in seen:
            continue
        seen.add(row["row_id"])
        b = row["build"]
        reqs = "; ".join(b["requirements"]) or "&mdash;"
        body.append(
            f"<tr><td><a href='#{escape(row['row_id'])}'>{escape(row['display_label'])}</a></td>"
            f"<td class='limits-limit'>{escape(b['limit_text'])}</td>"
            f"<td>{escape(reqs) if b['requirements'] else reqs}</td></tr>"
        )
    return f"""
<details class="limits-summary">
  <summary>Build-limited units <span class="limits-count">({len(body)})</span></summary>
  <table class="limits-table">
    <thead><tr><th>Unit</th><th>Limit</th><th>Requirements</th></tr></thead>
    <tbody>{''.join(body)}</tbody>
  </table>
</details>"""


def generate_html(registry, hardpoints_defs, images_dir, image_ext,
                   require_image=True, exclude_name_substrings=(), exclude_name_suffixes=(),
                   exclude_name_exact=(), translations=None,
                   hide_untranslated=False, projectile_damage=None, affiliation_overrides=None,
                   image_size=110, image_bg_color="#0d0f14", display_name_overrides=None,
                   in_game_images_dir=None, in_game_images=None, output_basename="glossary.html",
                   title=None, description=None, author=None, mod_icon_src=None,
                   gameplay_image_src=None, faction_logos=None, faction_logos_dir=None,
                   custom_unit_order=None, structure_names=None, galaxy=None,
                   eras=None, easter_eggs=None, upgrade_links=None):
    """Returns (pages, unit_order_snapshot_text):

    pages is a list of (filename, html) pairs -- the first is always
    the splash page (filename == output_basename verbatim), followed by
    one page per faction found among the generated cards' affiliations,
    each filename derived from output_basename (see _faction_filename).
    Callers (see cli.py) write every pair into the same output
    directory; nothing here touches the filesystem itself.

    unit_order_snapshot_text is either None (a custom_unit_order WAS
    supplied, so there's nothing to write) or the ready-to-write
    content for --unit-order's own file format, reflecting whatever
    default ordering was actually used -- see load_unit_order and the
    end of this function.

    custom_unit_order: the PARSED {faction_name_lowercased: [(source,
    [name1, ...]), ...]} map from load_unit_order (see --unit-order),
    or None if that flag wasn't given at all -- None (not an empty
    dict) specifically means "no --unit-order flag", which is also
    what decides whether unit_order_snapshot_text gets built above; a
    flag given but pointing at an empty/all-comments file would parse
    to {} instead, which still counts as "given" (skips the snapshot)
    even though it changes no row's order at all this run.

    title/description/author: the splash page's dynamic text (see
    load_splash_config) -- title also replaces the old hardcoded <h1>
    on every per-faction page, not just the splash, so falls back to
    DEFAULT_TITLE rather than going blank when not supplied; description
    and author are splash-only and simply omitted when not given. title
    may itself contain embedded newlines (same multi-line config syntax
    as description/author) -- rendered as a real <br> in the visible
    <h1> on every page, but flattened to a single space-joined line for
    the browser tab's <title>, which can't contain markup.

    mod_icon_src/gameplay_image_src: pre-resolved <img src> paths (see
    resolve_images_base) for the splash page's small mod-identity icon
    and large illustrative gameplay image, each optional.

    faction_logos/faction_logos_dir: {lowercased faction name: filename}
    map (see load_faction_logos) plus the resolved directory base --
    a faction with no entry here just shows its name/count with no
    logo image on its splash card, same graceful-degradation pattern
    as a garrisoned unit with no icon."""
    translations = translations or {}
    projectile_damage = projectile_damage or {}
    display_name_overrides = display_name_overrides or {}
    affiliation_overrides = affiliation_overrides or {}
    in_game_images = in_game_images or {}
    faction_logos = faction_logos or {}
    page_title = title if title else DEFAULT_TITLE
    # Two renderings of the same title: {title} is a single flattened
    # line for <title> in the document head (a plain-text context that
    # can't contain markup -- browsers collapse/ignore a literal
    # newline there rather than breaking the line, hence flattening it
    # to a space explicitly rather than leaving that to chance).
    # {title_html} is for the visible <h1> instead, where a newline in
    # the config value (see load_splash_config -- title supports the
    # same multi-line continuation description/author do) becomes a
    # real <br>, each line escaped individually so escaping never
    # touches the <br> tags themselves.
    page_title_plain = escape(" ".join(page_title.split("\n")))
    page_title_html = "<br>".join(escape(line) for line in page_title.split("\n"))
    cache = {}
    resolved_all = {name: resolve_unit(name, registry, cache) for name in registry}

    squadron_member_names, all_squadron_member_names, container_used_names = compute_membership(resolved_all)
    passthrough_names = compute_passthrough_names(registry, exempt_names=all_squadron_member_names)
    garrison_spawners = compute_garrison_spawners(resolved_all)

    referenced_parents = compute_referenced_parents(registry)
    orphan_planet_modifiers = compute_orphan_planet_modifiers(registry, resolved_all, referenced_parents)
    orphan_planet_modifier_names = {
        mod_name for mods in orphan_planet_modifiers.values() for mod_name, _ in mods
    }

    exclude_subs_lower = [s.lower() for s in exclude_name_substrings]
    exclude_exact_set = set(exclude_name_exact) | xml_io.EXCLUDED_NAMES
    skipped = {"no_image": 0, "name_substring": 0, "name_suffix": 0, "name_exact": 0,
               "squadron_member": 0, "container": 0, "passthrough": 0,
               "untranslated": 0, "planet_modifier": 0}

    candidates = []
    for name in sorted(registry):
        resolved = resolved_all[name]
        tag = resolved.get("_tag", "")

        if name in exclude_exact_set:
            skipped["name_exact"] += 1
            continue
        if any(name.endswith(suf) for suf in exclude_name_suffixes):
            skipped["name_suffix"] += 1
            continue
        name_lower = name.lower()
        if any(sub in name_lower for sub in exclude_subs_lower):
            skipped["name_substring"] += 1
            continue
        # Any candidate referenced by some squadron's own Squadron_Units
        # is folded into that squadron's card (see compute_membership /
        # merge_squadron_members) regardless of its OWN element tag --
        # this mod uses UniqueUnit (not just SpaceUnit) for a squadron
        # member that's also a named hero (e.g. a squadron's flight
        # leader flown alongside its regular UniqueUnit-tagged
        # fighters), so the skip below can't be scoped to SpaceUnit
        # alone without leaving those members shown twice: once
        # (correctly) folded into the squadron's own fighter breakdown,
        # and once again as their own standalone top-level card.
        if name in squadron_member_names:
            skipped["squadron_member"] += 1
            continue
        if tag == "Container" and name in container_used_names:
            skipped["container"] += 1
            continue
        if name in passthrough_names:
            skipped["passthrough"] += 1
            continue
        if name in orphan_planet_modifier_names:
            skipped["planet_modifier"] += 1
            continue

        merged = dict(resolved)
        # Always attempt squadron-member merging, regardless of this
        # candidate's OWN declared XML tag -- this mod has SpaceUnit/
        # UniqueUnit entries (e.g. a faction variant like Consular_R)
        # that inherit Squadron_Units/Create_Team_Type from a Squadron-
        # tagged ancestor via Variant_Of_Existing_Type rather than
        # declaring a Squadron element themselves. Gating this on
        # tag == "Squadron" left such an entry's per-fighter Hull/
        # Shields/HardPoints/AI Combat Power (and its formation
        # diagram) missing entirely, since none of that ever got
        # pulled in. merge_squadron_members is a safe no-op when
        # Squadron_Units/Create_Team_Type aren't present at all (an
        # ordinary standalone unit), so calling it unconditionally
        # here doesn't change anything for those.
        merged = merge_squadron_members(merged, resolved_all)

        # Required_Planets comes ONLY from this unit's own
        # Variant_Of_Existing_Type chain (already in `resolved`). A bare
        # *_Required_Planets node that merely shares this unit's parent
        # is a sibling, not an ancestor, so the game never applies it
        # here -- see compute_orphan_planet_modifiers.

        if hide_untranslated and translations and not has_translated_name(merged, translations):
            skipped["untranslated"] += 1
            continue

        if name in affiliation_overrides:
            # Manual override wins outright -- skip every other
            # affiliation signal (own tag, spawner inheritance, hero
            # exemption), since specifying an affiliation by hand is
            # itself a declaration that this unit should be shown,
            # under exactly this affiliation. See
            # load_affiliation_overrides / --affiliation-overrides.
            merged["_effective_affiliations"] = affiliation_overrides[name]
        else:
            own_affiliation = first_text(merged, "Affiliation", "")
            is_neutral = own_affiliation.strip().lower() in NEUTRAL_AFFILIATION_VALUES
            spawner_affs = garrison_spawners.get(name, [])
            if is_neutral and spawner_affs:
                # Display it under the affiliation(s) of whatever spawns
                # it as garrison rather than "Neutral" -- a real signal
                # read directly off other units' own spawn tags, not a
                # guess. A Neutral unit with no spawner (or any other
                # unit) is otherwise shown as-is, under whatever
                # Affiliation its own XML entry declares (including
                # "Neutral" itself) -- units are never hidden based on
                # affiliation.
                merged["_effective_affiliations"] = spawner_affs
            # else: fall through to the unit's own Affiliation tag, read
            # directly by get_affiliations -- nothing is hidden here.

        icon = first_text(merged, "Icon_Name")
        if require_image and not icon:
            skipped["no_image"] += 1
            continue

        img_src = icon_src(icon, images_dir, image_ext) if icon else None
        candidates.append({"name": name, "resolved": merged, "icon_src": img_src})

    garrison_referenced_names = set(garrison_spawners.keys())
    variant_groups = {}
    order = []
    for c in candidates:
        key = variant_group_key_for(c)
        if key not in variant_groups:
            variant_groups[key] = []
            order.append(key)
        variant_groups[key].append(c)

    # Render every merged group's row EXACTLY ONCE here, regardless of
    # how many faction pages it ends up appearing on below -- a unit
    # buildable by several factions (a shared hero, say) shows on each
    # of their pages, but its HTML is only ever generated a single
    # time. Each row's own affiliation list (row_result["affiliations"])
    # is what the distribution pass right after this loop uses to
    # decide which page(s) it lands on; it's collected here rather than
    # recomputed later since render_group_row already computed it.
    def _render(members):
        return render_group_row(
            members, hardpoints_defs, translations, projectile_damage,
            images_dir=images_dir, image_ext=image_ext, image_size=image_size,
            display_name_overrides=display_name_overrides, resolved_all=resolved_all,
            in_game_images_dir=in_game_images_dir, in_game_images=in_game_images,
            structure_names=structure_names,
        )

    all_rows = []
    for key in order:
        members = variant_groups[key]
        group_primary = pick_primary_member(members)[0]
        primary_source = group_primary["resolved"].get("_source", "")
        row_result = _render(members)
        sort_key = _row_sort_key(row_result["hp"], row_result["sort_name"])
        all_rows.append({
            "html": row_result["html"],
            "sort_key": sort_key,
            "source": primary_source,
            "affiliations": row_result["affiliations"],
            "classes": row_result["classes"],
            "has_planets": row_result["has_planets"],
            "is_hero": row_result["is_hero"],
            # The ordering key for --unit-order is the group's
            # pick_primary_member Name -- stable regardless of which
            # member a given faction page ends up displaying.
            "raw_name": group_primary["name"],
            "members": members,
            "row_id": row_result["row_id"],
            "display_label": row_result["display_label"],
            "build_lines": row_result["build_lines"],
            "orbit_names": row_result["orbit_names"],
            "sort_cost": row_result["sort_cost"],
            "sort_pop": row_result["sort_pop"],
            "sort_ai_power": row_result["sort_ai_power"],
        })

    all_sources = {row["source"] for row in all_rows}

    # Distribute rows across per-faction pages -- a row with more than
    # one affiliation appears, unchanged, on each of those factions'
    # own pages (this replaces the old single-page Affiliation filter:
    # what used to be "check the Empire chip to show Empire rows" is
    # now "open the Empire page"). A row with no affiliation at all
    # (rare -- see get_affiliations) goes on its own "Unaffiliated"
    # page rather than being silently dropped.
    faction_rows = {}     # lowercased key -> list of row dicts
    faction_display = {}  # lowercased key -> display label
    faction_order = []
    for row in all_rows:
        affs = row["affiliations"] or [None]
        for a in affs:
            key = a.lower() if a else UNAFFILIATED_KEY
            if key not in faction_rows:
                faction_rows[key] = []
                faction_display[key] = a if a else UNAFFILIATED_LABEL
                faction_order.append(key)
            faction_rows[key].append(row)

    def render_filter_group(title, group_key, options):
        """options: list of (value, label) pairs, already sorted for
        display. Renders "" if there are no options at all -- e.g. no
        row had a CategoryMask, so a Class filter with zero choices
        would just be dead UI."""
        if not options:
            return ""
        chips = "".join(
            f"<label class='chip'><input type='checkbox' data-filter-group='{escape(group_key)}' "
            f"value='{escape(value)}'> {escape(label)}</label>"
            for value, label in options
        )
        return f"""
<div class="filter-group">
  <div class="filter-group-title">{escape(title)}</div>
  <div class="filter-chips">{chips}</div>
</div>"""

    # The gallery/container width scales with image_size so multiple
    # images in a squadron's fighter gallery (see render_group_row)
    # still get room to sit side by side rather than immediately
    # wrapping to one column each when the person scales images up --
    # floor of 260px matches the original fixed size for the default.
    image_container_max = max(260, image_size * 2 + 40)
    # PAGE_CSS is its own template (see styles.py) needing the same
    # image_size/image_container_max/image_bg_color fill-in -- rendered
    # once here (identical across every page from this run) into a
    # plain string, then dropped into each template's {styles} slot.
    # PAGE_SCRIPT has no placeholders of its own, so it's passed
    # through as-is; SPLASH_TEMPLATE doesn't use it at all.
    rendered_css = PAGE_CSS.format(
        image_size=image_size, image_container_max=image_container_max,
        image_bg_color=image_bg_color,
    )

    pages = []          # (filename, html) -- splash page prepended at the end
    splash_link_info = []  # (label, filename, row_count), for the splash page
    # Collected only when custom_unit_order is None (i.e. --unit-order
    # wasn't given at all) -- see the write-out this function returns
    # at the very end. faction_display[key] (not the lowercased key
    # itself) is used so the written file's section headers read as
    # real faction names.
    unit_order_snapshot = {}

    def _default_ordered_sources(rows_by_source_subset, sources_subset):
        """Default file-group section order: ascending by the LARGEST
        HP entry found anywhere in that source file (each row tuple's
        middle element is the (hp_is_none, hp_or_0.0, sort_name) tuple
        from _row_sort_key), missing-HP files sorted last, alphabetical
        as the final tie-break."""
        group_max_hp = {}
        for source in sources_subset:
            known_hps = [sk[1] for _html, sk, _raw_name in rows_by_source_subset[source] if not sk[0]]
            group_max_hp[source] = max(known_hps) if known_hps else None
        return sorted(
            sorted(sources_subset),
            key=lambda source: (group_max_hp[source] is None,
                                 group_max_hp[source] if group_max_hp[source] is not None else 0.0),
        )

    faction_view_cache = {}
    upgrade_index = (UpgradeIndex(upgrade_links, resolved_all, translations, display_name_overrides)
                     if upgrade_links else None)

    def _faction_view(base_row, faction_key):
        """base_row re-rendered from only the members whose own
        affiliation includes faction_key, or base_row unchanged when
        that's every member (or none of them, or no faction)."""
        if not faction_key:
            return base_row
        members = base_row["members"]
        subset = [m for m in members
                  if faction_key in {a.lower() for a in get_affiliations(m["resolved"], m["name"])}]
        if not subset or len(subset) == len(members):
            return base_row
        cache_key = tuple(sorted(m["name"] for m in subset))
        if cache_key not in faction_view_cache:
            faction_view_cache[cache_key] = _render(subset)
        r = faction_view_cache[cache_key]
        row = dict(base_row)
        row.update({
            "html": r["html"], "row_id": r["row_id"], "display_label": r["display_label"],
            "build_lines": r["build_lines"], "orbit_names": r["orbit_names"],
            "classes": r["classes"], "is_hero": r["is_hero"],
            "sort_cost": r["sort_cost"], "sort_pop": r["sort_pop"],
            "sort_ai_power": r["sort_ai_power"],
        })
        return row

    for key in sorted(faction_order, key=lambda k: faction_display[k].lower()):
        # Fill each card's build panel with THIS faction's rules (a
        # card shared by several factions shows only the rules for the
        # page you're on -- see build_rules.lines_for_faction).
        faction_key = None if key == UNAFFILIATED_KEY else key
        rows = []
        page_unit_names = set()
        start_names = faction_start_names(galaxy, faction_key) if galaxy else set()
        # Every variant Name on this page -> its card's anchor, so the
        # Forms & upgrades panel can link to the other forms.
        page_row_ids = {}
        for base_row in faction_rows[key]:
            view = _faction_view(base_row, faction_key)
            for line in view["build_lines"]:
                for n in line["names"]:
                    page_row_ids.setdefault(n.lower(), view["row_id"])
        for base_row in faction_rows[key]:
            # A card merging several factions' variants shows only the
            # variants belonging to this page's faction (title, images,
            # stats, "variants merged" line) -- e.g. the Rebel page's
            # Delta-7 doesn't list the Empire-only garrison copy.
            base_row = _faction_view(base_row, faction_key)
            lines = lines_for_faction(base_row["build_lines"], faction_key)
            # This faction's variant Names on the card (all of them if
            # none is affiliated with it) -- for the Era chip, the map's
            # starting-forces lookup and the Easter Egg check.
            card_names = [n for l in base_row["build_lines"]
                          if not faction_key or faction_key in {a.lower() for a in l["affs"]}
                          for n in l["names"]] or [n for l in base_row["build_lines"] for n in l["names"]]
            card_eras = eras_for_names(card_names, eras) if eras is not None else None
            panel_html, build_summary, build_tokens = render_build_panel(
                lines, structure_names=structure_names, unit_names=base_row["orbit_names"],
                eras=card_eras)
            upgrade_html, upgrade_markers = render_upgrade_panel(
                upgrade_index, card_names, structure_names or {}, page_row_ids)
            panel_html += upgrade_html
            row = dict(base_row)
            row_html = (base_row["html"]
                        .replace(BUILD_PANEL_PLACEHOLDER, panel_html)
                        .replace(BUILD_ATTR_PLACEHOLDER, build_tokens))
            map_html = ""
            if galaxy:
                map_html = render_map_box(lines, card_names, start_names,
                                          eras_for_names(card_names, eras) if eras is not None else None,
                                          upgrade_markers)
                if map_html:
                    page_unit_names.update(card_names)
            if map_html:
                row_html = _MAP_SLOT_RE.sub(lambda _m: map_html, row_html)
            else:
                row_html = row_html.replace(MAP_START, "").replace(MAP_END, "")
            # Easter eggs (easter_eggs.txt) get their own Unit Type
            # instead of Unique Hero / regular.
            row["is_easter_egg"] = bool(easter_eggs) and any(
                m["name"] in easter_eggs for m in base_row["members"])
            if row["is_easter_egg"]:
                # Hidden until the Easter Egg filter is ticked (inline
                # display:none so it stays hidden even before the page
                # script runs) -- see page_script's applyFilter.
                row_html = re.sub(r'data-unit-kind="\w+"', 'data-unit-kind="easteregg" style="display:none"',
                                  row_html, count=1)
                row["is_hero"] = False
            # Era filter tokens and Sort By keys (see page_script).
            row["era_tokens"] = " ".join(ERA_TOKENS[e] for e in (card_eras or []))
            row_html = row_html.replace(
                ' data-build="',
                f' data-era="{row["era_tokens"]}" data-sort-name="{escape(base_row["display_label"].lower())}"'
                f' data-class-rank="{class_sort_rank(base_row["classes"])}"'
                f' data-tech="{tech_sort_value(lines)}"'
                f' data-cost="{_sort_attr(base_row.get("sort_cost"))}"'
                f' data-pop="{_sort_attr(base_row.get("sort_pop"))}"'
                f' data-ai-power="{_sort_attr(base_row.get("sort_ai_power"))}" data-build="', 1)
            row["html"] = row_html
            row["build"] = build_summary
            row["build_tokens"] = build_tokens
            rows.append(row)

        # Bucket THIS faction's rows by source file, same reasoning as
        # the old single-page version: entries defined in the same XML
        # file are shown together, in a section titled with that file's
        # relative path. Each bucket holds (html, sort_key, raw_name)
        # triples -- raw_name (the row's primary member's own XML Name)
        # is what a --unit-order file's comma-separated lists are
        # matched against below; it's otherwise unused except for
        # building the unit_order_snapshot at the end.
        rows_by_source = {}
        source_order = []
        class_display = {}
        any_has_planets = False
        any_hero = False
        build_token_seen = set()
        limited_rows = []
        any_easter_egg = False
        era_token_seen = set()
        eggs_by_source = {}  # kept out of visible counts so they stay a surprise
        for row in rows:
            if row["source"] not in rows_by_source:
                rows_by_source[row["source"]] = []
                source_order.append(row["source"])
            rows_by_source[row["source"]].append((row["html"], row["sort_key"], row["raw_name"]))
            for c in row["classes"]:
                class_display.setdefault(c.lower(), c)
            if row["has_planets"]:
                any_has_planets = True
            if row["is_hero"]:
                any_hero = True
            if row.get("is_easter_egg"):
                any_easter_egg = True
            build_token_seen.update(row["build_tokens"].split())
            era_token_seen.update(row["era_tokens"].split())
            if row.get("is_easter_egg"):
                eggs_by_source[row["source"]] = eggs_by_source.get(row["source"], 0) + 1
            elif row["build"]["limited"]:
                limited_rows.append(row)

        # If --unit-order mentions this faction at all, its explicit
        # order takes priority; anything it DOESN'T mention (a row
        # within a source file it does cover, or an entire source file
        # it doesn't) falls back to the normal default (ascending HP)
        # order, appended after everything the file DOES specify --
        # see load_unit_order's own docstring for the full rationale.
        custom_for_faction = (custom_unit_order or {}).get(key)
        if custom_for_faction:
            custom_name_order = {source: names for source, names in custom_for_faction}
            for source, rows_list in rows_by_source.items():
                name_order = custom_name_order.get(source)
                if not name_order:
                    rows_list.sort(key=lambda item: item[1])
                    continue
                name_index = {name: i for i, name in enumerate(name_order)}
                rows_list.sort(key=lambda item: (
                    item[2] not in name_index, name_index.get(item[2], 0), item[1],
                ))
            custom_source_order = [s for s, _names in custom_for_faction if s in rows_by_source]
            leftover_sources = [s for s in source_order if s not in custom_source_order]
            ordered_sources = custom_source_order + _default_ordered_sources(
                {s: rows_by_source[s] for s in leftover_sources}, leftover_sources)
        else:
            for source in rows_by_source:
                rows_by_source[source].sort(key=lambda item: item[1])
            ordered_sources = _default_ordered_sources(rows_by_source, source_order)

        if custom_unit_order is None:
            unit_order_snapshot[faction_display[key]] = [
                (source, [raw_name for _html, _sk, raw_name in rows_by_source[source]])
                for source in ordered_sources
            ]

        group_sections = []
        for source in ordered_sources:
            rows_html = [html for html, _sk, _raw_name in rows_by_source[source]]
            group_sections.append(f"""
<div class="file-group">
  <div class="file-group-title">{escape(source)}<span class="file-group-count"> &middot; {len(rows_html) - eggs_by_source.get(source, 0)} entries</span></div>
  <div class="rows">
{''.join(rows_html)}
  </div>
</div>""")

        # Class/Required-Planets/Unit-Type filter options are computed
        # PER FACTION PAGE now (only from what's actually on that page),
        # not globally -- there's no more Affiliation filter group at
        # all, since the page itself already is the affiliation filter.
        class_options = sorted(
            ((v, label) for v, label in class_display.items() if v not in CLASS_FILTER_EXCLUDE),
            key=lambda kv: kv[1].lower(),
        )
        unit_kind_options = [("hero", "Unique Hero")] if any_hero else []
        if any_easter_egg:
            unit_kind_options.append(("easteregg", "Easter Egg"))
        build_options = [
            (token, label) for token, label in BUILD_FILTER_OPTIONS if token in build_token_seen
        ]

        era_options = [(t, label) for t, label in ERA_FILTER_OPTIONS if t in era_token_seen]

        filters_html = "".join([
            render_filter_group("Era", "era", era_options),
            render_filter_group("Build rules", "build", build_options),
            render_filter_group("Class", "class", class_options),
            render_filter_group("Unit Type", "unitkind", unit_kind_options),
        ])
        if filters_html:
            filters_html = f'<div class="filters">{filters_html}<button type="button" id="clear-filters" class="clear-filters">Clear filters</button></div>'

        filename = _faction_filename(output_basename, faction_display[key])
        page_html = PAGE_TEMPLATE.format(
            home_href=escape(output_basename),
            groups="\n".join(group_sections), count=len(rows) - sum(eggs_by_source.values()),
            filters=filters_html,
            limits_summary=render_limits_summary(limited_rows),
            galaxy_controls=GALAXY_CONTROLS if galaxy else "",
            galaxy_data=(
                f'<script id="galaxy-data" type="application/json">'
                f'{build_page_data(galaxy, faction_key, page_unit_names)}</script>' if galaxy else ""
            ),
            styles=rendered_css, script=PAGE_SCRIPT, title=page_title_plain, title_html=page_title_html,
        )
        pages.append((filename, page_html))
        splash_link_info.append((faction_display[key], filename, len(rows) - sum(eggs_by_source.values())))

    # Splash page header: mod icon / title / author, each optional --
    # see the module docstring/generate_html's own docstring for how
    # None vs. a real value is decided by the caller (cli.py).
    mod_icon_html = (
        f"  <img class='splash-mod-icon' src='{escape(mod_icon_src)}' alt='Mod icon'>"
        if mod_icon_src else ""
    )
    # author/description are NOT escaped -- unlike every other piece of
    # user-supplied text in this tool (unit names, descriptions pulled
    # from the game's own XML, etc.), these two come from a config file
    # the mod author writes for THIS purpose, so raw HTML -- most
    # usefully a hyperlink, e.g. <a href="https://...">my site</a> --
    # is taken at face value and rendered as-is rather than escaped to
    # literal text. A literal "<" or "&" the author wants to show
    # as-is needs its own HTML entity (&lt; / &amp;) same as writing
    # any other HTML by hand. title is NOT given this treatment -- it
    # also lands inside <title> in the document head, where markup
    # doesn't apply and would just corrupt the tag.
    author_html = (
        f"    <div class='splash-author'>{author}</div>" if author else ""
    )
    # description can be multiple paragraphs (see load_splash_config) --
    # split on a blank line the same way resolve_description splits an
    # in-game unit's own flavor text at TEXT_LINE, each becoming its
    # own <p>. Not escaped, for the same reason as author above.
    if description:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", description) if p.strip()]
        description_html = (
            f"<div class='splash-description'>"
            f"{''.join(f'<p>{p}</p>' for p in paragraphs)}</div>"
        )
    else:
        description_html = ""
    gameplay_image_html = (
        f"<div class='splash-gameplay-image'><img src='{escape(gameplay_image_src)}' "
        f"alt='Gameplay screenshot'></div>" if gameplay_image_src else ""
    )

    # One card per faction: a large logo image (if --faction-logos has
    # an entry for this faction, matched case-insensitively) above the
    # name and entry count. A faction with no configured logo just
    # shows its name/count with no image slot at all, rather than a
    # broken-image icon. The card's NAME text can also be overridden
    # independently of the logo (see load_faction_logos) -- the actual
    # affiliation value (label/fname, used for the href and the lookup
    # key itself) is untouched either way; only what's DISPLAYED on
    # this one card changes.
    cards_by_key = {}
    for label, fname, count in sorted(splash_link_info, key=lambda t: t[0].lower()):
        logo_filename, display_name_override = faction_logos.get(label.lower(), (None, None))
        display_label = display_name_override or label
        logo_html = ""
        if logo_filename and faction_logos_dir:
            logo_src = f"{faction_logos_dir}/{logo_filename}"
            logo_html = (
                f"<div class='splash-faction-logo-wrap'>"
                f"<img class='splash-faction-logo' src='{escape(logo_src)}' alt='{escape(display_label)}'></div>"
            )
        cards_by_key[label.lower()] = (
            f"<a class='splash-faction-card' href='{escape(fname)}'>"
            f"{logo_html}"
            f"<div class='splash-faction-name'>{escape(display_label)}</div>"
            f"<div class='splash-faction-count'>{count} entries</div>"
            f"</a>"
        )

    # Major factions on one row, minor factions on the next, each in a
    # fixed order (SPLASH_FACTION_ROWS); any faction page not listed
    # there (e.g. Unaffiliated) goes in a final "Other" row.
    faction_rows_html = []
    placed = set()
    for title, keys in SPLASH_FACTION_ROWS:
        cards = [cards_by_key[k] for k in keys if k in cards_by_key]
        placed.update(keys)
        if cards:
            faction_rows_html.append(_splash_row(title, cards))
    leftovers = [c for k, c in cards_by_key.items() if k not in placed]
    if leftovers:
        faction_rows_html.append(_splash_row("Other", leftovers))
    faction_cards = faction_rows_html

    splash_html = SPLASH_TEMPLATE.format(
        styles=rendered_css, title=page_title_plain, title_html=page_title_html,
        mod_icon=mod_icon_html, author=author_html,
        description=description_html, gameplay_image=gameplay_image_html,
        faction_cards="".join(faction_cards),
    )
    pages.insert(0, (output_basename, splash_html))

    print(f"Skipped -- no image: {skipped['no_image']}, name substring: {skipped['name_substring']}, "
          f"name suffix: {skipped['name_suffix']}, exact name: {skipped['name_exact']}, "
          f"folded into squadron: {skipped['squadron_member']}, "
          f"folded container: {skipped['container']}, passthrough template: {skipped['passthrough']}, "
          f"bare planet modifier: {skipped['planet_modifier']}, untranslated: {skipped['untranslated']}")
    print(f"{len(candidates)} candidate entries merged into {len(all_rows)} glossary cards "
          f"({len(candidates) - len(all_rows)} merged away by variant grouping) "
          f"across {len(all_sources)} source file(s).")
    if garrison_referenced_names:
        print(f"{len(garrison_referenced_names)} name(s) referenced as garrison spawns elsewhere "
              f"(Neutral-affiliation ones among them are shown under their spawner's affiliation "
              f"instead of 'Neutral').")
    print(f"Split across {len(splash_link_info)} faction page(s) plus 1 splash page: " +
          ", ".join(f"{label} ({count})" for label, _fname, count in
                     sorted(splash_link_info, key=lambda t: t[0].lower())))

    # unit_order_snapshot_text is the ready-to-write content for
    # --unit-order's own file format (see load_unit_order) -- built
    # only when custom_unit_order is None (i.e. --unit-order wasn't
    # given at all), reflecting the default order actually used above.
    # None here means "nothing to write" (a custom order WAS supplied,
    # so this run is in consume-not-produce mode) -- callers (cli.py)
    # decide the actual output path and do the file write themselves,
    # matching how every other page in `pages` is handled.
    unit_order_snapshot_text = None
    if custom_unit_order is None:
        lines = []
        for faction_label in sorted(unit_order_snapshot, key=str.lower):
            lines.append(f"[{faction_label}]")
            for source, names in unit_order_snapshot[faction_label]:
                lines.append(f"{source}={', '.join(names)}")
            lines.append("")
        unit_order_snapshot_text = "\n".join(lines).rstrip("\n") + "\n"

    return pages, unit_order_snapshot_text

