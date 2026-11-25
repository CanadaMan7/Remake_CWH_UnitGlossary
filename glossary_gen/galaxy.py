"""
galaxy -- the per-card "Galactic Map": which planets a unit can be
recruited at, for each galactic-conquest campaign set-up.

Data sources (all under a Data\\Xml folder, later --galaxy-data-dirs
entries override earlier ones file by file):

- CampaignFiles.xml: which campaign files are live. Commented-out
  <File> entries are ignored, and only Campaigns_Imperial_Web_Way*
  files are used.
- Campaigns_Imperial_Web_Way_*.xml: each file holds one campaign set-up
  (one <Campaign> per playable faction, sharing a Campaign_Set). A
  set-up's planets are its <Locations> that also appear in some
  <Starting_Forces> entry -- Locations also lists art assets (galaxy
  core model, nebulae, faction icons, dummies) that never get forces.
  Its routes are the names listed in its own <Trade_Routes>.
- Planets_WW.xml: each planet's Galactic_Position, Max_Space_Base,
  Special_Structures_Space and Text_ID.
- TradeRoutes*.xml: route Name -> Point_A / Point_B (e.g.
  TradeRoutes_Web_Way.xml, and TradeRoutes_Web_Way_Tiny.xml for the
  Tiny set-up). Only routes a set-up lists are drawn for it.

A unit counts as recruitable at a planet in a set-up when
  - the planet is in that set-up,
  - it's in the unit's Required_Planets (if the unit has any),
  - the planet's Max_Space_Base is at least the unit's
    Required_Star_Base_Level, and
  - if the unit needs a special structure (shipyard etc.), the planet
    has at least one space structure slot.
The page's JavaScript applies these rules per set-up (see
page_script.py), so switching campaign doesn't need a regeneration.
"""

import json
import os
import re
import sys

from .xml_io import safe_parse

CAMPAIGN_PREFIX = "campaigns_imperial_web_way"

_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def _read_text(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _find_file(dirs, filename):
    """Last directory (highest priority) holding filename, matched
    case-insensitively, or None."""
    found = None
    for d in dirs:
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        for entry in entries:
            if entry.lower() == filename.lower():
                found = os.path.join(d, entry)
    return found


def _split_list(text):
    return [t.strip() for t in re.split(r"[,\s]+", text or "") if t.strip()]


def _parse_campaign_file(path):
    """Regex-based on purpose: campaign files are large, hand-edited and
    full of comments; we only need a handful of tags per <Campaign>."""
    text = _COMMENT_RE.sub("", _read_text(path))
    campaigns = []
    for m in re.finditer(r'<Campaign\s+Name="([^"]+)"\s*>(.*?)</Campaign>', text, re.S):
        body = m.group(2)

        def tag(name):
            t = re.search(rf"<{name}>(.*?)</{name}>", body, re.S)
            return t.group(1).strip() if t else ""

        forces = []
        for sf in re.findall(r"<Starting_Forces>(.*?)</Starting_Forces>", body, re.S):
            parts = [p.strip() for p in sf.split(",")]
            if len(parts) >= 2 and parts[1]:
                forces.append((parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
        max_tech = {}
        for mt in re.findall(r"<Max_Tech_Level>(.*?)</Max_Tech_Level>", body, re.S):
            parts = [p.strip() for p in mt.split(",")]
            if len(parts) == 2:
                try:
                    max_tech[parts[0].lower()] = int(parts[1])
                except ValueError:
                    pass
        campaigns.append({
            "name": m.group(1),
            "set": tag("Campaign_Set"),
            "text_id": tag("Text_ID"),
            "sort": tag("Sort_Order"),
            "active": tag("Starting_Active_Player"),
            "locations": _split_list(tag("Locations")),
            "routes": _split_list(tag("Trade_Routes")),
            "forces": forces,
            "max_tech": max_tech,
        })
    return campaigns


def load_galaxy(dirs, translations, planets_filename="Planets_WW.xml"):
    """Returns a galaxy dict (see build_page_data for what's embedded),
    or None if the files aren't found."""
    campaign_list = _find_file(dirs, "CampaignFiles.xml")
    planets_path = _find_file(dirs, planets_filename)
    if not campaign_list or not planets_path:
        print(f"  ! --galaxy-data-dirs: CampaignFiles.xml or {planets_filename} not found -- "
              f"no Galactic Map.", file=sys.stderr)
        return None

    # ---- live campaign files, in CampaignFiles.xml order ----
    list_text = _COMMENT_RE.sub("", _read_text(campaign_list))
    files = [f.strip() for f in re.findall(r"<File>(.*?)</File>", list_text, re.S)]
    files = [f for f in files if f.lower().startswith(CAMPAIGN_PREFIX)]

    # ---- planets ----
    planets = {}
    root = safe_parse(planets_path)
    if root is not None:
        for el in root.iter("Planet"):
            name = el.get("Name")
            pos = (el.findtext("Galactic_Position") or "").split(",")
            if not name or len(pos) < 2:
                continue
            try:
                x, y = float(pos[0]), float(pos[1])
            except ValueError:
                continue

            def num(tag, default=0):
                try:
                    return int(float((el.findtext(tag) or "").strip()))
                except ValueError:
                    return default

            text_id = (el.findtext("Text_ID") or "").strip()
            label = translations.get(text_id) or name.replace("_WW", "").replace("_", " ")
            planets[name] = {
                "x": x, "y": y, "label": label,
                "space": num("Max_Space_Base"),
                "slots": num("Special_Structures_Space"),
            }

    # ---- trade routes (every TradeRoutes*.xml; later dirs win) ----
    routes = {}
    for d in dirs:
        try:
            entries = sorted(os.listdir(d))
        except OSError:
            continue
        for entry in entries:
            if entry.lower().startswith("traderoutes") and entry.lower().endswith(".xml") \
                    and entry.lower() != "traderoutefiles.xml":
                r = safe_parse(os.path.join(d, entry))
                if r is None:
                    continue
                for el in r.iter("TradeRoute"):
                    a = (el.findtext("Point_A") or "").strip()
                    b = (el.findtext("Point_B") or "").strip()
                    if el.get("Name") and a and b:
                        kind = (el.findtext("Visible_Line_Name") or "").strip().lower()
                        routes[el.get("Name")] = (a, b, "main" if "main" in kind else "")

    # ---- campaign set-ups ----
    setups = []
    for fname in files:
        path = _find_file(dirs, fname)
        if not path:
            print(f"  ! campaign file listed in CampaignFiles.xml not found: {fname}", file=sys.stderr)
            continue
        camps = _parse_campaign_file(path)
        if not camps:
            continue
        locations = []
        route_names = []
        forced = set()
        for c in camps:
            locations.extend(l for l in c["locations"] if l not in locations)
            route_names.extend(r for r in c["routes"] if r not in route_names)
            forced.update(p for _f, p, _o in c["forces"])
        setup_planets = [l for l in locations if l in forced and l in planets]
        planet_set = set(setup_planets)
        edges = []
        missing_routes = []
        for rn in route_names:
            r = routes.get(rn)
            if r is None:
                missing_routes.append(rn)
            elif r[0] in planet_set and r[1] in planet_set:
                edges.append(r)

        # Starting owner per planet, per playable faction's own campaign:
        # whichever faction has the most Starting_Forces entries there.
        owners_by_faction = {}
        for c in camps:
            counts = {}
            for fac, p, _o in c["forces"]:
                counts.setdefault(p, {}).setdefault(fac, 0)
                counts[p][fac] += 1
            owners = {p: max(fc.items(), key=lambda kv: kv[1])[0] for p, fc in counts.items()}
            owners_by_faction[(c["active"] or "").lower()] = owners
        default_owners = next(iter(owners_by_faction.values()), {})

        # Which factions exist in this set-up at all, their max tech
        # level, and which units each faction starts with (and where).
        present = set()
        max_tech = {}
        starts = {}  # faction -> {object name -> [planets]}
        for c in camps:
            for fac, mt in c["max_tech"].items():
                present.add(fac)
                max_tech[fac] = max(max_tech.get(fac, mt), mt)
            for fac, p, obj in c["forces"]:
                present.add(fac.lower())
                if obj and p in planet_set:
                    bucket = starts.setdefault(fac.lower(), {}).setdefault(obj, [])
                    if p not in bucket:
                        bucket.append(p)

        text_id = camps[0]["text_id"]
        label = translations.get(text_id) or camps[0]["set"] or fname
        setups.append({
            "id": camps[0]["set"] or fname,
            "label": label,
            "file": fname,
            "era": campaign_era(fname),
            "planets": setup_planets,
            "edges": edges,
            "campaign_count": len(camps),
            "present": present,
            "max_tech": max_tech,
            "starts": starts,
            "owners_by_faction": owners_by_faction,
            "default_owners": default_owners,
        })
        if missing_routes:
            print(f"  ! {fname}: {len(missing_routes)} trade route(s) not found in any TradeRoutes*.xml",
                  file=sys.stderr)
    if not setups:
        return None
    return {"planets": planets, "setups": setups}


def campaign_era(fname):
    """The era a campaign file is set in, by its name:
    Campaigns_Imperial_Web_Way_CW_* -> Clone Wars,
    Campaigns_Imperial_Web_Way_RiseOfTheEmpire -> Rise of the Empire,
    anything else -> Galactic Civil War. (Matches eras.py's labels; a
    _RotE story plot inside another campaign doesn't change its era.)"""
    from .eras import CLONE_WARS, GALACTIC_CIVIL_WAR, RISE_OF_THE_EMPIRE
    stem = os.path.splitext(fname)[0].lower()
    if stem.startswith("campaigns_imperial_web_way_cw_"):
        return CLONE_WARS
    if stem == "campaigns_imperial_web_way_riseoftheempire":
        return RISE_OF_THE_EMPIRE
    return GALACTIC_CIVIL_WAR


def campaign_accepts(era):
    """Unit Era tags a campaign of this era can recruit (besides "All").
    Rise of the Empire is set during the Galactic Civil War, so its
    campaign takes GCW units as well as its own RotE-only ones; GCW
    campaigns don't get RotE units."""
    from .eras import GALACTIC_CIVIL_WAR, RISE_OF_THE_EMPIRE
    if era == RISE_OF_THE_EMPIRE:
        return [RISE_OF_THE_EMPIRE, GALACTIC_CIVIL_WAR]
    return [era]


def faction_start_names(galaxy, faction_key):
    """Every object name the faction starts with in any set-up."""
    names = set()
    for s in galaxy["setups"]:
        names.update(s["starts"].get(faction_key or "", {}))
    return names


def build_page_data(galaxy, faction_key, unit_names=()):
    """Compact JSON blob for one faction page: the planet table, and per
    set-up its planet indices, route index pairs, this faction's
    starting planets, whether the faction is in the set-up at all, its
    max tech level, and where any unit in unit_names (the page's cards'
    variant Names) starts in play."""
    unit_names = set(unit_names)
    names = sorted({p for s in galaxy["setups"] for p in s["planets"]})
    index = {n: i for i, n in enumerate(names)}
    planets = [[n, galaxy["planets"][n]["label"], round(galaxy["planets"][n]["x"], 1),
                round(galaxy["planets"][n]["y"], 1), galaxy["planets"][n]["space"],
                galaxy["planets"][n]["slots"]] for n in names]
    # A faction no set-up mentions at all (Neutral, Unaffiliated, ...)
    # gets no "faction not in this campaign" verdicts.
    known_faction = any(faction_key and faction_key in s["present"] for s in galaxy["setups"])
    setups = []
    for s in galaxy["setups"]:
        owners = s["owners_by_faction"].get(faction_key or "", s["default_owners"])
        owned = [index[p] for p in s["planets"]
                 if faction_key and owners.get(p, "").lower() == faction_key]
        fac_starts = s["starts"].get(faction_key or "", {})
        setups.append({
            "id": s["id"], "label": s["label"], "file": s["file"], "era": s["era"],
            "eras": campaign_accepts(s["era"]),
            "p": [index[p] for p in s["planets"]],
            "e": [[index[a], index[b], 1 if kind == "main" else 0] for a, b, kind in s["edges"]],
            "own": owned,
            "present": (faction_key in s["present"]) if known_faction else None,
            "maxTech": s["max_tech"].get(faction_key or ""),
            "start": {n: [index[p] for p in ps] for n, ps in fac_starts.items() if n in unit_names},
        })
    # Default: the set-up playable by the most factions, then the one
    # with the most planets; first in CampaignFiles.xml order on a tie.
    # A choice made in the page is remembered by the browser.
    default = 0
    for i, s in enumerate(galaxy["setups"]):
        best = galaxy["setups"][default]
        if (s["campaign_count"], len(s["planets"])) > (best["campaign_count"], len(best["planets"])):
            default = i
    return json.dumps({"planets": planets, "setups": setups, "default": default},
                      separators=(",", ":"))


def map_rules_attr(lines):
    """data-map attribute for a card: one rule per build line (see
    build_rules.collect_build_lines) -- [required planet names or null,
    required space station level, needs a structure slot (0/1), tech
    level or null, buildable (0/1)]."""
    rules = []
    for line in lines:
        info = line["info"]
        rules.append([
            list(info["planets_raw"]) or None,
            info["star_base"] or 0,
            1 if info["structures"] else 0,
            info["tech"],
            1 if info["buildable"] else 0,
        ])
    return json.dumps(rules, separators=(",", ":"))
