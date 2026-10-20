# Changelog

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
