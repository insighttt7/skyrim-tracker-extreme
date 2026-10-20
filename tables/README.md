# Tracker tables

All files: separator `;`, UTF-8 without BOM, `|` between several values in one cell.
Rows are matched by their key, never by position or name: `EditorID` (spells, shouts,
enchanting, ingredients, perks), `BaseEditorIDs` (collectibles, books), `Key` (quests:
the EditorID, or `EditorID|Name` when several rows share one) and the first marker of
`MarkerFormIDs` as `Plugin:LocalID` (locations). A key must be unique in its table -
the parser stops with an error otherwise. The tracker page builds its rows from the
tables, in table order (`Block` and `SubBlock` group them); `Order` numbers the rows
1, 2, 3 ... The tables are built into the exe, so rebuild after any change.

| File | Columns |
|---|---|
| `quests_tracker.csv` | `Order;Tab;Section;Block;SubBlock;Name;EditorIDs;Key;NoCount;FormIDCandidates;OverrideMap;Category;ContentPlugin;Source` |
| `locations_tracker.csv` | `Order;Block;Name;Tags;MarkerFormIDs` |
| `MapMarkerExport.csv` | `FormID;Plugin;EditorID;MarkerName;MarkerType;AlwaysVisible;LinkedLocationEditorID;CellContext;FNAMHex;CanTravelTo;...;Verdict` - map markers exported from xEdit |
| `spells_tracker.csv` | `Order;Block;SubBlock;Name;Tags;Plugin;LocalID;EditorID` |
| `shouts_tracker.csv` | `Order;Block;Name;Tags;Plugin;LocalID;EditorID` |
| `enchanting_tracker.csv` | `Order;Block;Name;Tags;Plugin;LocalID;EditorID` |
| `ingredients_tracker.csv` | `Order;Block;Name;Tags;Plugin;LocalID;EditorID;AltCandidates;ContentPlugin` |
| `perks_tracker.csv` | `Order;Block;SubBlock;Name;Tags;Plugin;LocalID;EditorID;Source` |
| `collectibles_tracker.csv` | `Order;Block;Name;Tags;Mode;Required;BaseKeys;BaseEditorIDs;PersistentRefs` |
| `collectibles_houses.csv` | `Kind;House;Plugin;LocalID;EditorID;Name` - cells, containers and mannequins of the 8 tracked homes |
| `books_tracker.csv` | `Order;Block;SubBlock;Name;Tags;BaseKeys;BaseEditorIDs;PersistentRefs` |

## Quests: how a quest counts (`Category`)

- **flag** - done when the quest has its "completed" flag in the save;
- **override** - done when the stage from `OverrideMap` is reached;
- **handle** - never read from the save, ticked by hand with the Mark chip
  (radiant and repeatable quests, thanes, Townsfolk Requests, Hidden
  Bosses).

## Grouping and plugins

- `SubBlock` - a nested block inside `Block` (empty = none).
- `ContentPlugin` (quests, ingredients) - the plugin the content comes from, when it
  is not the plugin of the record itself. Rows of a plugin that is not in the save are
  hidden and not counted.
- `Source` (quests) - shows a DLC chip, for example `Dawnguard`, on a row whose record
  is in another plugin.

## Tags

`Optional` - not needed for 100%, counts only when done.
`AE` - Anniversary Edition / Creation Club content.
Several tags are separated by `|`, for example `Optional|AE`.

## Locations

A new location needs a map marker FormID from `MapMarkerExport.csv`.
Several markers for one location are separated by `|` (any of them counts).
