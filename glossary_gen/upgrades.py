"""
upgrades -- hero / unit upgrade chains (e.g. Retaliation -> Retaliation_II),
shown as a "Forms & upgrades" panel on each card involved, with the
upgrade's own requirements, plus red "upgrade location" markers on the
Galactic Map when an upgrade is planet-restricted.

Source of truth for WHAT upgrades into what: Upgrade_Units.lua (Data\\
Scripts\\GameObject), used by both Remake 4.0 (whose story sandboxes
route their upgrade objects to it) and Clone Wars Holdouts (whose
*_HeroUpgrades sandboxes do the same). Each branch reads:

    elseif Object.Get_Type().Get_Name() == "RETALIATION_UPGRADE" then
        Upgrade_Unit(planet, player, "Retaliation", "Retaliation_II")

i.e. building the upgrade object RETALIATION_UPGRADE turns Retaliation
into Retaliation_II. Names starting with REPAIR_ are damage-state
repairs (e.g. Executor P2 -> P1) and are labelled as such.

Requirements come from the upgrade object's own entry in the unit XML
(e.g. <UniqueUnit Name="RETALIATION_UPGRADE"> in Units_Hero_Minors_
Republic_MZsinj.XML), read through the normal resolved registry so
inherited values count: Tech_Level, Required_Star_Base_Level,
Required_Special_Structures, Required_Planets, Required_Orbiting_Units
(usually the hero itself -- it has to be at the planet; squadron
upgrades often don't need this) and Build_Cost_Credits.
"""

import os
import re
from html import escape

from .xml_io import first_text, all_texts
from .model import resolve_display_name
from .build_rules import extract_build_info

_UPGRADE_RE = re.compile(
    r'Get_Name\(\)\s*==\s*"([^"]+)"\s*then\s*'
    r'Upgrade_Unit\(\s*[^,]+,\s*[^,]+,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)',
    re.S,
)


def load_upgrade_links(script_dirs, filename="Upgrade_Units.lua"):
    """[{"upgrade", "from", "to", "repair"}] from the highest-priority
    copy of Upgrade_Units.lua in script_dirs (later dirs win, as with
    every other override in this generator)."""
    path = None
    for d in script_dirs:
        try:
            for entry in os.listdir(d):
                if entry.lower() == filename.lower():
                    path = os.path.join(d, entry)
        except OSError:
            pass
    if not path:
        return []
    with open(path, encoding="utf-8", errors="replace") as f:
        text = re.sub(r"--[^\n]*", "", f.read())
    links = []
    for upgrade, src, dst in _UPGRADE_RE.findall(text):
        links.append({
            "upgrade": upgrade, "from": src, "to": dst,
            "repair": upgrade.lower().startswith("repair_"),
        })
    return links


class UpgradeIndex:
    """Lookups over the links plus everything needed to describe them."""

    def __init__(self, links, resolved_all, translations, display_name_overrides=None):
        self.links = links
        self.resolved_all = resolved_all
        self.translations = translations
        self.overrides = display_name_overrides
        self._lower = {n.lower(): n for n in resolved_all}
        self.by_from = {}
        self.by_to = {}
        for link in links:
            self.by_from.setdefault(link["from"].lower(), []).append(link)
            self.by_to.setdefault(link["to"].lower(), []).append(link)

    # -- names ----------------------------------------------------------
    def resolved(self, name):
        real = self._lower.get(name.lower())
        return self.resolved_all.get(real) if real else None

    def label(self, name):
        r = self.resolved(name)
        if r is None:
            return name.replace("_", " ")
        return resolve_display_name(r, self._lower[name.lower()], self.translations, self.overrides)

    # -- per card -------------------------------------------------------
    def links_for(self, names):
        """(incoming, outgoing) links touching any of the card's names."""
        incoming, outgoing, seen = [], [], set()
        for n in names:
            for link in self.by_to.get(n.lower(), []):
                if id(link) not in seen:
                    incoming.append(link)
                    seen.add(id(link))
            for link in self.by_from.get(n.lower(), []):
                if id(link) not in seen:
                    outgoing.append(link)
                    seen.add(id(link))
        return incoming, outgoing

    def chain(self, names):
        """Upgrade (not repair) forms connected to the card, as levels:
        [[root forms], [next forms], ...] -- branches share a level."""
        nodes, frontier = set(), {n.lower() for n in names}
        while frontier:  # collect the whole connected component
            n = frontier.pop()
            if n in nodes:
                continue
            nodes.add(n)
            for link in self.by_from.get(n, []) + self.by_to.get(n, []):
                if not link["repair"]:
                    frontier.update({link["from"].lower(), link["to"].lower()})
        if len(nodes) < 2:
            return []
        parents = {n: [l["from"].lower() for l in self.by_to.get(n, []) if not l["repair"]]
                   for n in nodes}
        level = {}

        def depth(n, seen=()):
            if n in level:
                return level[n]
            ps = [p for p in parents[n] if p in nodes and p not in seen]
            level[n] = 0 if not ps else 1 + max(depth(p, seen + (n,)) for p in ps)
            return level[n]

        for n in nodes:
            depth(n)
        out = [[] for _ in range(max(level.values()) + 1)]
        original = {}
        for link in self.links:
            original[link["from"].lower()] = link["from"]
            original[link["to"].lower()] = link["to"]
        for n in sorted(nodes, key=lambda x: original.get(x, x)):
            out[level[n]].append(original.get(n, n))
        return out

    def requirements(self, link):
        """Info about the upgrade object itself: build_rules-style info
        plus cost and whether the source unit must be in orbit."""
        r = self.resolved(link["upgrade"])
        if r is None:
            return None
        info = extract_build_info(r)
        cost = first_text(r, "Build_Cost_Credits", "").strip()
        orbit = []
        for raw in all_texts(r, "Required_Orbiting_Units"):
            orbit.extend(t for t in re.split(r"[\s,]+", raw) if t)
        return {
            "info": info,
            "cost": cost,
            "orbit": orbit,
            "upgrade_label": self.label(link["upgrade"]),
        }


def _chip(label, value_html, kind, title=""):
    title_attr = f" title='{escape(title)}'" if title else ""
    return (f"<span class='build-chip build-chip--{kind}'{title_attr}>"
            f"<span class='build-chip-label'>{escape(label)}</span>"
            f"<span class='build-chip-value'>{value_html}</span></span>")


def render_upgrade_panel(index, names, structure_names, row_ids):
    """(html, map_markers) for a card. html is "" when the card isn't
    part of any upgrade chain. map_markers: [{"p": [planet Names],
    "label": str}] for planet-restricted upgrades into or out of this
    card, drawn red on its Galactic Map. row_ids: {unit Name lower ->
    card anchor id} for cards on this page, to link the other forms."""
    if index is None:
        return "", []
    incoming, outgoing = index.links_for(names)
    if not incoming and not outgoing:
        return "", []
    own = {n.lower() for n in names}

    def link_name(name):
        label = escape(index.label(name))
        rid = row_ids.get(name.lower())
        if name.lower() in own:
            return f"<strong>{label}</strong>"
        return f"<a href='#{escape(rid)}'>{label}</a>" if rid else label

    parts = []
    chain = index.chain(names)
    if chain:
        steps = " <span class='upg-arrow'>&rarr;</span> ".join(
            " / ".join(link_name(n) for n in level) for level in chain)
        parts.append(f"<div class='upg-chain'><span class='build-chip-label'>Forms</span> {steps}</div>")

    markers = []
    for direction, links in (("from", incoming), ("to", outgoing)):
        for link in links:
            req = index.requirements(link)
            other = link["from"] if direction == "from" else link["to"]
            verb = ("Repaired from" if direction == "from" else "Repairs to") if link["repair"] \
                else ("Upgraded from" if direction == "from" else "Upgrades to")
            head = f"<div class='upg-head'>{verb} {link_name(other)}"
            # "via <upgrade button name>" -- skipped when the in-game name
            # just repeats a form's name (e.g. "Upgrades to Home One via
            # Home One"); the internal ID is on hover either way.
            if req and req["upgrade_label"] not in (index.label(link["from"]), index.label(link["to"])):
                head += (f" <span class='upg-via' title='{escape(link['upgrade'])}'>"
                         f"via {escape(req['upgrade_label'])}</span>")
            head += "</div>"
            chips = []
            if req:
                info = req["info"]
                if req["cost"]:
                    chips.append(_chip("Cost", escape(req["cost"]), "req"))
                if info["tech"] is not None:
                    chips.append(_chip("Tech level", str(info["tech"]), "req"))
                if info["star_base"]:
                    chips.append(_chip("Space station", f"Level {info['star_base']}+", "req"))
                if info["ground_base"]:
                    chips.append(_chip("Ground base", f"Level {info['ground_base']}+", "req"))
                if info["structures"]:
                    chips.append(_chip("Requires", escape(", ".join(
                        structure_names.get(s, s) for s in info["structures"])), "req"))
                if req["orbit"]:
                    chips.append(_chip("Needs in orbit", escape(", ".join(
                        index.label(u) for u in req["orbit"])), "req",
                        "Required_Orbiting_Units: this unit has to be in orbit where the upgrade is built."))
                if info["planets"]:
                    chips.append(_chip("Only at", escape(", ".join(info["planets"])), "upg-planet",
                                       "Upgrade requirement -- shown in red on the Galactic Map."))
                    markers.append({"p": list(info["planets_raw"]),
                                    "label": f"{verb} {index.label(other)}"})
            else:
                chips.append(_chip("Requirements", "not found in the unit XML", "muted"))
            parts.append(f"<div class='upg-step'>{head}<div class='build-line'>{''.join(chips)}</div></div>")

    html = ("<div class='row-build row-upgrades'>"
            "<div class='row-build-title'>Forms &amp; upgrades</div>"
            f"{''.join(parts)}</div>")
    return html, markers
