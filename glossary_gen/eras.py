"""
eras -- which era (Clone Wars, Galactic Civil War, Rise of the Empire)
a unit or hero belongs to, shown as the "Era" chip in each card's
Build requirements panel.

How it's worked out, starting from the live campaigns:

1. CampaignFiles.xml -> live Campaigns_Imperial_Web_Way_* files (same
   rules as the Galactic Map: commented-out entries are skipped).
2. Each campaign's <Story_Name> ("Faction, file"), <Empire_Story_Name>,
   <Rebel_Story_Name> and <Underworld_Story_Name> -> Story_Plots_*.xml.
   A plot's era comes from its file name: "CW" (CW_ERA, WW_CW_Ai,
   Ai_CW_Era_Full ...) means Clone Wars, "RotE" means Rise of the
   Empire, anything else is the default Galactic Civil War set-up.
3. Each plot's <Active_Plot> -> Story_SandBox_*.xml files, and its
   <Lua_Script> -> Unit_Filter_WW_*.lua in Data\\Scripts\\Story.
4. Sandbox files: LOCK_UNIT events whose name is era-tagged (contains
   _CW_ or _GCW_). The unit locked belongs to the OTHER era than the
   sandbox's own -- a Clone Wars sandbox locks Galactic Civil War
   heroes and vice versa. (Going by the file's era rather than the
   event name, since a few events are labelled the wrong way round.)
5. Unit_Filter Lua scripts: every Check_Story_Flag(player, "<FLAG>")
   block whose flag contains _CW_ or _GCW_ (e.g. CIS_GCW_Heroes_Off)
   names that era's units in its SetBuildable(..., "<Unit>", ...)
   calls. The "Off" blocks include each era's hero upgrades.
6. Rise of the Empire: units whose Name ends in _RotE.

Anything not picked up by any of these is shown as "All".
"""

import os
import re
import sys

CLONE_WARS = "Clone Wars"
GALACTIC_CIVIL_WAR = "Galactic Civil War"
RISE_OF_THE_EMPIRE = "Rise of the Empire"
ALL_ERAS = "All"
ERA_ORDER = [CLONE_WARS, GALACTIC_CIVIL_WAR, RISE_OF_THE_EMPIRE]

_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_CW_RE = re.compile(r"(?:^|_)CW(?:_|$|\.)", re.I)
_GCW_RE = re.compile(r"(?:^|_)GCW(?:_|$|\.)", re.I)
_ROTE_RE = re.compile(r"(?:^|_)RotE(?:_|$|\.)", re.I)


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _index_dirs(dirs):
    """lowercase file name -> path, later dirs win."""
    out = {}
    for d in dirs:
        try:
            for entry in os.listdir(d):
                out[entry.lower()] = os.path.join(d, entry)
        except OSError:
            pass
    return out


def _file_era(name):
    if _ROTE_RE.search(name):
        return RISE_OF_THE_EMPIRE
    if _CW_RE.search(name) and not _GCW_RE.search(name):
        return CLONE_WARS
    return GALACTIC_CIVIL_WAR


def load_eras(xml_dirs, script_dirs):
    """Returns {unit Name: set(era names)} for every unit an era file
    mentions. RotE-suffixed units are handled in eras_for_names, so
    they needn't appear here."""
    xml_files = _index_dirs(xml_dirs)
    lua_files = _index_dirs(script_dirs)
    eras = {}
    missing = set()

    def add(unit, era):
        eras.setdefault(unit, set()).add(era)

    # 1-2: live campaign files -> plot files
    campaign_list = xml_files.get("campaignfiles.xml")
    if not campaign_list:
        print("  ! eras: CampaignFiles.xml not found -- every unit will show Era: All",
              file=sys.stderr)
        return eras
    listed = re.findall(r"<File>(.*?)</File>", _COMMENT_RE.sub("", _read(campaign_list)), re.S)
    plots = set()
    for fname in (f.strip() for f in listed):
        if not fname.lower().startswith("campaigns_imperial_web_way"):
            continue
        path = xml_files.get(fname.lower())
        if not path:
            missing.add(fname)
            continue
        text = _COMMENT_RE.sub("", _read(path))
        for tag, value in re.findall(r"<(\w*Story_Name)>(.*?)</\1>", text, re.S):
            plot = value.split(",")[-1].strip()
            if plot:
                plots.add(plot)

    # 3: plots -> sandbox files (with the era they're loaded in) and Lua scripts
    sandbox_eras = {}
    scripts = set()
    for plot in sorted(plots):
        path = xml_files.get(plot.lower())
        if not path:
            missing.add(plot)
            continue
        era = _file_era(plot)
        text = _COMMENT_RE.sub("", _read(path))
        for active in re.findall(r"<Active_Plot>(.*?)</Active_Plot>", text, re.S):
            active = active.strip()
            if os.path.basename(active).lower().startswith("story_sandbox"):
                sandbox_eras.setdefault(os.path.basename(active), set()).add(era)
        for script in re.findall(r"<Lua_Script>(.*?)</Lua_Script>", text, re.S):
            if script.strip().lower().startswith("unit_filter"):
                scripts.add(script.strip())

    # 4: era-tagged LOCK_UNIT events in sandbox files
    for sandbox, loaded_in in sorted(sandbox_eras.items()):
        path = xml_files.get(sandbox.lower())
        if not path:
            missing.add(sandbox)
            continue
        if CLONE_WARS in loaded_in and len(loaded_in) > 1:
            continue  # loaded by plots of both eras -- direction unclear
        locked_era = GALACTIC_CIVIL_WAR if CLONE_WARS in loaded_in else CLONE_WARS
        text = _COMMENT_RE.sub("", _read(path))
        for name, body in re.findall(r'<Event\s+Name="([^"]+)"\s*>(.*?)</Event>', text, re.S):
            if not (_CW_RE.search(name) or _GCW_RE.search(name)):
                continue
            if not re.search(r"<Reward_Type>\s*LOCK_UNIT\s*<", body):
                continue
            unit = re.search(r"<Reward_Param1>\s*([^<\s]+)", body)
            if unit:
                add(unit.group(1), locked_era)

    # 5: Unit_Filter Lua scripts
    for script in sorted(scripts):
        path = lua_files.get(script.lower() + ".lua") or lua_files.get(script.lower())
        if not path:
            missing.add(script + ".lua")
            continue
        text = re.sub(r"--[^\n]*", "", _read(path))
        blocks = re.split(r'Check_Story_Flag\s*\(\s*\w+\s*,\s*"', text)
        for block in blocks[1:]:
            flag = block.split('"', 1)[0]
            if _GCW_RE.search(flag):
                era = GALACTIC_CIVIL_WAR
            elif _CW_RE.search(flag):
                era = CLONE_WARS
            else:
                continue
            for unit in re.findall(r'SetBuildable\s*\(\s*\w+\s*,\s*"([^"]+)"', block):
                add(unit, era)

    if missing:
        print(f"  ! eras: {len(missing)} referenced file(s) not found (skipped): "
              + ", ".join(sorted(missing)[:8]) + (" ..." if len(missing) > 8 else ""),
              file=sys.stderr)
    return eras


def eras_for_names(names, eras):
    """Era labels for a card from its variant Names, in display order;
    ["All"] when none of them is era-specific."""
    found = set()
    for n in names:
        found.update(eras.get(n, ()))
        if re.search(r"_RotE$", n, re.I):
            found.add(RISE_OF_THE_EMPIRE)
    return [e for e in ERA_ORDER if e in found] or [ALL_ERAS]
