# Skyrim Tracker Extreme

A 100% completion tracker for **Skyrim Special Edition / Anniversary Edition**.
It reads a `.ess` save and shows the progress over 2254 entries in 9 categories:
quests, locations, spells, shouts, enchanting, ingredients, perks, collectibles and books.

All rights reserved - see [LICENSE.txt](LICENSE.txt).
The user manual that ships with the program is [docs/README.txt](docs/README.txt).

---

## Contents

1. [Repository layout](#repository-layout)
2. [Requirements](#requirements)
3. [Build on your PC](#build-on-your-pc)
4. [Build on GitHub (Actions)](#build-on-github-actions)
5. [Run from source](#run-from-source)
6. [Check the parser on a save](#check-the-parser-on-a-save)
7. [Editing the tables](#editing-the-tables)
8. [Releasing a new version](#releasing-a-new-version)
9. [AI in this project](#ai-in-this-project)

---

## Repository layout

```
skyrim-tracker-extreme/
├── src/
│   ├── app.py              program window, settings, save picker
│   └── parse_ess.py        reads a save and produces the tracker data
├── web/
│   └── Skyrim_Tracker_v12.html   the tracker page (both themes)
├── tables/                 the 11 tracker tables (CSV)
├── assets/
│   └── SkyrimTrackerExtreme.ico
├── tools/
│   └── pack.py             packs page + tables into the program, release zip
├── docs/
│   ├── README.txt          user manual (goes into the release)
│   └── notices_static.txt  template for THIRD_PARTY_NOTICES.txt
├── .github/workflows/
│   └── build.yml           build on GitHub
├── build.bat               one-click build
├── requirements.txt        exact library versions for the build
├── CHANGELOG.md
└── LICENSE.txt
```

## Requirements

- Windows 10 or 11, 64-bit
- Python 3.14 (`python --version` must work in the console)
- The build libraries, installed once:

```
python -m pip install -r requirements.txt
```

## Build on your PC

Double-click `build.bat` (or run it in a console from the repository folder).
It does four steps:

| Step | What happens |
|---|---|
| 1/4 | `tools\pack.py` copies `app.py` and `parse_ess.py` without comments and packs the page and the tables into the program |
| 2/4 | PyInstaller builds the exe (1-3 minutes) |
| 3/4 | `tools\pack.py --release` adds LICENSE, README and third-party notices, writes the release zip and `SHA256.txt` |
| 4/4 | the temporary `_gen` folder is removed |

Result:

```
dist\Skyrim Tracker Extreme\Skyrim Tracker Extreme.exe   the ready program
dist\Skyrim Tracker Extreme v1.0.0.zip                   the release archive
dist\SHA256.txt                                          checksums of the exe and the zip
```

## Build on GitHub (Actions)

`.github/workflows/build.yml` runs the same `build.bat` on a GitHub Windows machine.

- **By hand:** Actions tab -> **Build** -> **Run workflow**. The zip and `SHA256.txt`
  appear under **Artifacts** at the bottom of the run page.
- **By a version tag:** pushing a tag like `v1.0.1` builds and also creates a **Release**
  with the zip and `SHA256.txt`.

An exe built on GitHub is not byte-identical to one built at home (normal for PyInstaller);
it works the same.

## Run from source

Starts the program without building an exe (useful to test a change quickly):

```
python src\app.py
```

Settings and the error log go to `src\data\` (ignored by git).

## Check the parser on a save

Writes `<save>.tracker.json` next to the save, without opening the program:

```
python src\parse_ess.py "<path to save>.ess" tables\locations_tracker.csv tables\MapMarkerExport.csv tables\quests_tracker.csv tables\spells_tracker.csv tables\shouts_tracker.csv tables\enchanting_tracker.csv tables\ingredients_tracker.csv tables\perks_tracker.csv tables\collectibles_tracker.csv tables\collectibles_houses.csv tables\books_tracker.csv --json-only
```

Any table can be replaced by `-` to skip that category.

To make sure a packed build reads a save exactly like the source parser,
compare it with a `tracker.json` made by the command above:

```
python tools\pack.py --check "<save>.ess" "<save>.tracker.json"
```

## Editing the tables

See [tables/README.md](tables/README.md) for the format of every table.

The short rules:
- separator `;`, encoding UTF-8 without BOM, `|` separates several values inside one cell;
- row order and names must match the tracker page exactly - rows are matched by their
  `Order` number, not by name;
- after any change, run the parser on a real save and check the result in the program.

## Releasing a new version

1. Change `APP_VERSION` in `src/app.py` (for example `1.0.1`).
2. Write the changes in `CHANGELOG.md`.
3. Run `build.bat` and test the program on real saves.
4. Commit the changes.
5. Optional: create a tag `v1.0.1` (Releases -> Draft a new release -> new tag)
   to get the release built on GitHub.

## AI in this project

1. The code (the app, the save parser and the build scripts) was written together with Claude (Anthropic).
2. Design of the tracker page: colours and backgrounds for both themes.
3. Debugging and bug fixes.
4. The preview image.
