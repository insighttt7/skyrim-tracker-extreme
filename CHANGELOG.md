# Changelog

## v2.1.1 - 2026-11-11

New
- Progress Changed: load another save of the same character and press F5 to see every entry that changed since the save loaded before it. A cross marks a quest that became failed, a tick what is new, a dashed circle what is no longer done. F5 shows and hides the box, Esc closes it.
- F4 opens the save dialog, F11 switches full screen.
- Each tab remembers its status filter between starts, and always opens at its start.
- The page's browser keys (reload, print, find bar and others) are off; Ctrl + plus, minus and 0 still zoom.
- Settings: the gear button next to the search (or F6) opens a box on the right, the mirror of Progress Changed. Language (the language list moved here from the language button); Mark - reset the Mark ticks of the loaded character; View - show or hide the Editor IDs; Tools - open the data folder, reset Progress Changed, reset all settings except Mark ticks, and export every entry not done yet as a CSV file. The program version is shown at the bottom.
- A red "!" in the player panel when the save was made without USSEP, or without USCCP while it has Anniversary Edition content (Creation Club beyond the four free Creations, which USSEP fixes); the tooltip names the missing patch.

Look
- The level ring tooltip shows the experience left to the next level ("1,885 XP to next level") instead of a percentage.
- Dark theme: the annotations, the language list and the COPIED and zoom badges use the colour of the blocks; the chosen language is easier to see.
- The moon of the theme button is drawn smoothly.
- Loading card: the dashed frame stays in the theme colour while a save is read and turns green once it is loaded; in the light theme the frame is bronze; in the dark theme NO SAVE LOADED and READING YOUR SAVE are in the theme colour.
- The line under an annotation title lines up with the line of the block behind it.
- A clicked button no longer shows a focus frame when a key is pressed afterwards.

Fixes
- Rows hidden because their plugin was not in the save (for example Creation Club quests) kept the old language after the language was switched, and showed it once a save with that plugin was loaded.
- When the save lacks a Creation Club plugin used by some quest rows (for example ALMSIVI), a Mark tick or Mark all did not change the counters, the filter pills and the percentage in any tab, and in Townsfolk Requests, Hidden Bosses, Dawnguard, Dragonborn and the later Skyrim blocks the tick itself did not show; the ticks were kept and appeared after the next save was loaded.
- Search across all tabs: after another tab had been opened, the block counters of Locations, Spells, Shouts, Enchanting, Ingredients, Perks, Collectibles and Books showed 0 done (for example Cities 0/10); they now show the real progress.
- Ingredients: Aloe Vera Leaves counted on games older than 1.6.1130, which do not have them (they came with _ResourcePack.esl in that update), so Ingredients could never reach 100%. The row now shows only when the save has _ResourcePack.esl.

Content - 2281 entries
- Locations: Riften Docks (Shadowfoot Sanctum Creation).
- Locations: new Military Camps block with the 16 Civil War camps, 8 of the Imperial Legion and 8 of the Stormcloaks - 436 locations. They follow your side: until you join one all 16 are an Alternative line and count as not discovered; after it your side's camps stay an Alternative line and leave the counter, and the 8 camps of the other side count (the game keeps them on the map once the war is over).
- Books: 412. Added The Legend of Red Eagle, A Kiss, Sweet Mother, Tamrielic Lore: Revised and Saints and Seducers. Removed 10 journals and notes (Discovering Ruunvald I-IV, Admonition Against Ebony, Crypt of the Heart - Draft, Decree of Monument, Midden Incident Report, Spider Experiment Notes, The Keepers of the Razor).
- Books: 9 names follow USSEP, for example Death Blow of Ebernanit, The Nirnroot Missive and Where Were You When the Dragon Broke?
- Collectibles: Diadem of the Savant and Notched Pickaxe, in the new OTHER COLLECTIBLE ITEMS block together with the Kagrumez gems - 46 entries.

## v2.1.0 - 2026-10-26

New
- Languages: entry names in German, Spanish, French, Italian, Japanese, Polish, Russian or Traditional Chinese. Each language is a separate download ("STE - DE.zip" and so on) that goes into the new lang folder; pick it with the language button next to the search. The interface stays in English. The search finds an entry by its translated and by its English name. The choice is remembered.
- Statistics: a new page, opened with the chart button in the player panel. Your favourite weapon, spell, school of magic and shout, and the statistics the game keeps, grouped as General, Quest, Combat, Magic, Crafting, Crime and Other, plus Total Kills. Click STATISTICS to copy the whole list.
- Click an entry name or a quest Editor ID to copy it; a COPIED badge shows what was copied.

Look
- Entry names use the title font; rows keep the same height in every language.
- Shouts show each word with its meaning ("RAAN - Animal"), the dragon word in capitals.
- The fi ligature is removed from the fonts, so "fi" no longer looks glued.
- The Optional chip always comes first.
- Light theme: the counter of the pressed Townsfolk Requests / Hidden Bosses button is now readable.
- Light theme: the active tab no longer changes colour on hover.
- A clicked filter shows its underline at once.
- Tabs switch and progress bars fill at once, with no animation.
- Switching the theme while the top bar and tabs stick to the top no longer flickers.
- A double click on buttons, tabs and counters no longer highlights text.
- The loading card moves faster, and its last step is fully drawn while the tracker builds.
- The loading card frame turns green while a save is read; the error badge is drawn cleanly.
- The Shouts icon has a solid triangle.
- The page styles are rewritten: half the size, same look.

Content
- Dungeon Delving (Townsfolk Requests): rows show the item only, for example Hrolfdir's Shield and Helm of Winterhold.
- Renamed: Liar's Retreat (was Lair's Retreat), Composure, Speed, and Precision, Amethyst Dragon Claw halves.
- Quest Perks in alphabetical order.

## v2.0.0 - 2026-10-20

The program
- Rewritten in Rust (Tauri 2) instead of Python and pywebview. One small exe, no libs folder; starts and reads a save several times faster and uses less memory. The results are the same as in 1.1.0.
- The window appears only when the page is fully drawn, with the theme picture already in place.
- The page zoom (Ctrl + mouse wheel, Ctrl + plus / minus) is remembered; a badge shows the zoom for a moment when it changes.
- Ctrl+F jumps to the search field.
- Loading a save after a save without some Creation Club content no longer leaves rows hidden.

Player panel
- New: Playtime ("191 h 37 min") and the in-game date ("Tirdas, 17th of Frostfall, 4E 205").
- Cyrillic names (for example the location in a Russian game) are shown in the interface font.

Look
- New background pictures for both themes; the panels let the picture show through.
- Dark theme: new colours; chips and filters in both themes are plain coloured words.
- Hearthfire chip in wood tones, so it no longer looks like the Not chip.
- New Hidden Bosses icon.
- The interface is 5% larger on screens 1400 px wide and up (was 10%).
- Blocks open and close instantly, so large blocks no longer stutter.
- Fixes: the mini profile no longer jumps when the sticky bar appears; the Mark flash no longer replays when a tab is opened again; End and scrolling to the bottom keep the page length steady; the theme switch runs smoothly; annotation tooltips never end with a lone dot.

Content - 2268 entries
- Quests (617): new Townsfolk Requests rows Kill the Forsworn Leader and Kill the Dragon, and a new Some Light Theft block (Dengeir of Stuhn, Malur Seloth, Stands-In-Shallows); new Anniversary Edition quest Through a Glass, Darkly. If I had a Hammer, Swift as an Arrow and The Edge of Ruin now count by their final stage (the game does not mark them completed).
- Locations (419): a location counts as Discovered when you can fast travel to it - a marker only shown on the map by a note or a quest no longer counts. Gallows Hall and Japhet's Folly removed (no lasting map marker); Chillwind Depths and Blackbone Isle added; The Chill now uses the USSEP map marker.

## v1.1.0 - 2026-10-10
- New themes: Stalhrim Hollow (dark) and Dragonbone Parchment (light) replace Daedric Space and Stalhrim Parchment - new colours, chips, cursors and fonts (Enriqueta, Barlow Semi Condensed, Crimson Text, all hinted for sharp text on Windows).
- New program icon to match the themes.
- The light theme is the default on the first start; a picked theme is still remembered.
- settings.json stores the theme as dark / light; the old values from 1.0.0 are converted automatically.
- Fix: after "open tab" in the search results, sections without matching rows are hidden (their headings and buttons were left on screen).
- Quest "Hrodulf's House" renamed to "Hrodulf's Madness" (the location keeps its name).
- Berit's Ashes removed from the ingredients: a unique quest item (fixed by the Unofficial Patch) - 183 ingredients.
- Spells: Restoration ends with Dawnguard and Vampire blocks for the side-locked spells (Stendarr's Aura, Sun Fire, Vampire's Bane / Heal Undead). They follow the Dawnguard side like the quest branches: the other side's spells show Alternative line and count only if learned; new Alternative line filter in Spells. Heal Undead is no longer Optional.
- Black Books block counts all 7 books (7/7); the two that are also Dragonborn main quests still count once in the overall progress.
- Heart Stones is a Mark quest (ticked by hand).
- Honor Thy Family is Optional and goes last in Dark Brotherhood - Miscellaneous Quests.
- Coming of Age counts as done when its final stage (81) is reached - the game does not mark it completed.
- The First Catch quest row is removed from the First Catch block.
- All 85 stage-checked quests verified in game; new final stages for Surgery (50), Dragon's Breath Mead (20), Sanuarach Mine (100), My Pet Mudcrab (30), The Pale Lady (100) and Lair's Retreat (100). Speak to Degaine is read from T01DegaineFavor only.
- Thane of the Rift goes last in its block, before Vald's Debt.
- Vald's Debt is Optional.
- Out of Balance and Aftershock are Mark quests (the game resets them after completion).
- Trius' Trinket removed (the quest cannot be finished).
- New Wild Horses block in Anniversary Edition: Creature of Legend (now read from the save) and the seven horses; Horse Whisperer removed.
- New Hidden Bosses panel, opened from the Skyrim tab next to Townsfolk Requests: Vulthuryol (Blackreach) and The Reaper (Soul Cairn), Mark rows that count in Quests.
- Search also finds Townsfolk Requests and Hidden Bosses rows.
- Mark chip icon is a pencil.
- Enchanting: Smithing Expertise removed (it cannot be obtained with the Unofficial Patch) - 57 effects.
- Collectibles: every Kagrumez gem counts on its own in the progress - 44 entries.
- Player panel: "Save v:" and "Form v:" with a colon; the save number comes last.
- 611 quests, 2262 entries.
- Master Transmute is Optional; Optional spells (Master Transmute, Conjure Staada) go last in their block.
- The page is 10% larger on screens 1400 px wide and up.
- The AE section heading reads ANNIVERSARY EDITION.
- Third-party notices: the Force67/recreation code is used with the author's permission; font notices updated for the new fonts.

## v1.0.0 - 2026-09-30
- First release: 2254 entries in 9 categories, Mark quests, two themes, portable exe.
