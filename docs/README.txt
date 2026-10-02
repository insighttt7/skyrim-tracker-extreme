==============================================================================
                          SKYRIM TRACKER EXTREME
                                  v1.0.0
               A 100% completion tracker for Skyrim SE / AE
==============================================================================

Author:  Alexey Insight


------------------------------------------------------------------------------
READ THIS FIRST
------------------------------------------------------------------------------

* The tracker supports Skyrim Special Edition and Anniversary Edition ONLY:
  the base game, Dawnguard, Hearthfire, Dragonborn and the Creation Club
  content of the Anniversary Edition.

* USSEP (Unofficial Skyrim Special Edition Patch) and USCCP (Unofficial
  Skyrim Creation Club Content Patch) are REQUIRED. All tables of the
  tracker were built and checked with both patches installed. Without them
  some quests, items or statuses may not be recognised correctly.

* Content added by mods is NOT tracked. Mods that add new quests, locations,
  spells, perks, items, books or anything else to collect will not show up
  in the tracker, and mods that change vanilla quests or records can make
  their status wrong. The tracker knows only what exists in SE / AE itself.

* The tracker only READS save files. It never changes, moves or deletes a
  save. Your game is never touched.

* Every category except Quests has an annotation - the small (i) icon next
  to the category title. PLEASE READ THEM. Each one explains the exact
  in-game action that makes an entry count, and some of them are not
  obvious (for example, a shout counts only after you have used it once,
  and books count only when placed in one of your homes).


------------------------------------------------------------------------------
CONTENTS
------------------------------------------------------------------------------

   1. What it is
   2. Requirements
   3. Installing and starting
   4. Loading a save
   5. The screen
   6. Keyboard shortcuts
   7. Statuses and chips
   8. The categories
   9. Mark - why some quests are ticked by hand
  10. Creation Club content
  11. Settings and files
  12. Troubleshooting
  13. Credits, license and contact


==============================================================================
1. WHAT IT IS
==============================================================================

Skyrim Tracker Extreme reads your save file (.ess) and shows how far you are
from 100% completion of Skyrim: quests, locations, spells, shouts,
enchantments, ingredients, perks, collectibles and books - 2254 entries in
total, each one with its status taken straight from the save.

You pick a save, the tracker reads it in a couple of seconds and fills every
list. After you play more, save in the game and load the new save in the
tracker.


==============================================================================
2. REQUIREMENTS
==============================================================================

* Windows 10 or Windows 11, 64-bit.
* Microsoft Edge WebView2 Runtime. It is part of Windows 11 and of every
  up-to-date Windows 10. If the window stays empty, install the "Evergreen"
  runtime from Microsoft:
  https://developer.microsoft.com/microsoft-edge/webview2/
* Skyrim Special Edition or Anniversary Edition (Steam or GOG), any game
  language.
* USSEP and USCCP installed in the game (see "Read this first").
* Nothing else. Python and all libraries are already inside the program.


==============================================================================
3. INSTALLING AND STARTING
==============================================================================

1. Unpack the WHOLE archive into any folder, for example your Desktop or
   Documents. There is no installer.

2. Keep the folder together:

      Skyrim Tracker Extreme\
        Skyrim Tracker Extreme.exe   - start the program with this
        libs\                        - the program's own Python and libraries
        data\                        - your settings (created on first start)
        README.txt, LICENSE.txt, THIRD_PARTY_NOTICES.txt

   The .exe cannot run without the "libs" folder next to it. Do not move the
   .exe alone. To start it from the Desktop, make a shortcut instead:
   right-click the .exe - Send to - Desktop (create shortcut).

3. Start "Skyrim Tracker Extreme.exe". The window opens maximized.

4. Windows may show a blue "Windows protected your PC" window the first
   time. This appears for new programs that are not signed with a paid
   certificate. Click "More info" and then "Run anyway".

The program is portable: copy the folder to another place or computer and it
keeps working, with your settings.


==============================================================================
4. LOADING A SAVE
==============================================================================

* Click "Choose .ess file" in the top left corner and pick a save.

* The first time, the dialog opens in the standard save folder:
      Documents\My Games\Skyrim Special Edition\Saves
  (or "Skyrim Special Edition GOG\Saves" for the GOG version). If you pick a
  save from another folder, the tracker remembers that folder and opens it
  next time.

* A loading card shows each step: reading the save, unpacking it, then every
  category. When it finishes, the tracker opens with your data.

* The tracker does not follow the game live. After a new save in the game,
  click "Choose .ess file" again and pick the new save.

* If the file is not a Skyrim save, or the save is damaged or still being
  written by the game, the card says so and you can pick another file.

Tip: use a manual save or a quicksave made in a calm moment. Any save works,
but the save you see in the tracker is exactly the moment it was made.


==============================================================================
5. THE SCREEN
==============================================================================

Top bar
  - Theme button: switches between the two themes, Daedric Space (dark) and
    Stalhrim Parchment (light).
  - Choose .ess file: loads a save. After loading it shows the save's name.
  - SKYRIM title.
  - Search: searches every category at once by name or by FormID / Editor ID.

Player panel
  - Level ring with your character level and experience.
  - Location, character name, race, number of plugins and light plugins,
    save number and save version, taken from the save. Location and game
    date are shown in the language of your game.
  - COMPLETION: your overall progress in percent. It is calculated over 8
    categories: Quests, Locations, Spells, Shouts, Enchanting, Ingredients,
    Perks and Collectibles. Books are shown separately and are not part of
    the percentage.
  - On the right: a small bar for each of those 8 categories.

Tabs
  - DAWNGUARD, SKYRIM, DRAGONBORN: the quest lists.
  - Enchanting, Ingredients, Spells, Shouts, Locations, Perks, Collectibles,
    Books: the other categories.

Filter pills (under the tabs)
  - All, Done / Not done (or Obtained / Learned / Discovered and their
    opposites, depending on the category), Optional, Alternative line,
    Failed, Mark. Each pill shows how many entries it holds. Pills appear
    only when the current tab has such entries.

Section tools (right side of each section title)
  - Collapse all / expand all blocks.
  - Compact rows: shows more rows on the screen.
  - In the Skyrim tab: the TOWNSFOLK REQUESTS button (see chapter 8).

Each block shows a progress bar and a "done / total" counter. The counter is
in the theme colour at 0, yellow while in progress and green when complete.

When you scroll down, a small profile with your level and percentage stays
at the top of the window. Click it to jump back up.

Click one of the 8 small bars in the player panel to open that category.


==============================================================================
6. KEYBOARD SHORTCUTS
==============================================================================

  Esc                     While typing in the search field: clears the
                          search and leaves the field.
  Page Up / Page Down     Scroll the page one screen up / down.
  Home / End              Jump to the top / bottom of the page.
  Arrow Up / Arrow Down   Scroll the page a little.
  Ctrl + mouse wheel      Zoom in / out. Ctrl + plus / Ctrl + minus do the
                          same.
  Ctrl + 0                Reset the zoom.

Page Up, Page Down, Home, End and the arrows scroll the page when the search
field is not active - press Esc first if you were typing in it.


==============================================================================
7. STATUSES AND CHIPS
==============================================================================

Status chips
  Done / Obtained / Learned / Discovered
      The save shows that this entry is complete.
  Not done / Not obtained / Not learned / Not discovered
      The save shows that it is not complete yet.
  Optional
      Not required for 100%. It counts only after you complete it: while it
      is not done it is left out of both numbers of the counter, so 100% is
      reachable without it. When done, it shows Done as well and counts.
  Alternative line
      One of two mutually exclusive paths (see chapter 8, Quests).
  Failed
      The quest is failed in your save (see chapter 8, Quests).
  Mark
      Cannot be read from a save - you tick it yourself (see chapter 9).

Content chips
  Dawnguard, Dragonborn, Hearthfire - the entry comes from that DLC.
  AE - the entry comes from Anniversary Edition / Creation Club content.
  Rare Curios - the ingredient comes from the Rare Curios Creation.
  Other chips name the Creation the entry belongs to.

Every row also shows its Editor ID or FormID on the right, so you can look it
up on UESP or in the game console.


==============================================================================
8. THE CATEGORIES
==============================================================================

------------------------------------------------------------------------------
QUESTS - 605 rows
------------------------------------------------------------------------------

  Skyrim tab            403 rows  (Main, Daedric, Divine, Dungeon and other
                                   global quests, Civil War, Factions,
                                   Regions, Anniversary Edition content)
  Dawnguard tab          39 rows
  Dragonborn tab         60 rows
  Townsfolk Requests    103 rows  (opened from the Skyrim tab)

Most quests are read from the save: a quest counts as Done when the game
marks it completed, or, for quests the game never marks as completed, when
the save shows that its final stage was reached. Each rule was checked
against the quest data and in the game.

Optional quests (8) - not needed for 100%:
  Paarthurnax, Season Unending, Rejoining the College, Rebuilding the
  Blades, Dragon Hunting, Dragon Research, Reparations, Surgery.

Alternative lines - mutually exclusive paths:
  - Civil War: the Imperial Legion or the Stormcloaks.
  - Dark Brotherhood: "Where You Hang Your Enemy's Head..." or "Destroy the
    Dark Brotherhood!".
  - Dawnguard: the Dawnguard path or the vampire path.
  - Dragonborn, Thirsk: "The Chief of Thirsk Hall" or "Retaking Thirsk" with
    Hilund, Elmus and Halbarn.
  - A Dying Wish: "Fortunate Son" or "The Pit".
  While you have not started either path, both show "Alternative line" and
  both count. As soon as you complete the first quest of one path, that path
  becomes the one that counts; the other path stays "Alternative line" and
  leaves the counter.

Failed quests: a quest that is failed in your save is shown as Failed and
still counts in the total, so 100% is not possible while any quest is
failed. Only quests that the game itself can fail are checked. To fix it,
load an earlier save and complete the quest.

Black Books: "Waking Dreams" and "Epistolary Acumen" are the same quests as
"The Temple of Miraak" and "The Path of Knowledge" in the Dragonborn main
story. They are shown in both places but counted only once.

Rows with the Mark chip (56 in the quest tabs) and the whole Townsfolk
Requests panel (103 rows) are ticked by hand - see chapter 9.

TOWNSFOLK REQUESTS
  Opened with the TOWNSFOLK REQUESTS button in the Skyrim tab (next to the
  collapse / expand buttons); the same button brings you back. The button
  shows your progress, for example 12 / 103. The panel holds the small jobs
  and favours people across Skyrim ask of you: chopping wood, mining ore,
  gathering wheat, brawls, gifts to beggars and drunks, rare gifts,
  deliveries, dungeon delving, persuasion, the crafting tutorials and more.
  Every row here is a Mark row. Each block also has a "Mark all" button
  (double tick, shown when you point at the block title) that ticks or
  unticks the whole block at once.

------------------------------------------------------------------------------
LOCATIONS - 419 map locations in 36 blocks
------------------------------------------------------------------------------

  A location counts as Discovered when its marker is revealed on your map.
  Annotation: travel within sight of the location to discover it. Locations
  that are shown on the map from the very start, like the big cities, count
  automatically.

------------------------------------------------------------------------------
SPELLS - 167 spells
------------------------------------------------------------------------------

  Grouped by school. Includes the spells of Dawnguard, Dragonborn and the
  Creation Club (for example Necromantic Grimoire, Saints & Seducers, The
  Cause). Optional: Heal Undead and Conjure Staada.
  Annotation: a spell counts once it is learned - read its Spell Tome or be
  taught it directly.

------------------------------------------------------------------------------
SHOUTS - 27 shouts, 81 Words of Power
------------------------------------------------------------------------------

  Every word is its own row. The top bar counts shouts with all 3 words
  learned.
  Annotation - IMPORTANT: the game writes a word into the save only after
  you have used the shout. Learn the word at a Word Wall, unlock it with a
  dragon soul AND shout it at least once. Use every shout once after
  learning new words.

------------------------------------------------------------------------------
ENCHANTING - 58 enchantment effects
------------------------------------------------------------------------------

  Annotation: an effect counts only after you disenchant an item bearing it
  at an Arcane Enchanter. Finding or wearing the item is not enough.

------------------------------------------------------------------------------
INGREDIENTS - 184 ingredients
------------------------------------------------------------------------------

  Each row has 4 flasks, one per effect of the ingredient in its game order.
  A lit flask is a learned effect.
  Annotation: an ingredient counts as Discovered only when ALL 4 effects are
  learned - by eating it or by brewing potions with it.

------------------------------------------------------------------------------
PERKS - 282 rows
------------------------------------------------------------------------------

  The 18 skill trees (every rank of a perk is its own row), the Werewolf
  and Vampire Lord trees, and quest perks such as Agent of Mara, Agent of
  Dibella, Sinderion's Serendipity or Nightingale Armor. Werewolf and
  vampire perks stay in the save after a cure and keep counting.
  Optional: Dragon Infusion.
  Annotation: most perks need a perk point; quest perks count simply by
  finishing their quest.

------------------------------------------------------------------------------
COLLECTIBLES - 40 rows in 5 blocks
------------------------------------------------------------------------------

  Paragons (5), Dragon Claws (12), Dragon Priest Masks (14), Bugs in a
  Jar (8), Kagrumez Resonance Gems (5 gems in one row, shown as 5 gem
  icons).
  Annotation - IMPORTANT: an item counts only when it is placed in one of
  the 8 tracked homes - on a display, in a container or on a mannequin:
      Breezehome, Proudspire Manor, Honeyside, Vlindrel Hall, Hjerim,
      Severin Manor, Bloodchill Manor, Hendraheim
  Items you only carry in your inventory do not count.

------------------------------------------------------------------------------
BOOKS - 418 books (90 skill books + 328 other books)
------------------------------------------------------------------------------

  Skill books are grouped by skill, 5 per skill. Journals, notes, spell
  tomes, Black Books, the Elder Scrolls, Oghma Infinium and other quest
  copies are not part of the list.
  Annotation - IMPORTANT: like collectibles, a book counts only when it is
  placed in one of the 8 tracked homes (a bookshelf, a container, a display
  or a mannequin). Reading a book does not count.
  Books are not part of the COMPLETION percentage.


==============================================================================
9. MARK - WHY SOME QUESTS ARE TICKED BY HAND
==============================================================================

Some quests leave no reliable trace in the save file, so no program can read
them - not this tracker and not any other. The tracker does not guess: these
quests carry the Mark chip and you tick them yourself.

Why they cannot be read:

  * Radiant and repeatable quests - Companions jobs, Thieves Guild jobs,
    College of Winterhold tasks, the Dark Brotherhood contracts, the
    Dawnguard and vampire radiant quests, the First Catch radiant jobs and
    other repeatable work. The game restarts these quests over and over;
    each restart clears their stages and their "completed" flag, and the
    only thing left is a counter for the whole group.

  * Townsfolk requests and favours - chopping wood, mining, brawls, gifts,
    deliveries and the rest. The game keeps no record of which person you
    already helped.

  * The Thane quests of the 9 holds - the save does not keep a reliable
    trace of them (Thane of Whiterun, for example, is granted by the main
    story).

  * A few single cases, such as Pain in the Necklace, which never ends, and
    Hrodulf's House, which has only one stage.

How to use Mark:

  - Click the Mark chip of a row to tick it; it turns into Done and counts.
    Click again to untick it.
  - Rows are ticked one by one, even when several rows belong to the same
    quest record.
  - In the Townsfolk Requests panel, "Mark all" ticks a whole block.
  - The Mark filter pill shows how many Mark rows a tab has.
  - Ticks are saved automatically and belong to your character: each
    character (by name) has its own ticks, restored every time you load one
    of its saves.


==============================================================================
10. CREATION CLUB CONTENT
==============================================================================

The tracker reads the list of plugins from your save. Entries from a
Creation that is not in your save are hidden, and the counters and the
percentage count only what your game actually has. With the full
Anniversary Edition everything is shown; with Skyrim SE without Creation
Club content, all AE entries (and the AE section of the Skyrim tab) disappear
on their own.


==============================================================================
11. SETTINGS AND FILES
==============================================================================

Everything is stored in the "data" folder next to the program:

  data\settings.json   theme, last opened tab, compact rows, the last save
                       folder, the window size and your Mark ticks
  data\error.log       appears only if something went wrong

The window always opens maximized. If you restore it to a smaller size, that
size is remembered.

To start from scratch, close the program and delete the "data" folder.
To keep your Mark ticks when you update the program, copy the "data" folder
into the new version.


==============================================================================
12. TROUBLESHOOTING
==============================================================================

The program does not start, an error about "python314.dll" or "libs"
  The .exe was separated from the "libs" folder. Unpack the whole archive
  again and start the .exe inside the folder, or use a shortcut.

"Windows protected your PC"
  Click "More info" - "Run anyway". See chapter 3.

The window stays empty
  Install the Microsoft Edge WebView2 Runtime (see chapter 2).

"This isn't a Skyrim save" / "The save file is damaged"
  Pick a .ess file from the Saves folder. If the game was still writing the
  save, wait a few seconds and load it again.

A quest, word or item I have is not counted
  - Read the annotation of that category first - most cases are explained
    there (shouts must be used once, books and collectibles must be in a
    tracked home, enchantments must be disenchanted).
  - Make sure you loaded the newest save.
  - Check that USSEP and USCCP are installed and that no mod changes that
    content.
  - If it still looks wrong, contact the author and add data\error.log if
    it exists, together with the save.


==============================================================================
13. CREDITS, LICENSE AND CONTACT
==============================================================================

Skyrim Tracker Extreme - Copyright (c) 2026 Alexey Insight. All rights
reserved. Free for personal, non-commercial use. See LICENSE.txt for the
full terms.

Credits
  - FallrimTools (ReSaver) by Mark Fairchild - the save-format reading is
    based on its code (Apache License 2.0).
    https://github.com/mdfairch/FallrimTools
  - Force67/recreation - save-format research used for the spell detection.
    https://github.com/Force67/recreation
  - Fonts: Grenze, JetBrains Mono, Space Grotesk and Orbitron (SIL Open Font
    License 1.1).
  - Built with pywebview, Python and other open-source libraries.
  - Developed with the help of Claude (Anthropic).
  Full details and license texts: THIRD_PARTY_NOTICES.txt

Skyrim Tracker Extreme is an unofficial fan project and is not affiliated
with or endorsed by Bethesda Softworks or ZeniMax Media. The Elder Scrolls
and Skyrim are trademarks of their respective owners.

Questions, bug reports or permission requests:
  the comments on the Skyrim Tracker Extreme page on Nexus Mods, or a private
  message to the author there.
