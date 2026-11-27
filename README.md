# Remake_CWH_UnitGlossary
All credit to Ripoblus, who created the original for FFT and graciously allowed me to rehost this. My sincere thanks.

Provided Instructions are:
"Alright, I've uploaded code to the github. It's a bit messy currently because the output html pages get written to the same path as the scripts - this was a temporary step on my part to get GitHub to recognize the splash page.
https://github.com/ripoblus858-droid/eaw-unit-glossary

The readme has a complete step-by-step guide: for CWH, in the run_glossary.bat file (step 4) just remove the mod path for FFT, and redirect the projectiles.xml and translationsmanifest.xml paths to that of CWH.

Briefly, the procedure is: 
     
The in-game tga icons need to be converted to png to be rendered correctly in html. First, use MTD Editor (https://modtools.petrolution.net/tools/MtdEditor) to mass extract tga icons into a .tga folder. Then, run the Python script convert_icons.py to convert them to a folder of pngs. (In the following step, only pngs rendered on the web pages are kept, and the remaining are moved to an "unused" folder and can be discarded.)
Generate all web pages by running run_glossary.bat, but first, open the file and take a look at the parameter specifications. It simply runs a Python script, but it takes as input a half dozen or so .txt files. These files optionally specify all sorts of manual refinements to the xml entries to improve presentation of the web pages. In practice, I end up running the .bat multiple times, each time inspecting a few entries for errors, and return to these parameter files for modifications as needed."

## Build requirements panel

Every unit card now opens with a **Build requirements** panel, read straight from the unit XML:

- **Build limit**: `Build_Limit_Current_Per_Player` ("N at a time"), `Build_Limit_Lifetime_Per_Player` ("N per game") and `Build_Limit_Current_For_All_Allies`. `-1`/`0` means no limit.
  For squadrons the engine counts individual craft, so the at-a-time limit is shown divided by the number of `Squadron_Units` entries (e.g. 120 craft / 8 per squadron = 15 squadrons).
  Named hero squadrons (`Is_Named_Hero` = Yes on the squadron or one of its craft) are not divided, because a single unit caps them.
- **Tech level**, **Space station level** (`Required_Star_Base_Level`) and **Ground base level** (`Required_Ground_Base_Level`).
- **Requires**: `Required_Special_Structures`, shown by in-game name (e.g. `U_Shipyard_3` → "Major Construction Yard"). Hover a name to see its internal ID.
- **Only at**: `Required_Planets`, taken from the unit itself or an entry it inherits from through `Variant_Of_Existing_Type`. A `*_Required_Planets` entry that only shares a parent with the unit (for example `Pelta_Required_Planets` next to `Pelta_Rep`, both under `Pelta_Template`) does not restrict it, because the game never applies it to that unit.
- **Needs in orbit**: `Required_Orbiting_Units`.
- **Locked at start**: `Build_Initially_Locked` (and whether a slicer can unlock it).
- **Era**: Clone Wars, Galactic Civil War, Rise of the Empire, or All. It comes from the live campaigns' story files: each campaign's `Story_Name` points to a `Story_Plots_*` file, which loads `Story_SandBox_*` files and `Unit_Filter_WW_*` Lua scripts (from `--story-scripts-dirs`).
  - In the Lua scripts, units listed in a block whose story flag contains `_CW_` or `_GCW_` (e.g. `CIS_GCW_Heroes_Off`) belong to that era.
  - In the sandbox files, units locked by an era-tagged event belong to the other era from the file's own (a Clone Wars sandbox locks Galactic Civil War units, and vice versa).
  - Units whose name ends in `_RotE` are Rise of the Empire.
  - Everything else is All.

When a card merges variants from several factions, each faction page only shows that faction's own variants (title, images, stats and the "variants merged" line).

A unit with no build cost, or with Tech_Level 99, shows as "Not buildable". These are usually garrison or spawned copies. When a card merges several variants, each faction page shows only that faction's rules, and garrison copies are hidden.

**Easter eggs**: units listed in `easter_eggs.txt` (currently `Jak_Kannadee_CR-109`) get their own **Easter Egg** Unit Type filter instead of Unique Hero. They stay hidden, even from search, the build-limited table and entry counts, until that filter is ticked.

**Era filter and Sort by**: each faction page has an **Era** filter (Clone Wars, Galactic Civil War, Rise of the Empire, All eras) and a **Sort by** menu next to the search box. *Default* keeps the cards grouped by source file. *Alphabetical*, *Unit Class*, *Tech level*, *Cost*, *Pop Cost* and *AI Combat Power* show one flat list instead. Tech level sorts lowest first; ties go by class, then name, and cards that can't be built come last. Cost (`Build_Cost_Credits`) and Pop Cost (`Population_Value`) sort lowest first; AI Combat Power (`AI_Combat_Power`) sorts highest first. These use the number shown on the card (the largest one when a mixed squadron shows several); cards with no value come last, and ties go by class, then name. Unit Class order is Fighter, Bomber, Gunship, Corvette, Frigate, Capital, then anything else, alphabetical within each class.

Each faction page also has:
- a **Build-limited units** table at the top, linking to each card
- a **Build rules** filter: has a build limit, has requirements, locked at start, only at specific planets, no limit or requirements, not buildable

Structure names come from `--structures-dirs` (the `Data\Xml\Buildings` folders, already in `run_glossary.bat`). If one still shows a raw ID, add it to `structure_name_overrides.txt`.

Unlocks driven by Lua story scripts aren't in the unit XML, so they can't be picked up automatically.

## Galactic Map

Every buildable card has a **Galactic Map** showing where the unit can be recruited. On squadron cards it replaces the formation diagram, and on other cards it sits on the right. Units that can't be built keep their formation diagram and get no map. Use the **Galactic Map campaign** selector at the top of each faction page to switch campaigns. The browser remembers your choice.

- **Campaigns** come from `CampaignFiles.xml`. Only entries starting with `Campaigns_Imperial_Web_Way` are used, and commented-out entries are skipped.
- **Planets** in a campaign are its `<Locations>` that are defined in `Planets_WW.xml` and have at least one `<Starting_Forces>` entry. This leaves out art assets, nebulae, icons and dummies.
- **Trade routes** are the ones named in the campaign's own `<Trade_Routes>`, looked up in any `TradeRoutes*.xml` (including `TradeRoutes_Web_Way_Tiny.xml`). Main routes are drawn slightly brighter.
- **Recruitable** planets are in green. A planet counts when it is in the unit's `Required_Planets` (if the unit has any), its `Max_Space_Base` is at least the unit's required space station level, and it has a space structure slot if the unit needs a shipyard or other structure.
- **Yellow rings** mark the planets the page's faction starts with in that campaign.
- Hover over the map to see a planet's name.
- **Each map has its own campaign menu**, listed by campaign file. A tick means recruitable in that campaign, a star means it only starts in play there, and a cross means not available. When it isn't available, the caption says why: the faction isn't in that campaign, the unit needs a higher tech level than the campaign allows, its required planets aren't in that campaign, or no planet meets its requirements. The **All maps** menu at the top of the page resets every map to one campaign.
- **Era**: each campaign has an era, worked out from its file name. `Campaigns_Imperial_Web_Way_CW_*` files are Clone Wars, `Campaigns_Imperial_Web_Way_RiseOfTheEmpire` is Rise of the Empire, and every other campaign is Galactic Civil War. A unit with an Era tag (not "All") only counts as recruitable in campaigns of its own era. Rise of the Empire is set during the Galactic Civil War, so that campaign also recruits Galactic Civil War units, but Rise of the Empire units aren't available in the other Galactic Civil War campaigns. Both campaign menus show each campaign's era in brackets.
- **Blue dots** mark the planets where the unit starts in play (its `<Starting_Forces>` for the page's faction). Heroes that can't be built but start on the map still get a map.

`run_glossary.bat` passes both `Data\Xml` folders through `--galaxy-data-dirs`. When the same file exists in both, the CWH copy is used.

## Forms & upgrades

Cards that upgrade into another form, or are upgraded from one, get a **Forms & upgrades** panel under Build requirements.

- **Which unit becomes which** comes from `Upgrade_Units.lua` (`Data\Scripts\GameObject`, via `--upgrade-scripts-dirs`). Each `Get_Name() == "<UPGRADE>"` branch calls `Upgrade_Unit(planet, player, "<from>", "<to>")`. Both Remake 4.0's story sandboxes and CWH's `*_HeroUpgrades` sandboxes go through this script, so it covers both systems. Branches named `REPAIR_*` are shown as repairs (damage phases, e.g. P2 -> P1).
- **Forms** shows the whole chain (e.g. Judicator -> Accuser -> Executor / Imperial Piett Executor), with the current card in bold and links to the other forms' cards on the same page.
- **Upgrade requirements** are read from the upgrade object's own unit XML entry (e.g. `RETALIATION_UPGRADE` in `Units_Hero_Minors_Republic_MZsinj.XML`): cost, tech level, space station level, required structures, the unit that has to be in orbit (`Required_Orbiting_Units`, usually the hero itself), and required planets. The "via" name is the upgrade button's in-game name; hover it to see the internal ID.
- **Planet-restricted upgrades** are ringed in **red** on the Galactic Map, with a caption saying which upgrade needs them. If the planet isn't in the selected campaign, the caption says so instead.

**In-game screenshots** (`ingame_images.txt`): each line is `<unit Name>, <image>, <image>...`. An image can be a file name in the `screenshots` folder or a full `https://` link. The entries at the bottom of the file link straight to images on the ModDB galleries for Remake (https://www.moddb.com/mods/empire-at-war-re/images) and CWH (https://www.moddb.com/mods/empire-at-war-remake-clone-wars-holdout-factions/images). They were only added where the ModDB image title exactly matches the unit's in-game name, so most units still need screenshots added by hand. Linked images need an internet connection to show and will break if ModDB removes them; to keep a copy, download the image into `screenshots` and replace the link with its file name.

**Roster Type filter**: each faction page has a **Roster Type** filter above Era. A card is **Core** for a faction if either (1) the faction's name is in the file name of that faction's variant (e.g. `Units_Space_Neutral_Republic_Dreadnaught.xml` for the Republic), or (2) the faction can build its variant without a planet restriction. Otherwise it is **Cross-buildable**. The words looked for in file names are: Empire, Rebel, Underworld, Republic, CIS, Hutt/Cartel (Hutt Cartels), CSA, Hapan/Hapes, Mandalorian, Pirate, Sith, Warlords and Neutral. "Old_Republic" in a file name means the Sith (Sith Cultist) faction: those files count as Sith files and never as Republic ones, including the `Old_Republic_Republic_...` ships (Aurek, Foray, Hammerhead, Centurion). The list is `ROSTER_FILE_TOKENS` in `glossary_gen/html_output.py`. Garrison cards (a Name with `_G` or `Garrison` in it) are only Core if their file has the faction's name in it, or they are in the Garrison Complement of a Core card on the same page; otherwise they're Cross-buildable. To force a unit either way, add a line `<faction>, <unit Name>, core|cross` to `roster_overrides.txt` (passed with `--roster-overrides`); for example `CIS, Hornet_Carrier_CIS, cross`.
