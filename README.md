# Skyrim Tracker Extreme

A 100% completion tracker for **Skyrim Special Edition / Anniversary Edition**.
It reads a `.ess` save and shows the progress over 2268 entries in 9 categories:
quests, locations, spells, shouts, enchanting, ingredients, perks, collectibles and books.
It also shows the statistics kept in the save, copies a row name or a quest Editor ID with one click,
and shows the row names in other languages from language files in `lang\`.

All rights reserved - see [LICENSE.txt](LICENSE.txt).
The user manual that ships with the program is [docs/README.txt](docs/README.txt).

---

## Contents

1. [Repository layout](#repository-layout)
2. [Building](#building)
3. [Build on GitHub (Actions)](#build-on-github-actions)
4. [Check the parser on a save](#check-the-parser-on-a-save)
5. [Editing the tables](#editing-the-tables)
6. [Releasing a new version](#releasing-a-new-version)
7. [AI in this project](#ai-in-this-project)

---

## Repository layout

```
skyrim-tracker-extreme/
├── src-tauri/                the program (Rust + Tauri)
│   ├── src/main.rs           window, settings, save picker
│   ├── src/shim.js           connects the page to the program
│   ├── build.rs              prepares the page for the build
│   └── icons/icon.ico
├── ste-core/                 the save parser (Rust, standard library only)
│   └── src/bin/ste-parse.rs  command-line version of the parser
├── web/
│   ├── Skyrim_Tracker_v15.html   the tracker page (both themes)
│   ├── fonts/
│   └── bg/                   theme pictures
├── tables/                   the 12 tracker tables (CSV)
├── docs/
│   ├── README.txt            user manual (goes into the release)
│   ├── README_lang.txt       goes into the release, in lang\
│   └── THIRD_PARTY_NOTICES.txt
├── .github/workflows/
│   └── build.yml             build on GitHub
├── build.bat                 one-click build
├── BUILD.md                  what to install
├── CHANGELOG.md
└── LICENSE.txt
```

The page, the fonts, the pictures and the tables are built into the exe;
the program folder holds only the exe, its `data\` folder and `lang\` for language files.

## Building

Install Rust and the Visual Studio C++ build tools once - see [BUILD.md](BUILD.md).
Then double-click `build.bat`. The result:

```
dist\Skyrim Tracker Extreme\Skyrim Tracker Extreme.exe
```

with `README.txt`, `LICENSE.txt` and `THIRD_PARTY_NOTICES.txt` next to it.

## Build on GitHub (Actions)

`.github/workflows/build.yml` builds the exe on a GitHub Windows machine:
Actions tab -> **Build** -> **Run workflow**. The exe appears under **Artifacts**
at the bottom of the run page.

## Check the parser on a save

`ste-parse.exe` (built together with the program, in `target\release\`) writes
`<save>.tracker.json` without opening the program:

```
target\release\ste-parse.exe "<path to save>.ess" tables
```

## Editing the tables

See [tables/README.md](tables/README.md) for the format of every table.

The short rules:
- separator `;`, encoding UTF-8 without BOM, `|` separates several values inside one cell;
- the tracker page builds its rows from the tables, in table order;
- every row keeps a unique key (EditorID etc., see [tables/README.md](tables/README.md)) -
  saves and Mark ticks are matched by that key, not by the row position or name;
- the tables are built into the exe: rebuild after a change, then check the result on a real save.

## Releasing a new version

1. Change `version` in `src-tauri/Cargo.toml` and `src-tauri/tauri.conf.json` (for example `2.0.1`).
2. Write the changes in `CHANGELOG.md`.
3. Run `build.bat` and test the program on real saves.
4. Commit the changes.

## AI in this project

1. The code, written together with Claude (Anthropic).
2. The background art for both themes.
