"""
parse_ess.py
------------
Reads a Skyrim SE/AE save file (.ess) and extracts from the ChangeForm table:

1. QUST (quests) - RefID + reached stages.
2. REFR (location map markers) - "discovered / not discovered on the map"
   status (Discovered).

The format was taken from the primary source (github.com/mdfairch/FallrimTools,
Apache-2.0): Header.java, CompressionType.java, WStringElement.java/
WString.java, ESS.java, FileLocationTable.java, GlobalData.java,
ChangeForm.java, ChangeFormQust.java, ChangeFormRefr.java,
ChangeFormFlags.java, ChangeFormInitialData.java, ChangeFormExtraData.java,
ChangeFormExtraDataData.java, ChangeFlagConstantsQust.java, GeneralElement
.java, VSVal.java, PluginInfo.java, Plugin.java, RefID.java.

LOCATION DISCOVERY (Discovered) - how it works (fully confirmed from the
sources + re-checked byte for byte on 3 real saves):
  - It is stored NOT in LCTN but in the REFR record of the map marker itself.
  - Inside the REFR it is one byte of the "MapMarker" value (ExtraData TYPE=44),
    present only when change_flags has bit 31
    (CHANGE_REFR_EXTRA_GAME_ONLY). Without that bit there is no override at
    all and this ChangeForm does not define the status (the plugin's base
    value is used, FNAM Map Flags, which the parser does not read - it comes
    from ExportMapMarkers.csv, AlwaysVisible column).
  - Value 0x03 (bits Visible=0x01 | CanTravelTo=0x02, same meaning as FNAM
    in the .esm) = discovered. 0x00 = not discovered.
  - If EXTRADATA contains an ExtraData type whose structure was not confirmed
    from the sources (see parse_extra_data_element), the status is HONESTLY
    marked UNKNOWN instead of being filled in by a guess. This is a core
    project rule: NEVER guess field sizes.

IMPORTANT - deliberate simplification: to reach the ChangeForms we do NOT parse
TABLE1/TABLE2 completely - we jump straight to `changeFormsOffset` from the
FileLocationTable, which is a separate confirmed field.

USAGE:
    py parse_ess.py "path\\to\\your\\save.ess" [MapMarkerExport.csv]

    The second (optional) argument is the CSV from ExportMapMarkers_v2.pas
    (columns FormID;Plugin;EditorID;MarkerName;...). When given, Discovered
    is computed ONLY for REFRs whose (Plugin, FormID) are in that list (that
    is, only for real map markers) - faster, and it does not produce extra
    "UNKNOWN" rows for ordinary references (containers, doors etc.) that
    happen to have bit 31 set for another reason. Without it all REFRs are
    processed (slower and noisier report, but just as correct).

Dependencies: pip install lz4

Output goes to files next to the save (UTF-8):
  <save>.quests_report.txt / .quests_resolved.csv
  <save>.locations_report.txt / .locations_resolved.csv
  <save>.collectibles_report.txt / .collectibles_final.csv - Collectibles
      (arguments 10 and 11: collectibles_tracker.csv collectibles_houses.csv)
  <save>.books_report.txt / .books_final.csv - Books
      (argument 12: books_tracker.csv; homes - the same collectibles_houses.csv)
  <save>.plugins_final.csv - the save's plugin list (always written, needs no
      arguments): the HTML tracker hides rows of CC plugins that are not in
      this save (plugin filter)
"""

import sys
import os
import csv
import struct
import zlib
import lz4.block


# ---------------------------------------------------------------------------
# Hooks for the desktop app (Skyrim Tracker Extreme.exe). With the defaults
# below the script behaves exactly as the command line tool.
#   CSV_DATA    - {name: raw bytes} of tracker CSVs embedded in the app; a path
#                 found here is read from memory instead of the disk
#   PROGRESS    - callable(stage_index) for the loader card (stages 0..13 as in
#                 TrackerLoader.STAGES of the tracker page)
#   JSON_PATH   - where write_tracker_json() writes (None = next to the save)
#   LAST_RESULT - the dict written by the last write_tracker_json() call
# ---------------------------------------------------------------------------
CSV_DATA = {}
PROGRESS = None
JSON_PATH = None
LAST_RESULT = None


def _open_text(path, errors=None):
    """Opens a tracker CSV: from CSV_DATA when embedded, otherwise from disk.
    Decoding is the same in both cases (utf-8-sig, optional errors mode)."""
    import io
    if path in CSV_DATA:
        return io.StringIO(CSV_DATA[path].decode('utf-8-sig', errors or 'strict'), newline='')
    return open(path, encoding='utf-8-sig', newline='', errors=errors)


def _stage(index):
    if PROGRESS is not None:
        PROGRESS(index)


ENCODING = 'utf-8'  # confirmed on a real save: strings are UTF-8, not cp1251


class Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def read(self, n):
        b = self.data[self.pos:self.pos + n]
        if len(b) != n:
            raise EOFError(f"Expected {n} bytes at position {self.pos}, "
                            f"got {len(b)} (end of data)")
        self.pos += n
        return b

    def u8(self):
        return self.read(1)[0]

    def i8(self):
        v = self.read(1)[0]
        return v - 256 if v >= 128 else v

    def u16(self):
        return struct.unpack('<H', self.read(2))[0]

    def i16(self):
        return struct.unpack('<h', self.read(2))[0]

    def u32(self):
        return struct.unpack('<I', self.read(4))[0]

    def i32(self):
        return struct.unpack('<i', self.read(4))[0]

    def u64(self):
        return struct.unpack('<Q', self.read(8))[0]

    def f32(self):
        return struct.unpack('<f', self.read(4))[0]

    def wstring_raw(self):
        """WStringElement/WString: uint16 length + that many RAW bytes."""
        length = self.u16()
        return self.read(length)

    def wstring(self, encoding=ENCODING):
        raw = self.wstring_raw()
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            return raw.decode(encoding, errors='replace')

    def vsval(self):
        """VSVal.java, confirmed from the source: the low 2 bits of the first
        byte give the total size: 0->1 byte, 1->2 bytes, 2 or 3->3
        bytes. Value = little-endian bytes >> 2."""
        b0 = self.u8()
        size = b0 & 0x3
        if size == 0:
            raw = b0
        elif size == 1:
            b1 = self.u8()
            raw = b0 | (b1 << 8)
        else:
            b1 = self.u8()
            b2 = self.u8()
            raw = b0 | (b1 << 8) | (b2 << 16)
        return raw >> 2

    def refid_raw(self):
        """ESS.ESSContext.readRefID, confirmed: exactly 3 raw bytes,
        big-endian join (B1<<16 | B2<<8 | B3). Returns the raw 24-bit
        value (for isZero() checks inside ExtraData etc.) - NOT the
        resolved (plugin, local_id); to resolve the top-level RefID of a
        ChangeForm record use resolve_refid()."""
        b1, b2, b3 = self.u8(), self.u8(), self.u8()
        return (b1 << 16) | (b2 << 8) | b3

    # Backward compatibility with the old name
    def refid(self):
        return self.refid_raw()


# ---------------------------------------------------------------------------
# ChangeForm type codes (Skyrim), confirmed from the ChangeForm.java Type enum
QUST_TYPE_CODE = 8
REFR_TYPE_CODE = 0
ACHR_TYPE_CODE = 1   # same code as kAchr=1 in Force67/recreation - two
                     # independent sources agreeing confirms the format
NPC_TYPE_CODE = 9    # likewise, kNpc=9
WOOP_TYPE_CODE = 34  # confirmed on a real save (several
                     # runs of diagnose_shouts.py, including a control test
                     # before/after learning a word) - not from the sources (Word
                     # of Power is not listed in any known FallrimTools/UESP enum).
                     # "Word learned" signal = the mere presence of a WOOP ChangeForm
                     # with this type_code, whatever its value.
                     # IMPORTANT (confirmed by the Zii/Become Ethereal experiment):
                     # the engine writes this record not when the word is learned
                     # at the wall but later - apparently only after the first
                     # real use of a shout containing that word. Practical
                     # limitation for the tracker: a word the player learned but
                     # never used may temporarily not count. Decision: do not fight this in the parser, warn in
                     # the checklist itself - "use each of the 27 shouts at
                     # least once for correct tracking".

ENCH_TYPE_CODE = 48  # confirmed on a real save
                     # (diagnose_enchanting.py): the save has exactly 50 ChangeForms
                     # with this type_code, exactly the 50 base ENCH effects the
                     # game shows as learned at the enchanting table; the 8
                     # unlearned ones have no record. Checked name by name
                     # against table screenshots - 50/50 matches, 0 extra.
                     # "Effect learned" signal = the mere presence of a ChangeForm
                     # for the ENCH base (MasterPlugin+LocalID from enchanting_tracker.csv).
                     # The MGEFs of these effects have no ChangeForm at all - the
                     # signal is on ENCH only. All 50 have identical content
                     # (flags=0x00000001, 6 bytes `49 00 00 00 00 00`), but its
                     # meaning is NOT interpreted - only presence counts;
                     # content that differs from this sample is only logged.
ENCH_OBSERVED_FLAGS = 0x00000001
ENCH_OBSERVED_PAYLOAD = bytes.fromhex('490000000000')

INGR_TYPE_CODE = 16  # confirmed TWICE: the ChangeForm type table on UESP
                     # (Skyrim Mod:Save File Format, 16 = INGR) + empirically on
                     # save1/save2/save3 (diagnose_ingredients.py).
                     # Format (confirmed by a control experiment on save3):
                     # change_flags = 0x80000000, data = uint32 LE, the low 4
                     # bits = mask of learned effects, bit N = effect N+1 in
                     # INGR record order (as in ingredients_tracker.csv).
                     #   Wild Grass Pod + Burnt Spriggan Wood (sharing only
                     #   Fortify Alteration) -> Wild Grass Pod = 0x04 (3rd effect),
                     #   Burnt Spriggan Wood = 0x02 (2nd effect) - both matched
                     #   the prediction.
                     # IMPORTANT: a record can exist with mask 0x00 (Netch Jelly
                     # after a failed brewing attempt) - the PRESENCE of the record
                     # means nothing, unlike ENCH/WOOP; only the mask counts.
                     # Any deviation (other flags, length != 4, bits above 0x0F)
                     # is not interpreted -> status UNKNOWN + raw hex in the report.
INGR_OBSERVED_FLAGS = 0x80000000

PLAYER_LOCAL_ID = 0x14       # ACHR RefID of the player (PlayerRef), fixed by Bethesda
PLAYER_BASE_LOCAL_ID = 0x07  # NPC_ FormID of the player's base record (Player), fixed


def parse_header(f: Reader, log):
    """Returns a dict with the header fields + startingOffset (position in
    the source file right after the Header, needed to rebase FLT offsets)."""
    magic = f.read(13)
    if magic != b'TESV_SAVEGAME':
        raise ValueError(f"Unexpected signature: {magic!r}. "
                          f"Is this really a Skyrim SE/AE save file?")

    header_size = f.u32()          # = partialSize(), without magic/itself/screenshot
    header_start = f.pos

    version = f.u32()
    save_number = f.u32()
    name = f.wstring()
    level = f.u32()
    location = f.wstring()
    game_date = f.wstring()
    race_eid = f.wstring()
    sex = f.u16()
    cur_xp = f.f32()
    needed_xp = f.f32()
    filetime = f.u64()
    shot_w = f.u32()
    shot_h = f.u32()

    # CompressionType.read(): short (2 bytes), confirmed from the source.
    comp_type = f.u16()

    consumed = f.pos - header_start
    if consumed != header_size:
        raise ValueError(
            f"Header size mismatch: HEADERSIZE={header_size}, "
            f"actually read {consumed} bytes. This may not be a regular "
            f"SKYRIM_SE Steam save (VR/another platform?), where the "
            f"compression field is laid out differently.")

    BYPP = 4  # SE/AE = RGBA
    screenshot_bytes = BYPP * shot_w * shot_h
    f.read(screenshot_bytes)  # skip the screenshot pixels

    starting_offset = f.pos  # <-- base for rebasing the FLT offsets

    log(f"Save version: {version}, save_number: {save_number}")
    log(f"Player: {name}, level {level}")
    log(f"Location: {location}")
    log(f"In-game date: {game_date}, race: {race_eid}, sex: {sex}")
    log(f"Screenshot: {shot_w}x{shot_h}, compression type: {comp_type} "
        f"(0=none,1=zlib,2=lz4)")

    return {
        'starting_offset': starting_offset,
        'comp_type': comp_type,
        # player / save info for the tracker page (tracker.json)
        'version': version, 'save_number': save_number, 'name': name,
        'level': level, 'location': location, 'game_date': game_date,
        'race_eid': race_eid, 'sex': sex, 'cur_xp': cur_xp, 'needed_xp': needed_xp,
    }


def decompress_body(f: Reader, comp_type, log):
    if comp_type == 0:
        body = f.data[f.pos:]
        log(f"File body is NOT compressed, size {len(body)} bytes")
        return body

    uncompressed_len = f.u32()
    compressed_len = f.u32()
    comp_bytes = f.read(compressed_len)

    if comp_type == 1:
        raw = zlib.decompress(comp_bytes)
    elif comp_type == 2:
        raw = lz4.block.decompress(comp_bytes, uncompressed_size=uncompressed_len)
    else:
        raise ValueError(f"Unknown compression type: {comp_type}")

    if len(raw) != uncompressed_len:
        log(f"[warn] size after decompression {len(raw)}, expected {uncompressed_len}")

    log(f"File body was compressed (type {comp_type}): "
        f"{compressed_len} -> {len(raw)} bytes")
    return raw


def parse_plugin_info(b: Reader, log):
    """PluginInfo.java, confirmed from the source."""
    plugin_info_size = b.u32()
    start_pos = b.pos

    number_of_full = b.u8()
    full_plugins = [b.wstring() for _ in range(number_of_full)]

    return plugin_info_size, start_pos, number_of_full, full_plugins


def get_plugin_for(formid, full_plugins, lite_plugins):
    """ESS.getPluginFor(), confirmed from the source."""
    index = (formid >> 24) & 0xFF
    subindex = (formid & 0xFFFFFF) >> 12
    if 0 <= index < 0xFE and index < len(full_plugins):
        return full_plugins[index], False
    elif index == 0xFE and 0 <= subindex < len(lite_plugins):
        return lite_plugins[subindex], True
    return None, False


def resolve_refid(raw, full_plugins, lite_plugins, form_ids):
    """RefID.java, confirmed from the source. Returns
    (plugin_name_or_None, local_form_id, resolution_kind)."""
    val_part = raw & 0x3FFFFF
    type_idx = (raw >> 22) & 0x3

    if val_part == 0:
        return None, 0, 'ZERO'

    if type_idx == 0:  # FORMIDX -> an INDEX into the FormID array, not a direct value
        form_index = val_part - 1
        if 0 <= form_index < len(form_ids):
            formid = form_ids[form_index]
            plugin, is_lite = get_plugin_for(formid, full_plugins, lite_plugins)
            local_id = formid & (0xFFF if is_lite else 0xFFFFFF)
            return (plugin, local_id, 'FORMIDX')
        else:
            return (None, -1, 'FORMIDX_OUT_OF_RANGE')
    elif type_idx == 1:  # DEFAULT -> implies full_plugins[0]
        plugin = full_plugins[0] if full_plugins else None
        return (plugin, val_part, 'DEFAULT')
    elif type_idx == 2:  # CREATED -> object created dynamically in the game
        return ('(Created)', val_part, 'CREATED')
    else:
        return (None, 0, 'INVALID')


def parse_qust_changeform(data: bytes, change_flags: int, log, refid_hex):
    """Partial parse of ChangeFormQust.java: fields are read STRICTLY in the
    order they are declared in the source, and we stop right after
    QUEST_STAGES - the rest (QUEST_OBJECTIVES/QUEST_RUN_DATA/ALREADY_RUN) is not needed."""
    r = Reader(data)

    def has_bit(n):
        return (change_flags >> n) & 1

    if has_bit(0):  # CHANGE_FORM_FLAGS
        log(f"  [skip] refid={refid_hex}: CHANGE_FORM_FLAGS bit is set "
            f"-> this record is not parsed")
        return None

    try:
        quest_flags = None
        if has_bit(1):  # CHANGE_QUEST_FLAGS -> Flags.Short, 2 bytes
            quest_flags = r.u16()
        if has_bit(2):  # CHANGE_QUEST_SCRIPT_DELAY -> float, 4 bytes
            r.f32()
        if has_bit(31):  # CHANGE_QUEST_STAGES -> VSVal count + count*(short+byte)
            count = r.vsval()
            stages = []
            stage_status = []
            for _ in range(count):
                stage = struct.unpack('<h', r.read(2))[0]
                status = r.u8()
                stages.append(stage)
                stage_status.append((stage, status))
            return {'quest_flags': quest_flags, 'stages': stages, 'stage_status': stage_status}
        else:
            return {'quest_flags': quest_flags, 'stages': [], 'stage_status': []}
    except EOFError as e:
        log(f"  [warn] refid={refid_hex}: ran out of data while parsing QUST "
            f"({e}) - the ChangeForm offset may be wrong")
        return None


# ===========================================================================
# LOCATIONS: "discovered on the map" status (REFR ChangeForm)
# ===========================================================================

class ParseAbort(Exception):
    """A structure that CANNOT be parsed further safely was met
    (unknown/unconfirmed ExtraData type). Means: the status of this record
    is UNKNOWN, not a guessed value. Project rule: in this situation we MUST
    stop instead of guessing a field size."""
    pass


def _read_vs_elem_array(r: Reader, element_reader):
    count = r.vsval()
    for _ in range(count):
        element_reader(r)


def _read_32_elem_array(r: Reader, element_reader):
    count = r.u32()
    for _ in range(count):
        element_reader(r)


def _read_ints_vs(r: Reader):
    count = r.vsval()
    r.read(4 * count)


def _read_floats_vs(r: Reader):
    count = r.vsval()
    r.read(4 * count)


def _read_longs_vs(r: Reader):
    count = r.vsval()
    r.read(8 * count)


def _read_bytes_vs(r: Reader):
    count = r.vsval()
    r.read(count)


def parse_extra_data_element(r: Reader):
    """One element of ChangeFormExtraDataData.java. Returns
    (type_code, map_marker_value_or_None). Repeats the field order and sizes
    of the source for every TYPE. For a type missing from this switch (same
    as the switch in the source - its default throws) we raise ParseAbort.
    For type 45 (LeveledCreature) the structure is PARTLY unknown (it needs
    ChangeFormNPC.java, which we do not have) - also ParseAbort, not a guess."""
    type_code = r.u8()
    map_marker_value = None

    if type_code == 0:      # NULL
        pass
    elif type_code == 4:    # ExtraExtraData1
        parse_extra_data_element(r)
    elif type_code == 8:    # ExtraExtraData2
        parse_extra_data_element(r)
        parse_extra_data_element(r)
    elif type_code == 12:   # ExtraExtraData3
        parse_extra_data_element(r)
        parse_extra_data_element(r)
        parse_extra_data_element(r)
    elif type_code == 22:   # Worn
        pass
    elif type_code == 23:   # WornLeft
        pass
    elif type_code == 24:   # PackageStartLocation
        r.refid_raw(); r.read(12); r.f32()
    elif type_code == 25:   # Package
        r.refid_raw(); r.refid_raw(); r.u32(); r.read(3)
    elif type_code == 26:   # TrespassPackage
        ref = r.refid_raw()
        if ref == 0:
            raise ParseAbort("TrespassPackage(26) incomplete (ref=0)")
    elif type_code == 27:   # RunOncePacks
        _read_ints_vs(r)
    elif type_code == 28:   # ReferenceHandle
        r.refid_raw()
    elif type_code == 29:   # Unknown29
        pass
    elif type_code == 30:   # LevCreaModifier
        r.u32()
    elif type_code == 31:   # Ghost
        r.u8()
    elif type_code == 32:   # UNKNOWN32
        pass
    elif type_code == 33:   # Ownership
        r.refid_raw()
    elif type_code == 34:   # Global
        r.refid_raw()
    elif type_code == 35:   # Rank
        r.refid_raw()
    elif type_code == 36:   # Count
        r.u16()
    elif type_code == 37:   # Health
        r.f32()
    elif type_code == 39:   # TimeLeft
        r.u32()
    elif type_code == 40:   # Charge
        r.f32()
    elif type_code == 42:   # Lock
        r.read(2); r.refid_raw(); r.u32(); r.u32()
    elif type_code == 43:   # Teleport
        r.read(12); r.read(12); r.u8(); r.refid_raw()
    elif type_code == 44:   # MapMarker - the value the tracker reads
        map_marker_value = r.u8()
    elif type_code == 45:   # LeveledCreature - needs ChangeFormNPC.java, not available
        raise ParseAbort("LeveledCreature(45): ChangeFormNPC.java structure not confirmed")
    elif type_code == 46:   # LeveledItem
        r.u32(); r.u8()
    elif type_code == 47:   # Scale
        r.f32()
    elif type_code == 49:   # NonActorMagicCaster
        r.u32(); r.refid_raw(); r.u32(); r.u32(); r.refid_raw(); r.f32(); r.refid_raw(); r.refid_raw()
    elif type_code == 50:   # NonActorMagicTarget
        r.refid_raw()

        def _magic_target(rr):
            rr.refid_raw(); rr.u8(); rr.vsval(); _read_bytes_vs(rr)
        _read_vs_elem_array(r, _magic_target)
    elif type_code == 52:   # PlayerCrimeList
        _read_longs_vs(r)
    elif type_code == 53:   # Unknown53
        pass
    elif type_code == 56:   # ItemDropper
        r.refid_raw()
    elif type_code == 61:   # CannotWear
        pass
    elif type_code == 62:   # ExtraPoison
        r.refid_raw(); r.u32()
    elif type_code == 68:   # FriendHits
        _read_floats_vs(r)
    elif type_code == 69:   # HeadingTarget
        r.refid_raw()
    elif type_code == 72:   # StartingWorldOrCell
        r.refid_raw()
    elif type_code == 73:   # HotKey
        r.u8()
    elif type_code == 76:   # InfoGeneralTopic
        r.wstring_raw(); r.read(5)
        for _ in range(4):
            r.refid_raw()
    elif type_code == 77:   # HasNoRumors
        r.u8()
    elif type_code == 79:   # TerminalState
        r.read(2)
    elif type_code == 83:   # Unknown83
        r.u32()
    elif type_code == 84:   # CanTalkToPlayer
        r.u8()
    elif type_code == 85:   # ObjectHealth
        r.f32()
    elif type_code == 88:   # ModelSwap
        r.refid_raw(); r.u32()
    elif type_code == 89:   # Radius
        r.f32()
    elif type_code == 91:   # FactionChanges
        def _faction_change(rr):
            rr.refid_raw(); rr.u8()
        _read_vs_elem_array(r, _faction_change)
        r.refid_raw(); r.u8()
    elif type_code == 92:   # DismemberedLimbs
        r.u16(); r.u32(); r.u32(); r.u8(); r.refid_raw()

        def _limb(rr):
            rr.read(4)
            _read_vs_elem_array(rr, lambda rrr: rrr.refid_raw())
        _read_vs_elem_array(r, _limb)
    elif type_code == 93:   # ActorCause
        r.u32()
    elif type_code == 101:  # CombatStyle
        r.refid_raw()
    elif type_code == 102:  # MYSTERIOUS
        r.refid_raw(); r.refid_raw()
    elif type_code == 104:  # OpenCloseActivateRef
        r.refid_raw()
    elif type_code == 106:  # Ammo
        r.refid_raw(); r.u32()
    elif type_code == 111:  # SayTopicInfoOnceADay
        def _say(rr):
            rr.refid_raw(); rr.u32(); rr.u32()
        _read_vs_elem_array(r, _say)
    elif type_code == 112:  # EncounterZone
        r.refid_raw()
    elif type_code == 113:  # SayToTopicInfo
        r.refid_raw(); r.u8(); r.u32(); r.refid_raw()
        # SayToTopicInfoData2:
        r.wstring_raw(); r.wstring_raw(); r.u32(); r.u32(); r.u8()
        r.refid_raw(); r.refid_raw(); r.refid_raw(); r.u8()
    elif type_code == 120:  # GuardedRefData
        def _guard(rr):
            rr.refid_raw(); rr.u32(); rr.u8()
        _read_vs_elem_array(r, _guard)
    elif type_code == 133:  # AshPileRef
        r.refid_raw()
    elif type_code == 135:  # TEST
        r.refid_raw(); r.refid_raw(); r.refid_raw(); r.refid_raw()
    elif type_code == 136:  # AliasInstanceArray
        def _alias(rr):
            rr.refid_raw(); rr.u32()
        _read_vs_elem_array(r, _alias)
    elif type_code == 140:  # PromotedRef
        _read_vs_elem_array(r, lambda rr: rr.refid_raw())
    elif type_code == 142:  # OutfitItem
        r.refid_raw()
    elif type_code == 146:  # SceneData
        r.refid_raw()
    elif type_code == 149:  # FromAlias
        r.refid_raw(); r.u32()
    elif type_code == 150:  # ShouldWear
        r.u8()
    elif type_code == 152:  # AttachedArrows3D
        def _arrow(rr):
            ref = rr.refid_raw()
            if ref != 0:
                u16 = rr.i16()
                if u16 != -1:
                    rr.u32(); rr.read(32)
        _read_vs_elem_array(r, _arrow)
        r.u16(); r.u16()
    elif type_code == 153:  # TextDisplayData
        ref1 = r.refid_raw(); ref2 = r.refid_raw()
        unk = r.i32()
        if ref1 == 0 and ref2 == 0 and unk == -2:
            r.wstring_raw()
    elif type_code == 155:  # Enchantment
        r.refid_raw(); r.u16()
    elif type_code == 156:  # Soul
        r.u8()
    elif type_code == 157:  # ForcedTarget
        r.refid_raw()
    elif type_code == 159:  # UniqueId
        r.u32(); r.u16()
    elif type_code == 160:  # Flags
        r.u32()
    elif type_code == 161:  # RefrPath
        r.read(4 * 18); r.read(4 * 4)
    elif type_code == 164:  # ForcedLandingMarker
        r.refid_raw()
    elif type_code == 169:  # Interaction
        r.u32(); r.refid_raw(); r.refid_raw(); r.u8()
    elif type_code == 174:  # GroupConstraint
        r.u32(); r.refid_raw(); r.wstring_raw(); r.wstring_raw()
        r.read(12); r.read(12); r.u32(); r.f32()
    elif type_code == 175:  # ScriptedAnimDependence
        def _sad(rr):
            rr.refid_raw(); rr.u32()
        _read_32_elem_array(r, _sad)
    elif type_code == 176:  # CachedScale
        r.f32(); r.f32()
    else:
        raise ParseAbort(f"Unknown ExtraData type={type_code} "
                          f"(no such case in ChangeFormExtraDataData.java)")

    return type_code, map_marker_value


def parse_location_marker_changeform(payload: bytes, change_flags: int, kind: str, log, refid_hex):
    """Parses the REFR ChangeForm of a map marker and determines the
    "discovered / not discovered on the map" status (Discovered).

    Returns a dict:
      {'status': 'DISCOVERED'|'NOT_DISCOVERED'|'NO_OVERRIDE'|'UNKNOWN',
       'raw_byte': int|None, 'reason': str|None}

    Based on the FULLY confirmed structure (ChangeFormRefr.java +
    ChangeFormInitialData.java + ChangeFormFlags.java + ChangeFormExtraData
    .java + ChangeFormExtraDataData.java, all from the FallrimTools sources).
    The only thing confirmed on real saves (the meaning of the byte, not the
    structure) - on 3 independent real locations: the ExtraData element of
    type 44 ("MapMarker") carries the map visibility byte, where bit 0 of
    that byte = Visible (same meaning as FNAM in the .esm: 0x01=Visible,
    0x02=CanTravelTo; the observed value 0x03 = both bits = "discovered").
    """
    def has_bit(n):
        return (change_flags >> n) & 1

    r = Reader(payload)

    try:
        # --- initialType, as in ChangeFormRefr.java (the order of checks matters!) ---
        if kind == 'CREATED':
            initial_type = 5
        elif has_bit(25) or has_bit(3):    # PROMOTED(0x02000000) | CELL_CHANGED(0x08)
            initial_type = 6
        elif has_bit(2) or has_bit(1):     # HAVOK_MOVE(0x04) | MOVE(0x02)
            initial_type = 4
        else:
            initial_type = 0

        # --- INITIAL (ChangeFormInitialData.java) ---
        if initial_type == 1:
            r.read(2); r.read(1); r.read(1); r.read(4)
        elif initial_type == 2:
            r.read(2); r.read(2); r.read(2); r.read(4)
        elif initial_type == 3:
            r.read(4)
        elif initial_type == 4:
            r.refid_raw(); r.read(12); r.read(12)
        elif initial_type == 5:
            r.refid_raw(); r.read(12); r.read(12); r.read(1); r.refid_raw()
        elif initial_type == 6:
            r.refid_raw(); r.read(12); r.read(12); r.refid_raw(); r.read(2); r.read(2)
        # initial_type == 0 -> nothing is read (the java switch has no case 0, default is empty)

        # --- HAVOK (bit 2, CHANGE_REFR_HAVOK_MOVE) ---
        if has_bit(2):
            _read_bytes_vs(r)

        # --- CHANGE_FORM_FLAGS (bit 0) -> ChangeFormFlags.java: Flags.Int(4)+short(2) ---
        if has_bit(0):
            r.read(4); r.read(2)

        # --- BASE_OBJECT (bit 7, 0x80) ---
        if has_bit(7):
            r.refid_raw()

        # --- SCALE (bit 4, 0x10) ---
        if has_bit(4):
            r.f32()

        # --- EXTRADATA ---
        # Confirmed triggers (see ChangeFormRefr.java, OR condition):
        # EXTRA_OWNERSHIP(bit6,0x40), EXTRA_ENCOUNTER_ZONE(bit29,0x20000000),
        # EXTRA_GAME_ONLY(bit31,0x80000000), PROMOTED(bit25,0x02000000),
        # EXTRA_ACTIVATING_CHILDREN(bit26,0x04000000). 4 more bit triggers
        # in the source (LOCK/AMMO/TELEPORT/ITEM_DATA) have bit numbers we
        # do not know - that does not matter: GAME_ONLY alone is a confirmed
        # and sufficient trigger (OR condition), with it the game always
        # reads EXTRADATA regardless of the others.
        game_only = bool(has_bit(31))

        if not game_only:
            return {'status': 'NO_OVERRIDE', 'raw_byte': None,
                    'reason': 'CHANGE_REFR_EXTRA_GAME_ONLY (bit 31) is not set - '
                              'no override in the save, the status comes from the '
                              'plugin base value (ExportMapMarkers.csv, AlwaysVisible)'}

        count = r.vsval()
        if count < 0 or count > 1024:
            raise ParseAbort(f"Invalid EXTRA_DATA_COUNT={count}")

        map_marker_value = None
        found = False
        for _ in range(count):
            type_code, mm_val = parse_extra_data_element(r)
            if type_code == 44:
                map_marker_value = mm_val
                found = True

        if not found:
            return {'status': 'UNKNOWN', 'raw_byte': None,
                    'reason': f'GAME_ONLY is set, EXTRADATA parsed ({count} '
                              f'element(s)), but there is no type 44 (MapMarker) '
                              f'element among them'}

        status = 'DISCOVERED' if (map_marker_value & 0x01) else 'NOT_DISCOVERED'
        return {'status': status, 'raw_byte': map_marker_value, 'reason': None}

    except ParseAbort as e:
        log(f"  [unknown] refid={refid_hex}: {e}")
        return {'status': 'UNKNOWN', 'raw_byte': None, 'reason': str(e)}
    except EOFError as e:
        log(f"  [unknown] refid={refid_hex}: ran out of data while parsing REFR ({e})")
        return {'status': 'UNKNOWN', 'raw_byte': None, 'reason': f'EOF: {e}'}


kMinActorSpells = 32
kMaxActorSpells = 2048


def _read_spell_array_raw(block: bytes, at: int):
    """One attempt to read "u32 count + count distinct 3-byte refids" at an
    arbitrary place block[at:]. Returns the list of raw 24-bit refids, or
    None if at this offset it does not look like a spell list (the
    kMinActorSpells/kMaxActorSpells limits and the ban on duplicate/empty
    refids - see find_actor_spells_raw)."""
    if len(block) - at < 4:
        return None
    count = struct.unpack_from('<I', block, at)[0]
    if count < kMinActorSpells or count > kMaxActorSpells:
        return None
    at += 4
    if (len(block) - at) // 3 < count:
        return None
    found = []
    seen = set()
    for _ in range(count):
        b0, b1, b2 = block[at], block[at + 1], block[at + 2]
        raw = (b0 << 16) | (b1 << 8) | b2
        val_part = raw & 0x3FFFFF
        type_idx = (raw >> 22) & 0x3
        if val_part == 0 or type_idx == 3:  # "none" refid / UNUSED type
            return None
        key = (type_idx, val_part)
        if key in seen:
            return None
        seen.add(key)
        found.append(raw)
        at += 3
    return found


def find_actor_spells_raw(block: bytes):
    """Spells added to an actor during play live in the UNPARSED "tail" of
    the ACHR record (the same piece FallrimTools/UESP do not parse at all -
    see the parse_achr_actor_spells docstring). The exact offset inside that
    tail cannot be computed (a variable-length AI process state lives there
    too), so a byte-by-byte search for a characteristic "shape" is used:
    a u32 counter + that many distinct refids. If at least two different
    offsets give a valid read at once, the result is dropped (that
    ambiguity means the match is accidental and the real list was not
    found) - we do not try to guess which one is right.

    1:1 port of FindActorSpells() from Force67/recreation
    (components/bethesda/savegame_changeform.cc),
    byte-accurate, verified by their own test on a real 100% save (161
    spells, all resolving to real SPEL records) and additionally on two real
    saves of this project (164/167 of spells_tracker.csv matched on the
    second)."""
    out = []
    ambiguous = False
    n = len(block)
    i = 0
    while i + 4 <= n:
        spells = _read_spell_array_raw(block, i)
        if spells is None:
            i += 1
            continue
        if out:
            ambiguous = True
            break
        out = spells
        i += 1
    if ambiguous:
        return []
    return out


ACHR_ACTOR_EXTRA_DATA_BITS = (6, 9, 11, 17, 18, 25, 26, 29, 30, 31)
# ACHR-specific EXTRADATA triggers (unlike the REFR set above):
# ownership(6), package data(9), merchant container(11), dismembered
# limbs(17), levelled actor(18), promoted(25), activating children(26),
# encounter zone(29), created-only extras(30), game-only extras(31).
# 1:1 from kAchrExtraDataFlags in savegame_changeform.h (Force67/recreation).


def _decode_inventory_skip(r: Reader):
    """Inventory of an actor/container: vsval count of stacks, each - refid(3)
    + count(i32) + vsval count of extra-data lists, each list read with the
    already verified parse_extra_data_element() (the same one used for the
    REFR location markers). The content is not kept - only the cursor moves,
    to land exactly at the start of the actor block of the ACHR record."""
    count = r.vsval()
    if count < 0 or count > 200000:
        raise ParseAbort(f"Invalid INVENTORY_COUNT={count}")
    for _ in range(count):
        r.refid_raw()
        r.i32()
        lists = r.vsval()
        if lists < 0 or lists > 4096:
            raise ParseAbort(f"Invalid INVENTORY_EXTRA_LISTS={lists}")
        for _ in range(lists):
            inner_count = r.vsval()
            if inner_count < 0 or inner_count > 4096:
                raise ParseAbort(f"Invalid EXTRA_DATA_COUNT (inventory)={inner_count}")
            for _ in range(inner_count):
                parse_extra_data_element(r)


def parse_achr_actor_spells(payload: bytes, change_flags: int, kind: str, log, refid_hex):
    """Parses the ACHR ChangeForm of an actor (used for the player only,
    RefID 0x14) and looks for the list of actually learned spells.

    The transform/havok/form_flags/base_object/scale/extradata groups are
    walked in THE SAME order and with the same bits as in
    parse_location_marker_changeform() above (confirmed from
    ChangeFormRefr.java) - the only differences: (a) an actor has 8 bytes
    after the transform group with no flag at all (unrelated to REFR), and
    (b) the set of EXTRADATA trigger bits of ACHR differs from REFR (see
    ACHR_ACTOR_EXTRA_DATA_BITS). After extradata the INVENTORY must also be
    walked (parse_location_marker_changeform stopped before it because map
    markers do not need it) - otherwise the cursor does not reach the end of
    the REFR-specific data and the tail scanned by find_actor_spells_raw
    starts at the wrong position.

    The tail itself (AI process state + actor stat tables + perks + spells)
    is NOT documented anywhere (neither in the FallrimTools sources nor on
    UESP - it honestly says "Todo: Parse rest of ACHR form") - it is found by
    find_actor_spells_raw() with a byte-by-byte search, a port from
    Force67/recreation, see its docstring.

    Returns a dict: {'spells': [raw_refid,...], 'status': 'OK'|
    'TRUNCATED'|'UNKNOWN', 'decoded_bytes': int, 'reason': str|None}.
    """
    def has_bit(n):
        return (change_flags >> n) & 1

    r = Reader(payload)
    try:
        if kind == 'CREATED':
            initial_type = 5
        elif has_bit(25) or has_bit(3):
            initial_type = 6
        elif has_bit(2) or has_bit(1):
            initial_type = 4
        else:
            initial_type = 0

        if initial_type == 4:
            r.refid_raw(); r.read(12); r.read(12)
        elif initial_type == 5:
            r.refid_raw(); r.read(12); r.read(12); r.read(1); r.refid_raw()
        elif initial_type == 6:
            r.refid_raw(); r.read(12); r.read(12); r.refid_raw(); r.read(2); r.read(2)

        if has_bit(2):
            _read_bytes_vs(r)

        # ACHR-only: 8 bytes not tied to any flag.
        r.read(8)

        if has_bit(0):
            r.read(4); r.read(2)
        if has_bit(7):
            r.refid_raw()
        if has_bit(4):
            r.f32()

        if any(has_bit(bit) for bit in ACHR_ACTOR_EXTRA_DATA_BITS):
            count = r.vsval()
            if count < 0 or count > 4096:
                raise ParseAbort(f"Invalid EXTRA_DATA_COUNT={count}")
            for _ in range(count):
                parse_extra_data_element(r)

        if has_bit(5) or has_bit(27):  # INVENTORY | LEVELED_INVENTORY
            _decode_inventory_skip(r)

        if has_bit(28):  # ANIMATION
            _read_bytes_vs(r)

        rest = r.data[r.pos:]
        spells = find_actor_spells_raw(rest)
        return {'spells': spells, 'status': 'OK', 'decoded_bytes': r.pos, 'reason': None}

    except ParseAbort as e:
        log(f"  [unknown] refid={refid_hex}: {e}")
        return {'spells': [], 'status': 'UNKNOWN', 'decoded_bytes': r.pos, 'reason': str(e)}
    except EOFError as e:
        log(f"  [unknown] refid={refid_hex}: ran out of data while parsing ACHR ({e})")
        return {'spells': [], 'status': 'TRUNCATED', 'decoded_bytes': r.pos, 'reason': f'EOF: {e}'}


def parse_npc_base_spells(payload: bytes, change_flags: int, log, refid_hex):
    """Parses the NPC_ ChangeForm of the player's base record (FormID 0x07)
    and takes its OWN (small) spell/shout list - these are the character's
    starting spells (for example Flames/Healing of a freshly created Breton),
    which NEVER show up in the find_actor_spells_raw() search over the ACHR
    tail (see DecodeActorBase() in Force67/recreation: "the player's real
    spell book" - that is the ACHR search,
    "the NPC_ change form's spell list only holds the handful the game
    hands out early").

    The groups (FormFlags, Stats/ACBS, Factions, Spells, ...) come strictly
    in this order (1:1 from DecodeActorBase(), savegame_changeform.cc) -
    parsing stops right after the Spells group, nothing further is needed.

    Returns a dict: {'spells': [...], 'levelled_spells': [...],
    'shouts': [...], 'status': 'OK'|'UNKNOWN'} (the lists are raw 24-bit
    refids; shouts is not used for Spells, kept for the Shouts
    category)."""
    def has_bit(n):
        return (change_flags >> n) & 1

    r = Reader(payload)
    try:
        if has_bit(0):  # kActorBaseChangeFormFlags
            r.read(6)
        if has_bit(1):  # kActorBaseChangeStats (ACBS)
            r.u32()
            for _ in range(8):
                r.u16()
            r.i16()
            r.u16()
        if has_bit(6):  # kActorBaseChangeFactions (SNAM)
            count = r.vsval()
            if count < 0 or count > 4096:
                raise ParseAbort(f"Invalid FACTIONS_COUNT={count}")
            for _ in range(count):
                r.refid_raw(); r.i8()
        if has_bit(4):  # kActorBaseChangeSpells
            lists = {'spells': [], 'levelled_spells': [], 'shouts': []}
            for key in ('spells', 'levelled_spells', 'shouts'):
                count = r.vsval()
                if count < 0 or count > 4096:
                    raise ParseAbort(f"Invalid SPELLLIST_COUNT={count} ({key})")
                for _ in range(count):
                    lists[key].append(r.refid_raw())
            return {'status': 'OK', **lists}
        return {'status': 'OK', 'spells': [], 'levelled_spells': [], 'shouts': []}
    except (ParseAbort, EOFError) as e:
        log(f"  [unknown] refid={refid_hex}: {e}")
        return {'status': 'UNKNOWN', 'spells': [], 'levelled_spells': [], 'shouts': []}


# ---------------------------------------------------------------------------
# PERKS: the perk block in the player ACHR (0x14).
# The format was decoded byte by byte on the real save1/save2 of this project
# (diagnose_perks.py + dump save1.player_achr.bin), not taken from sources:
#   A: vsval n + n * (refid 3 bytes + u8)   <- LEARNED perks (full list)
#   B: vsval m + m * refid 3 bytes          <- subset of A
#   C: vsval k + k * (refid 3 bytes + u32)  <- subset of A (looks like perks
#      given by scripts: Sinderion, Ancient Knowledge, MQGreybeardsFus,
#      USKPMS05GiftofGab - NOT confirmed, not used anywhere)
# Meaning of A confirmed: resetting Illusion/Alchemy/One-Handed on save2 removed
# exactly 47 perks from A, leaving exactly the 2 bought again (IllusionNovice00,
# Alchemist00). The u8 in A = 1 in all 585 records of both saves, its meaning
# is not confirmed -> not used. The block offset inside ACHR moves (141877 on
# save1, 128729 on save2), so it is found by SHAPE, like find_actor_spells_raw:
# A without duplicates + non-empty B entirely from A + C entirely from A. On
# save1 without the "B not empty" condition there were 28 false matches (all
# with an empty B), with it - exactly one. 0 or >1 matches -> the whole block
# is UNKNOWN, no guessing.
# Vampire/werewolf perks live in the same A and are not removed after a cure
# (confirmed in game: a cured character still has both trees in A).
# ---------------------------------------------------------------------------

PERK_BLOCK_MIN_A = 10
PERK_BLOCK_MAX_A = 4096


def _vsval_at(d: bytes, p: int):
    """Same as Reader.vsval(), but without exceptions - for the byte-by-byte search."""
    if p >= len(d):
        return None, p
    b0 = d[p]
    size = b0 & 0x3
    need = 1 if size == 0 else 2 if size == 1 else 3
    if p + need > len(d):
        return None, p
    if size == 0:
        raw = b0
    elif size == 1:
        raw = b0 | (d[p + 1] << 8)
    else:
        raw = b0 | (d[p + 1] << 8) | (d[p + 2] << 16)
    return raw >> 2, p + need


def _refid_ok(raw):
    return (raw & 0x3FFFFF) != 0 and ((raw >> 22) & 0x3) != 3


def _read_perk_block(d: bytes, at: int):
    n, p = _vsval_at(d, at)
    if n is None or not (PERK_BLOCK_MIN_A <= n <= PERK_BLOCK_MAX_A) or p + 4 * n > len(d):
        return None
    a_list, seen = [], set()
    for _ in range(n):
        raw = (d[p] << 16) | (d[p + 1] << 8) | d[p + 2]
        if not _refid_ok(raw) or raw in seen:
            return None
        seen.add(raw)
        a_list.append(raw)
        p += 4
    m, p = _vsval_at(d, p)
    if m is None or m < 1 or m > n or p + 3 * m > len(d):
        return None
    b_list = []
    for _ in range(m):
        raw = (d[p] << 16) | (d[p + 1] << 8) | d[p + 2]
        if raw not in seen:
            return None
        b_list.append(raw)
        p += 3
    k, p = _vsval_at(d, p)
    if k is None or k > n or p + 7 * k > len(d):
        return None
    c_list = []
    for _ in range(k):
        raw = (d[p] << 16) | (d[p + 1] << 8) | d[p + 2]
        if raw not in seen:
            return None
        c_list.append(raw)
        p += 7
    return {'offset': at, 'end': p, 'A': a_list, 'B': b_list, 'C': c_list}


def find_perk_block(payload: bytes):
    """Returns the list of ALL shape matches; the caller must accept the
    result only when there is exactly one match."""
    hits = []
    for i in range(len(payload)):
        r = _read_perk_block(payload, i)
        if r is not None:
            hits.append(r)
    return hits



# ======================================================================
# COLLECTIBLES (masks, claws, bugs in jars, Kagrumez gems, paragons)
# ----------------------------------------------------------------------
# An item counts if it is in at least one home from
# collectibles_houses.csv (8 homes: cell + containers + mannequins).
# All four ways were confirmed on real saves (save1/save2/save5):
#   1. a created reference (FF RefID) with the item as its base, cell from
#      INITIAL (type 5) = the home cell - this is how displays place items;
#   2. the original persistent object from the plugin (PersistentRefs column
#      of the tracker - quest claws, Wooden Mask): cell from INITIAL
#      (type 4/6) = the home, AND the object is really in the world. When such
#      an object goes into a container/inventory, the cell in the record
#      STAYS THE OLD ONE, but Form Flags get 0x20 (Deleted) and ExtraData gets
#      an element of type 0x1C - with either sign the object does NOT count by
#      its cell;
#   3. the inventory of a home container (the count in the record is a delta
#      to the plugin content; plugin containers hold no tracker items);
#   4. the inventory of a home mannequin (ACHR) - the same parsing as the player.
# The player inventory does NOT count.
# Row modes: ANY - any of the bases; ALL - all bases (items whose halves may
# lie in different homes); COUNT - the sum of counts over all homes
# >= Required (Kagrumez gems: 5 of one record Inv01).
# If some home container/mannequin could not be parsed, rows that were not
# found get UNKNOWN, not NOT OBTAINED.
# ======================================================================

# REFR change_flags bits that mean an EXTRADATA block is present
# (ChangeFormRefr.java): OWNERSHIP 6, ITEM_DATA 10, AMMO 11, LOCK 12,
# TELEPORT 17, PROMOTED 25, ACTIVATING_CHILDREN 26, ENCOUNTER_ZONE 29,
# GAME_ONLY 31. Variant B adds CREATED_ONLY 30 - tried when A does not parse
# (on save1/save2/save5 every home parsed with variant A/B without a single
# failure).
COLL_REFR_EXTRA_BITS_A = (6, 10, 11, 12, 17, 25, 26, 29, 31)
COLL_REFR_EXTRA_BITS_B = COLL_REFR_EXTRA_BITS_A + (30,)
COLL_FORM_FLAG_DELETED = 0x20
COLL_EXTRA_NOT_IN_WORLD = 0x1C


def coll_read_initial(r, change_flags, kind):
    """INITIAL (ChangeFormInitialData.java). -> (initial_type, cell_raw, base_raw)."""
    def bit(n):
        return (change_flags >> n) & 1
    if kind == 'CREATED':
        it = 5
    elif bit(25) or bit(3):
        it = 6
    elif bit(2) or bit(1):
        it = 4
    else:
        it = 0
    cell = base = None
    if it == 4:
        cell = r.refid_raw(); r.read(12); r.read(12)
    elif it == 5:
        cell = r.refid_raw(); r.read(12); r.read(12); r.read(1); base = r.refid_raw()
    elif it == 6:
        cell = r.refid_raw(); r.read(12); r.read(12); r.refid_raw(); r.read(2); r.read(2)
    return it, cell, base


def coll_read_inventory(r):
    """Like _decode_inventory_skip(), but returns the stacks [(item_raw, count)]."""
    stacks = []
    count = r.vsval()
    if count < 0 or count > 200000:
        raise ParseAbort(f"INVENTORY_COUNT={count}")
    for _ in range(count):
        item = r.refid_raw()
        n = r.i32()
        stacks.append((item, n))
        lists = r.vsval()
        if lists < 0 or lists > 4096:
            raise ParseAbort(f"INVENTORY_EXTRA_LISTS={lists}")
        for _ in range(lists):
            inner = r.vsval()
            if inner < 0 or inner > 4096:
                raise ParseAbort(f"EXTRA_DATA_COUNT (inventory)={inner}")
            for _ in range(inner):
                parse_extra_data_element(r)
    return stacks


def coll_parse_refr(payload, change_flags, kind, extra_bits):
    """REFR: INITIAL, HAVOK, FORM_FLAGS, BASEOBJECT, SCALE, EXTRADATA, INVENTORY.
    -> dict(it, cell, base, form_flags, extra_types, stacks)."""
    def bit(n):
        return (change_flags >> n) & 1
    r = Reader(payload)
    it, cell, base = coll_read_initial(r, change_flags, kind)
    if bit(2):
        _read_bytes_vs(r)
    form_flags = None
    if bit(0):
        form_flags = r.u32(); r.read(2)
    if bit(7):
        base = r.refid_raw()
    if bit(4):
        r.f32()
    extra_types = []
    if any(bit(b) for b in extra_bits):
        c = r.vsval()
        if c < 0 or c > 4096:
            raise ParseAbort(f"EXTRA_DATA_COUNT={c}")
        for _ in range(c):
            extra_types.append(payload[r.pos])
            parse_extra_data_element(r)
    stacks = []
    if bit(5) or bit(27):
        stacks = coll_read_inventory(r)
    return {'it': it, 'cell': cell, 'base': base, 'form_flags': form_flags,
            'extra_types': extra_types, 'stacks': stacks}


def coll_parse_achr_inventory(payload, change_flags, kind):
    """ACHR (mannequin): the same path as parse_achr_actor_spells() up to the inventory."""
    def bit(n):
        return (change_flags >> n) & 1
    r = Reader(payload)
    coll_read_initial(r, change_flags, kind)
    if bit(2):
        _read_bytes_vs(r)
    r.read(8)
    if bit(0):
        r.read(4); r.read(2)
    if bit(7):
        r.refid_raw()
    if bit(4):
        r.f32()
    if any(bit(b) for b in ACHR_ACTOR_EXTRA_DATA_BITS):
        c = r.vsval()
        if c < 0 or c > 4096:
            raise ParseAbort(f"EXTRA_DATA_COUNT={c}")
        for _ in range(c):
            parse_extra_data_element(r)
    if bit(5) or bit(27):
        return coll_read_inventory(r)
    return []


def _coll_key(s):
    p, l = s.split(':')
    return (p.strip().lower(), int(l.strip(), 16))


def load_collectibles_tracker(path):
    """collectibles_tracker.csv: ';' delimited, Order;Block;Name;Tags;Mode;
    Required;BaseKeys;BaseEditorIDs;PersistentRefs - 40 rows in HTML order.
    BaseKeys/PersistentRefs - 'Plugin:LocalID' lists separated by '|';
    the first BaseKey is the HTML row key (data-item)."""
    rows = []
    with _open_text(path) as fh:
        for r in csv.DictReader(fh, delimiter=';'):
            r['_bases'] = [_coll_key(x) for x in r['BaseKeys'].split('|') if x.strip()]
            r['_prefs'] = [_coll_key(x) for x in r['PersistentRefs'].split('|') if x.strip()]
            rows.append(r)
    return rows


def load_collectibles_houses(path):
    """collectibles_houses.csv: Kind(CELL/CONTAINER/MANNEQUIN);House;Plugin;
    LocalID;EditorID;Name. -> (cells{key: house}, holders{key: (kind, house, eid)})."""
    cells, holders = {}, {}
    with _open_text(path) as fh:
        for r in csv.DictReader(fh, delimiter=';'):
            k = (r['Plugin'].strip().lower(), int(r['LocalID'].strip(), 16))
            if r['Kind'] == 'CELL':
                cells[k] = r['House']
            else:
                holders[k] = (r['Kind'], r['House'], r['EditorID'])
    return cells, holders


def stored_items_scan(coll_tracker_rows, coll_cells, coll_holders, location_forms,
                      achr_forms, cres):
    """Search for tracker items in the homes (4 ways, see the comment at
    coll_read_initial). Shared by Collectibles and Books - the code was moved
    from the COLLECTIBLES section of main() without any change in logic.
    -> (coll_found{base_key: [(house, how, n)]}, coll_unknown, coll_ignored,
        holders_seen)."""
    base_keys = set()
    pref_to_base = {}
    for row in coll_tracker_rows:
        base_keys.update(row['_bases'])
        for pk in row['_prefs']:
            pref_to_base[pk] = row['_bases'][0]

    coll_found = {}      # base_key -> [(house, how, count)]
    coll_unknown = []
    coll_ignored = []
    holders_seen = set()

    def add_hit(bk, house, how, n):
        coll_found.setdefault(bk, []).append((house, how, n))

    def payload_of(data, length2):
        return zlib.decompress(data) if length2 > 0 else data

    # REFR: created references, persistent objects, containers
    for refid, change_flags, version, length1, length2, data in location_forms:
        p_, l_, k_ = cres(refid)
        rk = (p_, l_)
        is_holder = rk in coll_holders and coll_holders[rk][0] == 'CONTAINER'
        is_pref = rk in pref_to_base
        if not (is_holder or is_pref or k_ == 'CREATED'):
            continue
        try:
            payload = payload_of(data, length2)
        except zlib.error as e:
            if is_holder or is_pref:
                coll_unknown.append(f"{p_}:{l_:06X}: zlib ({e})")
            continue
        parsed = None
        err = ''
        for bits in (COLL_REFR_EXTRA_BITS_A, COLL_REFR_EXTRA_BITS_B):
            try:
                parsed = coll_parse_refr(payload, change_flags, k_, bits)
                break
            except (ParseAbort, EOFError) as e:
                err = str(e)
        if parsed is None:
            if is_holder or is_pref:
                what = coll_holders[rk][1] + ' ' + coll_holders[rk][2] if is_holder else 'persistent'
                coll_unknown.append(f"{what} {p_}:{l_:06X}: {err}")
                continue
            if k_ != 'CREATED':
                continue
            try:   # INITIAL is enough for a created reference
                it, cell, base = coll_read_initial(Reader(payload), change_flags, k_)
                parsed = {'it': it, 'cell': cell, 'base': base, 'form_flags': None,
                          'extra_types': [], 'stacks': []}
            except EOFError:
                continue
        cell = parsed['cell']
        house = coll_cells.get(cres(cell)[:2]) if cell is not None else None

        if k_ == 'CREATED' and house and parsed['base'] is not None:
            bk = cres(parsed['base'])[:2]
            if bk in base_keys:
                add_hit(bk, house, f"in the world {p_}:{l_:06X}", 1)
        if is_pref and house:
            ff = parsed['form_flags']
            gone = (ff is not None and ff & COLL_FORM_FLAG_DELETED) \
                or COLL_EXTRA_NOT_IN_WORLD in parsed['extra_types']
            if gone:
                coll_ignored.append(
                    f"{p_}:{l_:06X} (cell {house}): form_flags=0x{ff or 0:08X}, "
                    f"extra={[hex(x) for x in parsed['extra_types']]}")
            else:
                add_hit(pref_to_base[rk], house, f"persistent {p_}:{l_:06X}", 1)
        if is_holder:
            holders_seen.add(rk)
            _, hh, eid = coll_holders[rk]
            for srid, n in parsed['stacks']:
                sk = cres(srid)[:2]
                if sk in base_keys and n > 0:
                    add_hit(sk, hh, f"{eid} {p_}:{l_:06X}", n)

    # ACHR: mannequins
    for refid, change_flags, data, length2 in achr_forms:
        p_, l_, k_ = cres(refid)
        rk = (p_, l_)
        if rk not in coll_holders or coll_holders[rk][0] != 'MANNEQUIN':
            continue
        holders_seen.add(rk)
        _, hh, eid = coll_holders[rk]
        try:
            stacks = coll_parse_achr_inventory(payload_of(data, length2), change_flags, k_)
        except (ParseAbort, EOFError, zlib.error) as e:
            coll_unknown.append(f"{hh} {eid} {p_}:{l_:06X}: {e}")
            continue
        for srid, n in stacks:
            sk = cres(srid)[:2]
            if sk in base_keys and n > 0:
                add_hit(sk, hh, f"mannequin {p_}:{l_:06X}", n)

    return coll_found, coll_unknown, coll_ignored, holders_seen


def load_perks_tracker(path):
    """perks_tracker.csv: ';' delimited, Order;Block;SubBlock;Name;Tags;Plugin;
    LocalID;EditorID;Source - 282 rows in HTML order. Source = PERK or SPEL
    (Prowler's Profit is an ability). Optional = 'Optional' among Tags."""
    with _open_text(path) as fh:
        return list(csv.DictReader(fh, delimiter=';'))


def load_spells_tracker(path):
    """Reads spells_tracker.csv: ';' delimited, Order;Block;Name;Tags;Plugin;
    LocalID;EditorID, rows in HTML order, Name exactly as in the HTML,
    Tags = HTML chips separated by '|'. Key for the save = (Plugin, LocalID)."""
    rows = []
    with _open_text(path) as fh:
        reader = csv.DictReader(fh, delimiter=';')
        for row in reader:
            rows.append(row)
    return rows


def load_shouts_tracker(path):
    """Reads shouts_tracker.csv: ';' delimited, Order;Block;Name;Tags;Plugin;
    LocalID;EditorID - 81 rows, one per word of power (WOOP record), in HTML
    order; Block = shout name, Name = the dragon word exactly as in the HTML."""
    rows = []
    with _open_text(path) as fh:
        reader = csv.DictReader(fh, delimiter=';')
        for row in reader:
            rows.append(row)
    return rows


def load_enchanting_tracker(path):
    """Reads enchanting_tracker.csv: ';' delimited, Order;Block;Name;Tags;Plugin;
    LocalID;EditorID - 58 rows, one per effect, in HTML order. Key for the save
    = (Plugin, LocalID) of the base enchantment; LocalID is already local (12 bit
    for ESL) - a full FormID is never used, for ESL it depends on load order."""
    rows = []
    with _open_text(path) as fh:
        reader = csv.DictReader(fh, delimiter=';')
        for row in reader:
            rows.append(row)
    return rows


def load_ingredients_tracker(path):
    """Reads ingredients_tracker.csv: ';' delimited, Order;Block;Name;Tags;Plugin;
    LocalID;EditorID;AltCandidates - 184 rows in HTML order. Key for the save =
    (Plugin, LocalID). AltCandidates = other records of the same ingredient,
    'Plugin:LocalID=EditorID|...' - only logged, never counted."""
    with _open_text(path) as fh:
        return list(csv.DictReader(fh, delimiter=';'))


def load_marker_filter(path):
    """Reads MapMarkerExport.csv (from ExportMapMarkers_v2.pas) and returns
    a set of (plugin, local_form_id_int) - only these REFRs are parsed as
    map markers."""
    result = set()
    with _open_text(path) as fh:
        reader = csv.DictReader(fh, delimiter=';')
        for row in reader:
            formid_hex = row.get('FormID', '').strip()
            plugin = row.get('Plugin', '').strip()
            if not formid_hex or not plugin:
                continue
            try:
                local_id = int(formid_hex, 16) & 0xFFFFFF
            except ValueError:
                continue
            result.add((plugin, local_id))
    return result


def load_location_tracker(path):
    """Reads locations_tracker.csv (build_locations_tracker.py):
    ';' delimited, Order;Block;Name;Tags;MarkerFormIDs, rows in HTML order,
    Name exactly as in the HTML. MarkerFormIDs - one or more "Plugin:FormID"
    separated by '|' (several markers = discovered if ANY of them is).

    Returns a list of dicts:
      {'order': str, 'block': str, 'name': str, 'tags': str,
       'markers': [(plugin, local_id_int), ...]}
    A row without a valid marker is an error, not a silent skip.
    """
    locations = []
    with _open_text(path) as fh:
        for row in csv.DictReader(fh, delimiter=';'):
            markers = []
            for entry in row['MarkerFormIDs'].split('|'):
                entry = entry.strip()
                if ':' not in entry:
                    continue
                plugin, formid_hex = entry.split(':', 1)
                markers.append((plugin.strip(), int(formid_hex.strip(), 16) & 0xFFFFFF))
            if not markers:
                raise ValueError(f"{path}: row {row['Order']} ({row['Name']}) has no MarkerFormIDs")
            locations.append({
                'order': row['Order'].strip(), 'block': row['Block'].strip(),
                'name': row['Name'].strip(), 'tags': row['Tags'].strip(),
                'markers': markers,
            })
    return locations


def load_always_visible(path):
    """Reads MapMarkerExport.csv (ExportMapMarkers_v2.pas) and returns
    dict {(plugin, local_id_int): always_visible_bool_or_None}.
    AlwaysVisible column - '1' if the marker in the plugin itself (not in the
    save) has the FNAM Visible flag (the marker is on the map from the very
    start of the game, like the big cities), otherwise empty/'0'. None if the
    marker is not in this export at all (then the status cannot be known,
    honestly UNKNOWN)."""
    result = {}
    # errors='replace': some records (in particular those added by USSEP) in
    # this export have broken non-UTF8 bytes in text fields (MarkerName etc.,
    # xEdit sometimes mixes up the encoding). These fields are not needed -
    # only FormID/Plugin/AlwaysVisible matter, and they are always plain
    # ASCII, so replacing unreadable bytes does not affect them.
    with _open_text(path, errors='replace') as fh:
        reader = csv.DictReader(fh, delimiter=';')
        for row in reader:
            formid_hex = row.get('FormID', '').strip()
            plugin = row.get('Plugin', '').strip()
            if not formid_hex or not plugin:
                continue
            try:
                local_id = int(formid_hex, 16) & 0xFFFFFF
            except ValueError:
                continue
            always_visible_raw = row.get('AlwaysVisible', '').strip()
            always_visible = always_visible_raw == '1'
            # Do not overwrite True with False when the same (plugin,
            # local_id) appears again (for example overridden by another
            # plugin/patch) - it is enough that AlwaysVisible=1 is found in
            # at least one of the records.
            if (plugin, local_id) in result and result[(plugin, local_id)]:
                continue
            result[(plugin, local_id)] = always_visible
    return result


# ===========================================================================
# PLUGINS: the save's plugin list for the CC content filter in the HTML
# ---------------------------------------------------------------------------
# Exactly what the save already read in PluginInfo (full_plugins +
# lite_plugins) - the plugins loaded in the game when it was saved. The HTML
# compares it (case-insensitive) with data-plugin of the rows and hides rows
# of CC plugins that are not in the list. The IsCC column is for the report
# only: a CC plugin = a name like ccXXXsse001-name.esl/.esm (or ccXXXsse001_name).
# ===========================================================================
import re as _re
CC_PLUGIN_RE = _re.compile(r'^cc[a-z]+sse\d{3}[-_].+\.es[lm]$', _re.IGNORECASE)


# Where reports and *_final.csv go: next to the save (default), or into a temp
# folder with --json-only, so that run leaves only <save>.tracker.json behind.
OUT_BASE = None


def out_base(path):
    return OUT_BASE or os.path.splitext(path)[0]


TRACKER_JSON_FORMAT = 'skyrim-tracker/1'


def write_tracker_json(path, header, form_version, full_plugins, lite_plugins, finals):
    """<save>.tracker.json - everything the tracker page needs for one save, built
    from the *_final.csv files written in this run. Rows are addressed by Order
    (= row order in the HTML), so the page never matches names.

    finals: {category: csv_path or None}; a category without a CSV this run is
    left out and the page shows it as empty.
      quests/locations/spells/shouts/enchanting/perks/collectibles/books:
          {"done": [Order...], "unknown": [Order...]}
      quests also: {"failed": [Order...]} (QUEST_FLAGS 0x40)
      ingredients: {"known": {Order: "YYNY"}, "unknown": [...]}  (only rows with any Y)
      collectibles also: {"counts": {Order: have}} for COUNT rows (Kagrumez 5/5)
    """
    import json
    done_words = {'DONE (flag)', 'DONE (stage override)', 'DISCOVERED', 'LEARNED', 'OBTAINED'}
    cats = {}
    for cat, csv_path in finals.items():
        if not csv_path or not os.path.exists(csv_path):
            continue
        with open(csv_path, encoding='utf-8', newline='') as fh:
            rows = list(csv.DictReader(fh, delimiter=';'))
        entry = {'done': [], 'unknown': []}
        if cat == 'ingredients':
            entry = {'known': {}, 'unknown': []}
        for r in rows:
            order = int(r['Order'])
            st = r['Status'].strip()
            if st == 'UNKNOWN':
                entry['unknown'].append(order)
            if cat == 'ingredients':
                if 'Y' in r.get('Known', ''):
                    entry['known'][str(order)] = r['Known']
                continue
            if st in done_words:
                entry['done'].append(order)
            if cat == 'quests' and st == 'FAILED':
                entry.setdefault('failed', []).append(order)
            if cat == 'collectibles' and r.get('Progress'):
                entry.setdefault('counts', {})[str(order)] = int(r['Progress'].split('/')[0])
        cats[cat] = entry
    data = {
        'format': TRACKER_JSON_FORMAT,
        'save': {'file': os.path.basename(path), 'number': header['save_number'],
                 'version': header['version'], 'formVersion': form_version},
        'player': {'name': header['name'], 'level': header['level'],
                   'xp': round(header['cur_xp']), 'xpMax': round(header['needed_xp']),
                   'race': header['race_eid'], 'sex': header['sex'],
                   'location': header['location'], 'gameDate': header['game_date']},
        'plugins': {'full': list(full_plugins), 'light': list(lite_plugins)},
        'categories': cats,
    }
    out_path = JSON_PATH or (os.path.splitext(path)[0] + '.tracker.json')   # next to the save by default
    global LAST_RESULT
    LAST_RESULT = data
    with open(out_path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(',', ':'))
    return out_path


def write_plugins_final(path, full_plugins, lite_plugins):
    out_path = out_base(path) + '.plugins_final.csv'
    rows = []
    for i, p in enumerate(full_plugins):
        rows.append({'Type': 'full', 'Index': f"{i:02X}", 'Plugin': p,
                     'IsCC': int(bool(CC_PLUGIN_RE.match(p)))})
    for i, p in enumerate(lite_plugins):
        rows.append({'Type': 'light', 'Index': f"FE{i:03X}", 'Plugin': p,
                     'IsCC': int(bool(CC_PLUGIN_RE.match(p)))})
    with open(out_path, 'w', encoding='utf-8', newline='') as csvf:
        writer = csv.DictWriter(csvf, fieldnames=['Type', 'Index', 'Plugin', 'IsCC'],
                                delimiter=';')
        writer.writeheader()
        writer.writerows(rows)
    return out_path, sum(r['IsCC'] for r in rows)


# ===========================================================================
# MAIN
# ===========================================================================

def load_quest_tracker(path):
    """Reads quests_tracker.csv (';', UTF-8). Columns: Order;Tab;Section;
    Block;SubBlock;Name;EditorIDs;Key;NoCount;FormIDCandidates;OverrideMap;Category.
    Rows are in HTML order, Name - as in the HTML.
      Category         - flag | override | handle. handle = category 3, NPC
                         Requests and Untrackable: never looked up in the save,
                         marked done by hand on the page (status HANDLE)
      EditorIDs        - 'EDID|EDID2' (Dark Ancestor - two IDs)
      Key              - data-key of the row in the HTML (Civil War only:
                         CW03_imperial / CW03_stormcloak), otherwise empty
      FormIDCandidates - 'Plugin:FormID=SubEDID|...'
      OverrideMap      - 'SubEDID:Stage|...'
    A row without a single candidate is a file error, not a silent skip."""
    trackers = []
    with _open_text(path) as fh:
        reader = csv.DictReader(fh, delimiter=';')
        for row in reader:
            candidates = []
            for entry in row['FormIDCandidates'].split('|'):
                entry = entry.strip()
                if not entry:
                    continue
                left, sub_edid = entry.rsplit('=', 1)
                plugin, formid_hex = left.split(':', 1)
                local_id = int(formid_hex.strip(), 16) & 0xFFFFFF
                candidates.append((plugin.strip(), local_id, sub_edid.strip()))

            overrides = {}
            for entry in row['OverrideMap'].split('|'):
                entry = entry.strip()
                if not entry:
                    continue
                sub_edid, threshold = entry.rsplit(':', 1)
                overrides[sub_edid.strip()] = int(threshold.strip())

            category = (row.get('Category') or 'flag').strip().lower()
            if category == 'handle':
                candidates, overrides = [], {}
            elif not candidates:
                raise ValueError(f"{path}: row Order={row['Order']} "
                                 f"({row['Name']}) has no FormIDCandidates")

            trackers.append({
                'order': row['Order'], 'tab': row['Tab'], 'block': row['Block'],
                'subblock': row['SubBlock'], 'name': row['Name'],
                'editor_ids': row['EditorIDs'], 'key': row['Key'],
                'candidates': candidates, 'overrides': overrides,
                'handle': category == 'handle',
            })
    return trackers


def main(path, tracker_path=None, always_visible_path=None, quest_tracker_path=None,
         spells_tracker_path=None, shouts_tracker_path=None,
         enchanting_tracker_path=None, ingredients_tracker_path=None,
         perks_tracker_path=None, collectibles_tracker_path=None,
         collectibles_houses_path=None, books_tracker_path=None):
    quests_out_path = out_base(path) + '.quests_report.txt'
    locations_out_path = out_base(path) + '.locations_report.txt'
    quest_lines = []
    location_lines = []

    def qlog(msg):
        quest_lines.append(msg)

    def llog(msg):
        location_lines.append(msg)

    quest_tracker = []
    quest_marker_filter = None
    if quest_tracker_path:
        quest_tracker = load_quest_tracker(quest_tracker_path)
        quest_marker_filter = set()
        for qt in quest_tracker:
            for plugin, local_id, sub_edid in qt['candidates']:
                quest_marker_filter.add((plugin, local_id))
        qlog(f"Quest table loaded from {quest_tracker_path}: {len(quest_tracker)} quests, "
             f"{len(quest_marker_filter)} unique (plugin, FormID) candidates")

    tracker = []
    marker_filter = None
    always_visible = {}
    if tracker_path:
        tracker = load_location_tracker(tracker_path)
        marker_filter = set()
        for loc in tracker:
            marker_filter.update(loc['markers'])
        llog(f"Location table loaded from {tracker_path}: {len(tracker)} locations, "
             f"{len(marker_filter)} unique markers")
    if always_visible_path:
        always_visible = load_always_visible(always_visible_path)
        llog(f"AlwaysVisible loaded from {always_visible_path}: {len(always_visible)} records")

    _stage(0)
    with open(path, 'rb') as fh:
        raw = fh.read()

    f = Reader(raw)
    header = parse_header(f, qlog)
    starting_offset = header['starting_offset']

    _stage(1)
    body = decompress_body(f, header['comp_type'], qlog)
    b = Reader(body)

    _stage(2)
    form_version = b.u8()
    qlog(f"Form version: {form_version}")
    supports_esl = form_version >= 78

    plugin_info_size, plugin_start_pos, number_of_full, full_plugins = \
        parse_plugin_info(b, qlog)

    if supports_esl:
        number_of_lite = b.u16()
        lite_plugins = [b.wstring() for _ in range(number_of_lite)]
    else:
        number_of_lite = 0
        lite_plugins = []

    computed_size = 1 + sum(2 + len(p.encode(ENCODING, errors='replace')) for p in full_plugins)
    if supports_esl:
        computed_size += 2 + sum(2 + len(p.encode(ENCODING, errors='replace')) for p in lite_plugins)
    consumed = b.pos - plugin_start_pos
    qlog(f"\nPluginInfo self-check: declared size={plugin_info_size}, "
         f"actually read={consumed} bytes "
         f"({'OK' if consumed == plugin_info_size else 'MISMATCH!'})")

    qlog(f"\nFull plugins ({number_of_full}):")
    for i, p in enumerate(full_plugins):
        qlog(f"  [{i:02X}] {p}")
    if supports_esl:
        qlog(f"\nLight plugins ({number_of_lite}):")
        for i, p in enumerate(lite_plugins):
            qlog(f"  [FE {i:03X}] {p}")

    plugins_out_path, plugins_cc = write_plugins_final(path, full_plugins, lite_plugins)
    qlog(f"\nPlugin list written: {plugins_out_path} "
         f"({number_of_full} full + {number_of_lite} light, of them CC: {plugins_cc})")

    # --- FileLocationTable ---
    _stage(3)
    formid_array_count_offset = b.u32()
    unknown_table3_offset = b.u32()
    table1_offset = b.u32()
    table2_offset = b.u32()
    changeforms_offset = b.u32()
    table3_offset = b.u32()
    table1_count = b.u32()
    table2_count = b.u32()
    table3_count_raw = b.u32()
    table3_count = table3_count_raw + 1
    changeform_count = b.u32()
    b.read(15 * 4)

    qlog(f"\nFileLocationTable: changeFormCount={changeform_count}, "
         f"TABLE1COUNT={table1_count}, TABLE2COUNT={table2_count}, "
         f"TABLE3COUNT={table3_count}")

    formid_body_pos = formid_array_count_offset - starting_offset
    b.pos = formid_body_pos
    formid_count = b.u32()
    form_ids = [b.u32() for _ in range(formid_count)]
    qlog(f"FormID array: {formid_count} records")

    body_pos = changeforms_offset - starting_offset
    if not (0 <= body_pos <= len(body)):
        raise ValueError(
            f"changeFormsOffset ({changeforms_offset}) - startingOffset "
            f"({starting_offset}) = {body_pos}, which is outside the file body "
            f"(0..{len(body)}).")
    b.pos = body_pos

    quest_forms = []
    location_forms = []
    shout_forms = []  # (refid, change_flags, version, length1, length2, data) for type_code==WOOP_TYPE_CODE
    ench_forms = []   # (refid, change_flags, version, length1, length2, data) for type_code==ENCH_TYPE_CODE
    ingr_forms = []   # the same, for type_code==INGR_TYPE_CODE
    achr_player_form = None   # (refid, change_flags, version, length1, length2, data, kind)
    npc_player_form = None    # the same, for the player's NPC_ record
    achr_forms = []           # all ACHR (refid, change_flags, data, length2) - for mannequins (Collectibles)
    other_type_counts = {}
    errors = 0

    for i in range(changeform_count):
        try:
            refid = b.refid_raw()
            change_flags = b.u32()
            typefield = b.u8()
            version = b.i8()
            type_code = typefield & 0x3F
            size_sel = typefield >> 6
            if size_sel == 0:
                length1, length2 = b.u8(), b.u8()
            elif size_sel == 1:
                length1, length2 = b.u16(), b.u16()
            else:
                length1, length2 = b.u32(), b.u32()
            data = b.read(length1)

            if type_code == QUST_TYPE_CODE:
                quest_forms.append((refid, change_flags, version, length1, length2, data))
            elif type_code == REFR_TYPE_CODE:
                location_forms.append((refid, change_flags, version, length1, length2, data))
            elif type_code == WOOP_TYPE_CODE:
                other_type_counts[type_code] = other_type_counts.get(type_code, 0) + 1
                shout_forms.append((refid, change_flags, version, length1, length2, data))
            elif type_code == INGR_TYPE_CODE:
                other_type_counts[type_code] = other_type_counts.get(type_code, 0) + 1
                ingr_forms.append((refid, change_flags, version, length1, length2, data))
            elif type_code == ENCH_TYPE_CODE:
                other_type_counts[type_code] = other_type_counts.get(type_code, 0) + 1
                ench_forms.append((refid, change_flags, version, length1, length2, data))
            elif type_code == ACHR_TYPE_CODE:
                other_type_counts[type_code] = other_type_counts.get(type_code, 0) + 1
                achr_forms.append((refid, change_flags, data, length2))
                p_chk, l_chk, k_chk = resolve_refid(refid, full_plugins, lite_plugins, form_ids)
                if p_chk is not None and l_chk == PLAYER_LOCAL_ID \
                        and full_plugins and p_chk == full_plugins[0]:
                    achr_player_form = (refid, change_flags, version, length1, length2, data, k_chk)
            elif type_code == NPC_TYPE_CODE:
                other_type_counts[type_code] = other_type_counts.get(type_code, 0) + 1
                p_chk, l_chk, k_chk = resolve_refid(refid, full_plugins, lite_plugins, form_ids)
                if p_chk is not None and l_chk == PLAYER_BASE_LOCAL_ID \
                        and full_plugins and p_chk == full_plugins[0]:
                    npc_player_form = (refid, change_flags, version, length1, length2, data, k_chk)
            else:
                other_type_counts[type_code] = other_type_counts.get(type_code, 0) + 1
        except EOFError as e:
            errors += 1
            qlog(f"[warn] stopped reading ChangeForms at record {i}/{changeform_count}: {e}")
            break

    qlog(f"\nChangeForm records read: {i + 1 - errors if errors else changeform_count} "
         f"of {changeform_count} declared")
    qlog(f"Of them QUST (code 8): {len(quest_forms)}")
    qlog(f"Of them REFR (code 0): {len(location_forms)}")
    qlog(f"Other types (top 10): "
         f"{sorted(other_type_counts.items(), key=lambda kv: -kv[1])[:10]}")

    # ------------------------------------------------------------------
    _stage(4)
    # QUST
    # ------------------------------------------------------------------
    qlog(f"\n--- QUST changeforms: reached stages ---")
    parsed_ok = 0
    parsed_skipped = 0
    quest_csv_rows = []
    qust_status_by_key = {}
    for refid, change_flags, version, length1, length2, data in quest_forms:
        refid_hex = f"0x{refid:06X}"
        plugin, local_id, kind = resolve_refid(refid, full_plugins, lite_plugins, form_ids)

        if quest_marker_filter is not None and plugin is not None \
                and (plugin, local_id) not in quest_marker_filter:
            continue

        is_light = plugin in lite_plugins if plugin else False
        if plugin is not None:
            resolved = f"{plugin}:{local_id:06X} ({kind})"
        else:
            resolved = f"NOT RESOLVED ({kind}, raw={refid_hex})"
        if length2 > 0:
            try:
                payload = zlib.decompress(data)
            except zlib.error as e:
                qlog(f"  [warn] refid={refid_hex}: zlib decompression error ({e})")
                parsed_skipped += 1
                continue
        else:
            payload = data

        result = parse_qust_changeform(payload, change_flags, qlog, refid_hex)
        if result is None:
            parsed_skipped += 1
            continue
        parsed_ok += 1
        stages = result['stages']
        stage_status = result['stage_status']
        qflags = result['quest_flags']
        qflags_str = f"0b{qflags:016b} (0x{qflags:04X})" if qflags is not None else "(CHANGE_QUEST_FLAGS bit not set)"
        status_str = ', '.join(f"{s}:{st}" for s, st in stage_status)
        if stages:
            qlog(f"  {resolved}  QUEST_FLAGS={qflags_str}  stages(number:status): [{status_str}]")
        else:
            qlog(f"  {resolved}  QUEST_FLAGS={qflags_str}  (CHANGE_QUEST_STAGES bit "
                 f"not set - stages did not change)")

        if plugin is not None:
            quest_csv_rows.append({
                'plugin': plugin,
                'local_form_id_hex': f"{local_id:06X}" if local_id >= 0 else '',
                'is_light': int(is_light),
                'resolution_kind': kind,
                'quest_flags_hex': f"{qflags:04X}" if qflags is not None else '',
                'max_stage_reached': max((sn for sn, sv in stage_status if sv == 1), default=''),
                'stages': ','.join(str(s) for s in stages),
                'stage_status': ','.join(f"{s}:{st}" for s, st in stage_status),
            })
            bit1_done = None if qflags is None else bool((qflags >> 1) & 1)
            # 0x40 = Failed. A failed quest ALSO carries 0x02 (Completed), so
            # Failed is checked first (verified on save11: Elmus Favor Quest
            # DLC2ThirskFFElmus and CW01B, both QUEST_FLAGS 0x0142).
            bit6_failed = None if qflags is None else bool((qflags >> 6) & 1)
            # stages whose status byte is 1 = actually reached; status 0 =
            # listed in the change form but never set (Bloody Nose:
            # 10:1, 200:0, 250:0 is NOT past stage 200)
            reached = [s for s, st_ in stage_status if st_ == 1]
            qust_status_by_key[(plugin, local_id)] = {
                'bit1_done': bit1_done, 'bit6_failed': bit6_failed,
                'max_reached': max(reached) if reached else None,
            }

    qlog(f"\nQUST total: parsed {parsed_ok}, skipped {parsed_skipped}")

    with open(quests_out_path, 'w', encoding='utf-8') as out:
        out.write('\n'.join(quest_lines))

    quests_csv_path = out_base(path) + '.quests_resolved.csv'
    with open(quests_csv_path, 'w', encoding='utf-8', newline='') as csvf:
        writer = csv.DictWriter(csvf, fieldnames=[
            'plugin', 'local_form_id_hex', 'is_light', 'resolution_kind',
            'quest_flags_hex', 'max_stage_reached', 'stages', 'stage_status'])
        writer.writeheader()
        writer.writerows(quest_csv_rows)

    # ------------------------------------------------------------------
    # FINAL QUEST ASSEMBLY (for the HTML tracker)
    # ------------------------------------------------------------------
    quests_final_csv_path = out_base(path) + '.quests_final.csv'
    quests_final_report_path = out_base(path) + '.quests_final_report.txt'
    qfinal_lines = []

    def qflog(msg):
        qfinal_lines.append(msg)

    def quest_candidate_status(plugin, local_id, sub_edid, overrides):
        """Order of checks: FAILED (0x40) -> DONE (flag, 0x02) -> DONE (stage
        override: a stage >= threshold with status 1) -> NOT DONE / UNKNOWN.
        Returns 'FAILED' | 'DONE (flag)' | 'DONE (stage override)' | 'NOT DONE' |
        'UNKNOWN' | 'NOT_IN_SAVE'. Order and meaning repeat match_quests.py
        1:1 (bit1_is_set + override): bit1 is not a bool but True/False/None;
        None (CHANGE_QUEST_FLAGS bit not set, and the override did not fire /
        is not defined) - honestly UNKNOWN, not silently NOT DONE."""
        st = qust_status_by_key.get((plugin, local_id))
        if st is None:
            return 'NOT_IN_SAVE'
        if st['bit6_failed'] is True:
            return 'FAILED'
        bit1 = st['bit1_done']
        if bit1 is True:
            return 'DONE (flag)'
        threshold = overrides.get(sub_edid)
        if threshold is not None and st['max_reached'] is not None and st['max_reached'] >= threshold:
            return 'DONE (stage override)'
        if bit1 is False:
            return 'NOT DONE'
        return 'UNKNOWN'

    STATUS_PRIORITY = ['DONE (flag)', 'DONE (stage override)', 'FAILED', 'NOT DONE', 'UNKNOWN', 'NOT_IN_SAVE']

    def merge_quest_status(statuses):
        for s in STATUS_PRIORITY:
            if s in statuses:
                return s
        return 'NOT_IN_SAVE'

    quest_final_rows = []
    quest_final_counts = {}
    for qt in quest_tracker:
        if qt['handle']:
            quest_final_counts['HANDLE'] = quest_final_counts.get('HANDLE', 0) + 1
            quest_final_rows.append({
                'Order': qt['order'], 'Tab': qt['tab'], 'Block': qt['block'],
                'SubBlock': qt['subblock'], 'Name': qt['name'],
                'EditorIDs': qt['editor_ids'], 'Key': qt['key'],
                'Status': 'HANDLE', 'Details': '',
            })
            continue
        details = []
        statuses = []
        for plugin, local_id, sub_edid in qt['candidates']:
            st = quest_candidate_status(plugin, local_id, sub_edid, qt['overrides'])
            statuses.append(st)
            details.append(f"{plugin}:{local_id:06X}={sub_edid}:{st}")

        final_status = merge_quest_status(statuses)
        quest_final_counts[final_status] = quest_final_counts.get(final_status, 0) + 1
        quest_final_rows.append({
            'Order': qt['order'], 'Tab': qt['tab'], 'Block': qt['block'],
            'SubBlock': qt['subblock'], 'Name': qt['name'],
            'EditorIDs': qt['editor_ids'], 'Key': qt['key'],
            'Status': final_status, 'Details': '|'.join(details),
        })
        qflog(f"  [{qt['block']}] {qt['name']} ({qt['editor_ids']})  ->  {final_status}   "
              f"({'; '.join(details)})")

    qflog(f"\nQuests total: {len(quest_tracker)}. {quest_final_counts}")

    with open(quests_final_report_path, 'w', encoding='utf-8') as out:
        out.write('\n'.join(qfinal_lines))

    with open(quests_final_csv_path, 'w', encoding='utf-8', newline='') as csvf:
        writer = csv.DictWriter(csvf, delimiter=';', fieldnames=[
            'Order', 'Tab', 'Block', 'SubBlock', 'Name', 'EditorIDs', 'Key',
            'Status', 'Details'])
        writer.writeheader()
        writer.writerows(quest_final_rows)

    # ------------------------------------------------------------------
    _stage(5)
    # REFR (location map markers)
    # ------------------------------------------------------------------
    llog(f"\n--- REFR changeforms: map marker status ---")
    loc_parsed = {'DISCOVERED': 0, 'NOT_DISCOVERED': 0, 'NO_OVERRIDE': 0, 'UNKNOWN': 0}
    loc_skipped_not_in_filter = 0
    location_csv_rows = []

    for refid, change_flags, version, length1, length2, data in location_forms:
        refid_hex = f"0x{refid:06X}"
        plugin, local_id, kind = resolve_refid(refid, full_plugins, lite_plugins, form_ids)
        if plugin is None:
            continue

        if marker_filter is not None and (plugin, local_id) not in marker_filter:
            loc_skipped_not_in_filter += 1
            continue

        if length2 > 0:
            try:
                payload = zlib.decompress(data)
            except zlib.error as e:
                llog(f"  [warn] refid={refid_hex}: zlib decompression error ({e})")
                continue
        else:
            payload = data

        result = parse_location_marker_changeform(payload, change_flags, kind, llog, refid_hex)
        loc_parsed[result['status']] = loc_parsed.get(result['status'], 0) + 1

        raw_byte_str = f"0x{result['raw_byte']:02X}" if result['raw_byte'] is not None else ''
        llog(f"  {plugin}:{local_id:06X} ({kind})  change_flags=0x{change_flags:08X}  "
             f"status={result['status']}  raw_byte={raw_byte_str}"
             + (f"  ({result['reason']})" if result['reason'] else ''))

        location_csv_rows.append({
            'plugin': plugin,
            'local_form_id_hex': f"{local_id:06X}",
            'resolution_kind': kind,
            'change_flags_hex': f"{change_flags:08X}",
            'status': result['status'],
            'raw_byte_hex': raw_byte_str,
            'reason': result['reason'] or '',
        })

    llog(f"\nREFR total (in filter{' - no markers given, all processed' if marker_filter is None else ''}): "
         f"{loc_parsed}")
    if marker_filter is not None:
        llog(f"Skipped (not in the map marker list): {loc_skipped_not_in_filter}")

    with open(locations_out_path, 'w', encoding='utf-8') as out:
        out.write('\n'.join(location_lines))

    locations_csv_path = out_base(path) + '.locations_resolved.csv'
    with open(locations_csv_path, 'w', encoding='utf-8', newline='') as csvf:
        writer = csv.DictWriter(csvf, fieldnames=[
            'plugin', 'local_form_id_hex', 'resolution_kind',
            'change_flags_hex', 'status', 'raw_byte_hex', 'reason'])
        writer.writeheader()
        writer.writerows(location_csv_rows)

    # ------------------------------------------------------------------
    # FINAL LOCATION ASSEMBLY (for the HTML tracker)
    # ------------------------------------------------------------------
    final_csv_path = out_base(path) + '.locations_final.csv'
    final_report_path = out_base(path) + '.locations_final_report.txt'
    final_lines = []

    def flog(msg):
        final_lines.append(msg)

    # per-marker "raw" status, key (plugin, local_id) -> status dict
    per_marker_status = {}
    for row in location_csv_rows:
        plugin = row['plugin']
        local_id = int(row['local_form_id_hex'], 16)
        per_marker_status[(plugin, local_id)] = row['status']

    def marker_effective_status(plugin, local_id):
        """Returns 'DISCOVERED' | 'NOT_DISCOVERED' | 'UNKNOWN' for one
        marker, resolving NO_OVERRIDE / a missing ChangeForm through
        AlwaysVisible."""
        raw_status = per_marker_status.get((plugin, local_id))
        if raw_status == 'DISCOVERED':
            return 'DISCOVERED'
        if raw_status == 'NOT_DISCOVERED':
            return 'NOT_DISCOVERED'
        if raw_status == 'UNKNOWN':
            return 'UNKNOWN'
        # raw_status is None (no ChangeForm at all) OR 'NO_OVERRIDE' -
        # AlwaysVisible is needed in both cases.
        av = always_visible.get((plugin, local_id))
        if av is True:
            return 'DISCOVERED'
        if av is False:
            return 'NOT_DISCOVERED'
        return 'UNKNOWN'  # the marker is not even in the AlwaysVisible export

    final_rows = []
    final_counts = {'DISCOVERED': 0, 'NOT_DISCOVERED': 0, 'UNKNOWN': 0}
    for loc in tracker:
        marker_details = []
        effective_statuses = []
        for plugin, local_id in loc['markers']:
            eff = marker_effective_status(plugin, local_id)
            effective_statuses.append(eff)
            marker_details.append(f"{plugin}:{local_id:06X}={eff}")

        if 'DISCOVERED' in effective_statuses:
            final_status = 'DISCOVERED'
        elif 'UNKNOWN' in effective_statuses:
            final_status = 'UNKNOWN'
        else:
            final_status = 'NOT_DISCOVERED'

        final_counts[final_status] += 1
        final_rows.append({
            'Order': loc['order'], 'Block': loc['block'], 'Name': loc['name'],
            'Tags': loc['tags'], 'Status': final_status,
            'Details': '|'.join(marker_details),
        })
        flog(f"  [{loc['block']}] {loc['name']}  ->  {final_status}   "
             f"({'; '.join(marker_details)})")

    flog(f"\nLocations total: {len(tracker)}. "
         f"DISCOVERED={final_counts['DISCOVERED']}, "
         f"NOT_DISCOVERED={final_counts['NOT_DISCOVERED']}, "
         f"UNKNOWN={final_counts['UNKNOWN']}")

    with open(final_report_path, 'w', encoding='utf-8') as out:
        out.write('\n'.join(final_lines))

    with open(final_csv_path, 'w', encoding='utf-8', newline='') as csvf:
        writer = csv.DictWriter(csvf, delimiter=';', fieldnames=[
            'Order', 'Block', 'Name', 'Tags', 'Status', 'Details'])
        writer.writeheader()
        writer.writerows(final_rows)

    # ------------------------------------------------------------------
    _stage(6)
    # SPELLS (player spells)
    # ------------------------------------------------------------------
    spells_out_path = out_base(path) + '.spells_report.txt'
    spells_final_csv_path = out_base(path) + '.spells_final.csv'
    spells_lines = []

    def slog(msg):
        spells_lines.append(msg)

    spells_tracker_rows = []
    if spells_tracker_path:
        spells_tracker_rows = load_spells_tracker(spells_tracker_path)
        slog(f"Spell table loaded from {spells_tracker_path}: "
             f"{len(spells_tracker_rows)} rows")

    learned_keys = set()
    spells_list_ok = False  # True only for an unambiguously found, non-empty ACHR spell list

    if achr_player_form is None:
        slog("[!] The player ACHR record (RefID 0x14) was not found in this save.")
    else:
        refid, change_flags, version, length1, length2, data, kind = achr_player_form
        if length2 > 0:
            try:
                payload = zlib.decompress(data)
            except zlib.error as e:
                slog(f"[warn] player ACHR: zlib decompression error ({e})")
                payload = None
        else:
            payload = data

        if payload is not None:
            slog(f"Player ACHR record found: refid=0x{refid:06X}, "
                 f"change_flags=0x{change_flags:08X}, version={version}, "
                 f"payload={len(payload)} bytes")
            result = parse_achr_actor_spells(payload, change_flags, kind, slog, f"0x{refid:06X}")
            slog(f"decoded_bytes={result['decoded_bytes']} of {len(payload)} payload bytes "
                 f"(parse status: {result['status']}"
                 + (f", {result['reason']}" if result['reason'] else '') + ")")
            slog(f"Spells found in the unparsed tail of the record: {len(result['spells'])}")
            spells_list_ok = result['status'] == 'OK' and len(result['spells']) > 0

            slog("\nLearned spells (ACHR, during play) (plugin:local_id):")
            for raw in result['spells']:
                plugin, local_id, kind2 = resolve_refid(raw, full_plugins, lite_plugins, form_ids)
                if plugin is None:
                    slog(f"  [warn] spell does not resolve (raw=0x{raw:06X})")
                    continue
                learned_keys.add((plugin.lower(), local_id))
                slog(f"  {plugin}:{local_id:06X}")

    if npc_player_form is None:
        slog("\n[!] The player NPC_ record was not found - starting spells "
             "(Flames/Healing etc.) will not be counted separately.")
    else:
        refid, change_flags, version, length1, length2, data, kind = npc_player_form
        if length2 > 0:
            try:
                base_payload = zlib.decompress(data)
            except zlib.error as e:
                slog(f"[warn] player NPC_: zlib decompression error ({e})")
                base_payload = None
        else:
            base_payload = data

        if base_payload is not None:
            base_result = parse_npc_base_spells(base_payload, change_flags, slog, f"0x{refid:06X}")
            base_spells = base_result.get('spells', [])
            base_levelled = base_result.get('levelled_spells', [])
            base_shouts = base_result.get('shouts', [])
            slog(f"\nStarting spells (NPC_): {len(base_spells)} spells, "
                 f"{len(base_levelled)} levelled, {len(base_shouts)} shouts")
            for raw in base_spells:
                plugin, local_id, kind2 = resolve_refid(raw, full_plugins, lite_plugins, form_ids)
                if plugin is None:
                    continue
                key = (plugin.lower(), local_id)
                if key not in learned_keys:
                    learned_keys.add(key)
                    slog(f"  {plugin}:{local_id:06X}  (starting)")

    spells_final_rows = []
    if spells_tracker_rows:
        learned_count = 0
        for row in spells_tracker_rows:
            plugin = row['Plugin'].strip()
            local_id = int(row['LocalID'].strip(), 16)
            learned = (plugin.lower(), local_id) in learned_keys
            if learned:
                learned_count += 1
            spells_final_rows.append({
                'Order': row['Order'], 'Block': row['Block'], 'Name': row['Name'],
                'Tags': row['Tags'],
                'Status': 'LEARNED' if learned else 'NOT_LEARNED',
                'Details': f"{plugin}:{local_id:06X}={row['EditorID']}",
            })
        slog(f"\nTotal: {learned_count} of {len(spells_tracker_rows)} tracker spells "
             f"marked as learned.")

        with open(spells_final_csv_path, 'w', encoding='utf-8', newline='') as csvf:
            writer = csv.DictWriter(csvf, delimiter=';', fieldnames=[
                'Order', 'Block', 'Name', 'Tags', 'Status', 'Details'])
            writer.writeheader()
            writer.writerows(spells_final_rows)

    with open(spells_out_path, 'w', encoding='utf-8') as out:
        out.write('\n'.join(spells_lines))

    # ------------------------------------------------------------------
    _stage(7)
    # SHOUTS (words of power)
    # ------------------------------------------------------------------
    shouts_out_path = out_base(path) + '.shouts_report.txt'
    shouts_final_csv_path = out_base(path) + '.shouts_final.csv'
    shouts_lines = []

    def shlog(msg):
        shouts_lines.append(msg)

    shouts_tracker_rows = []
    if shouts_tracker_path:
        shouts_tracker_rows = load_shouts_tracker(shouts_tracker_path)
        shlog(f"Word of power table loaded from {shouts_tracker_path}: "
              f"{len(shouts_tracker_rows)} rows")

    # A word counts as learned when its WOOP record has ANY ChangeForm
    # with type_code==WOOP_TYPE_CODE - see the comment at the constant above
    # about the record being delayed until the first use of the shout.
    shout_learned_keys = set()
    shlog(f"\nTotal ChangeForm records with type_code=={WOOP_TYPE_CODE}: {len(shout_forms)}")
    for refid, change_flags, version, length1, length2, data in shout_forms:
        plugin, local_id, kind = resolve_refid(refid, full_plugins, lite_plugins, form_ids)
        if plugin is None:
            shlog(f"  [warn] WOOP record does not resolve (raw=0x{refid:06X})")
            continue
        shout_learned_keys.add((plugin.lower(), local_id))

    shouts_final_rows = []
    if shouts_tracker_rows:
        learned_count = 0
        for row in shouts_tracker_rows:
            plugin = row['Plugin'].strip()
            local_id = int(row['LocalID'].strip(), 16)
            learned = (plugin.lower(), local_id) in shout_learned_keys
            if learned:
                learned_count += 1
            shouts_final_rows.append({
                'Order': row['Order'], 'Block': row['Block'], 'Name': row['Name'],
                'Tags': row['Tags'],
                'Status': 'LEARNED' if learned else 'NOT_LEARNED',
                'Details': f"{plugin}:{local_id:06X}={row['EditorID']}",
            })
        shlog(f"\nTotal: {learned_count} of {len(shouts_tracker_rows)} tracker words "
              f"marked as learned.")

        with open(shouts_final_csv_path, 'w', encoding='utf-8', newline='') as csvf:
            writer = csv.DictWriter(csvf, delimiter=';', fieldnames=[
                'Order', 'Block', 'Name', 'Tags', 'Status', 'Details'])
            writer.writeheader()
            writer.writerows(shouts_final_rows)

    with open(shouts_out_path, 'w', encoding='utf-8') as out:
        out.write('\n'.join(shouts_lines))

    # ------------------------------------------------------------------
    _stage(8)
    # ENCHANTING EFFECTS: learned enchanting effects
    # ------------------------------------------------------------------
    ench_out_path = out_base(path) + '.enchanting_report.txt'
    ench_final_csv_path = out_base(path) + '.enchanting_final.csv'
    ench_lines = []

    def elog(msg):
        ench_lines.append(msg)

    ench_tracker_rows = []
    if enchanting_tracker_path:
        ench_tracker_rows = load_enchanting_tracker(enchanting_tracker_path)
        elog(f"Enchanting effect table loaded from {enchanting_tracker_path}: "
             f"{len(ench_tracker_rows)} rows")

    ench_learned_keys = set()
    elog(f"\nTotal ChangeForm records with type_code=={ENCH_TYPE_CODE}: {len(ench_forms)}")
    for refid, change_flags, version, length1, length2, data in ench_forms:
        plugin, local_id, kind = resolve_refid(refid, full_plugins, lite_plugins, form_ids)
        if plugin is None:
            elog(f"  [warn] ENCH record does not resolve (raw=0x{refid:06X}, {kind})")
            continue
        ench_learned_keys.add((plugin.lower(), local_id))
        payload = data
        if length2 > 0:
            try:
                payload = zlib.decompress(data)
            except zlib.error:
                payload = None
        if change_flags != ENCH_OBSERVED_FLAGS or payload != ENCH_OBSERVED_PAYLOAD:
            elog(f"  [info] {plugin}:{local_id:06X} - content differs from the sample "
                 f"(flags=0x{change_flags:08X}, payload="
                 f"{payload.hex(' ') if payload is not None else 'zlib-ERROR'}); "
                 f"does not affect the status, only the presence of the record counts")

    ench_final_rows = []
    if ench_tracker_rows:
        learned_count = 0
        tracker_keys = set()
        for row in ench_tracker_rows:
            plugin = row['Plugin'].strip()
            local_id = int(row['LocalID'].strip(), 16)
            key = (plugin.lower(), local_id)
            tracker_keys.add(key)
            learned = key in ench_learned_keys
            if learned:
                learned_count += 1
            ench_final_rows.append({
                'Order': row['Order'], 'Block': row['Block'], 'Name': row['Name'],
                'Tags': row['Tags'],
                'Status': 'LEARNED' if learned else 'NOT_LEARNED',
                'Details': f"{plugin}:{local_id:06X}={row['EditorID']}",
            })
        extra = sorted(ench_learned_keys - tracker_keys)
        if extra:
            elog(f"\n[info] ENCH records in the save that are not in the tracker ({len(extra)}):")
            for pl, lid in extra:
                elog(f"  {pl}:{lid:06X}")
        elog(f"\nTotal: {learned_count} of {len(ench_tracker_rows)} tracker effects "
             f"marked as learned.")

        with open(ench_final_csv_path, 'w', encoding='utf-8', newline='') as csvf:
            writer = csv.DictWriter(csvf, delimiter=';', fieldnames=[
                'Order', 'Block', 'Name', 'Tags', 'Status', 'Details'])
            writer.writeheader()
            writer.writerows(ench_final_rows)

    with open(ench_out_path, 'w', encoding='utf-8') as out:
        out.write('\n'.join(ench_lines))

    # ------------------------------------------------------------------
    _stage(9)
    # INGREDIENTS: mask of learned effects (see the comment at INGR_TYPE_CODE)
    # ------------------------------------------------------------------
    ingr_out_path = out_base(path) + '.ingredients_report.txt'
    ingr_final_csv_path = out_base(path) + '.ingredients_final.csv'
    ingr_lines = []

    def ilog(msg):
        ingr_lines.append(msg)

    ingr_tracker_rows = []
    if ingredients_tracker_path:
        ingr_tracker_rows = load_ingredients_tracker(ingredients_tracker_path)
        ilog(f"Ingredient table loaded from {ingredients_tracker_path}: "
             f"{len(ingr_tracker_rows)} rows")

    # (plugin_lower, local_id) -> (mask_or_None, raw_description)
    ingr_masks = {}
    ilog(f"\nTotal ChangeForm records with type_code=={INGR_TYPE_CODE}: {len(ingr_forms)}")
    for refid, change_flags, version, length1, length2, data in ingr_forms:
        plugin, local_id, kind = resolve_refid(refid, full_plugins, lite_plugins, form_ids)
        if plugin is None:
            ilog(f"  [warn] INGR record does not resolve (raw=0x{refid:06X}, {kind})")
            continue
        payload = data
        if length2 > 0:
            try:
                payload = zlib.decompress(data)
            except zlib.error:
                payload = None
        raw = payload.hex(' ') if payload is not None else 'zlib-ERROR'
        mask = None
        if change_flags == INGR_OBSERVED_FLAGS and payload is not None and len(payload) == 4:
            value = struct.unpack('<I', payload)[0]
            if value <= 0x0F:
                mask = value
        if mask is None:
            ilog(f"  [info] {plugin}:{local_id:06X} - format does not match the confirmed one "
                 f"(flags=0x{change_flags:08X}, payload={raw}) -> UNKNOWN")
        ingr_masks[(plugin.lower(), local_id)] = (mask, raw)

    if ingr_tracker_rows:
        counts = {'DISCOVERED': 0, 'PARTIAL': 0, 'NOT DISCOVERED': 0, 'UNKNOWN': 0}
        final_rows = []
        tracker_keys = set()
        for row in ingr_tracker_rows:
            plugin = row['Plugin'].strip()
            local_id = int(row['LocalID'].strip(), 16)
            key = (plugin.lower(), local_id)
            tracker_keys.add(key)
            mask, raw = ingr_masks.get(key, (0, '(no record)'))
            if mask is None:
                status, known = 'UNKNOWN', ''
                bits = ['?'] * 4
            else:
                bits = ['Y' if mask & (1 << n) else 'N' for n in range(4)]
                known = bits.count('Y')
                status = ('DISCOVERED' if known == 4 else
                          'PARTIAL' if known > 0 else 'NOT DISCOVERED')
            counts[status] += 1
            for a in filter(None, row.get('AltCandidates', '').split('|')):
                pl, rest = a.split(':', 1)
                akey = (pl.strip().lower(), int(rest.split('=', 1)[0], 16))
                tracker_keys.add(akey)
                if akey in ingr_masks:
                    ilog(f"  [info] {row['Name']}: the alternative record {a} has an "
                         f"INGR ChangeForm ({ingr_masks[akey][1]}) - NOT counted in the "
                         f"status, whether copies share knowledge is not confirmed")
            final_rows.append({
                'Order': row['Order'], 'Block': row['Block'], 'Name': row['Name'],
                'Tags': row['Tags'], 'Status': status, 'Known': ''.join(bits),
                'Details': f"{plugin}:{local_id:06X}={row['EditorID']} raw={raw}",
            })
        extra = sorted(k for k in ingr_masks if k not in tracker_keys)
        if extra:
            ilog(f"\n[info] INGR records in the save that are not in the tracker ({len(extra)}):")
            for pl, lid in extra:
                ilog(f"  {pl}:{lid:06X} payload={ingr_masks[(pl, lid)][1]}")
        ilog("\nNot fully learned:")
        for fr in final_rows:
            if fr['Status'] != 'DISCOVERED':
                ilog(f"  {fr['Name']}: {fr['Status']} {fr['Known'].count('Y')}/4 "
                     f"[{fr['Known']}] {fr['Details']}")
        ilog(f"\nTotal of {len(final_rows)}: " +
             ", ".join(f"{k}={v}" for k, v in counts.items()))

        with open(ingr_final_csv_path, 'w', encoding='utf-8', newline='') as csvf:
            writer = csv.DictWriter(csvf, delimiter=';', fieldnames=[
                'Order', 'Block', 'Name', 'Tags', 'Status', 'Known', 'Details'])
            writer.writeheader()
            writer.writerows(final_rows)

    with open(ingr_out_path, 'w', encoding='utf-8') as out:
        out.write('\n'.join(ingr_lines))

    # ------------------------------------------------------------------
    _stage(10)
    # PERKS: list A in the player ACHR (see the comment at find_perk_block)
    # ------------------------------------------------------------------
    perks_out_path = out_base(path) + '.perks_report.txt'
    perks_final_csv_path = out_base(path) + '.perks_final.csv'
    perk_lines = []

    def plog(msg):
        perk_lines.append(msg)

    perks_tracker_rows = []
    if perks_tracker_path:
        perks_tracker_rows = load_perks_tracker(perks_tracker_path)
        plog(f"Perk table loaded from {perks_tracker_path}: {len(perks_tracker_rows)} rows")

    perk_keys = None   # set((plugin_lower, local_id)) or None = UNKNOWN
    if achr_player_form is None:
        plog("[!] The player ACHR record (RefID 0x14) was not found -> all perks UNKNOWN")
    else:
        refid, change_flags, version, length1, length2, data, kind = achr_player_form
        payload = data
        if length2 > 0:
            try:
                payload = zlib.decompress(data)
            except zlib.error as e:
                plog(f"[warn] player ACHR: zlib decompression error ({e}) -> all perks UNKNOWN")
                payload = None
        if payload is not None:
            hits = find_perk_block(payload)
            plog(f"Searching the perk block in the player ACHR ({len(payload)} bytes): shape matches = {len(hits)}")
            if len(hits) != 1:
                for h in hits:
                    plog(f"  offset={h['offset']} |A|={len(h['A'])} |B|={len(h['B'])} |C|={len(h['C'])}")
                plog("[!] the match is not unique -> all perks UNKNOWN (no guessing)")
            else:
                h = hits[0]
                plog(f"  offset={h['offset']} end={h['end']} |A|={len(h['A'])} "
                     f"|B|={len(h['B'])} |C|={len(h['C'])}")
                perk_keys = set()
                for raw in h['A']:
                    pl, lid, kd = resolve_refid(raw, full_plugins, lite_plugins, form_ids)
                    if pl is None:
                        plog(f"  [warn] perk from A does not resolve (raw=0x{raw:06X}, {kd})")
                        continue
                    perk_keys.add((pl.lower(), lid))

    if perks_tracker_rows:
        final_rows = []
        counts = {'OBTAINED': 0, 'NOT OBTAINED': 0, 'UNKNOWN': 0}
        tracker_keys = set()
        done_n = total_n = 0
        for row in perks_tracker_rows:
            plugin = row['Plugin'].strip()
            local_id = int(row['LocalID'].strip(), 16)
            key = (plugin.lower(), local_id)
            tracker_keys.add(key)
            source = row['Source'].strip().upper()
            if source == 'SPEL':
                # Prowler's Profit: not a PERK but an ability -> the player spell list
                # (learned_keys from the SPELLS section above). If the spell list was not
                # found unambiguously - UNKNOWN, not NOT OBTAINED.
                if not spells_list_ok:
                    status = 'UNKNOWN'
                else:
                    status = 'OBTAINED' if key in learned_keys else 'NOT OBTAINED'
            elif perk_keys is None:
                status = 'UNKNOWN'
            else:
                status = 'OBTAINED' if key in perk_keys else 'NOT OBTAINED'
            counts[status] += 1
            optional = 'Optional' in row['Tags'].split('|')
            # Project rule: an optional row counts (in both the numerator and the
            # denominator) only when obtained; an optional row not obtained does not count.
            if not optional or status == 'OBTAINED':
                total_n += 1
                if status == 'OBTAINED':
                    done_n += 1
            final_rows.append({
                'Order': row['Order'], 'Block': row['Block'], 'SubBlock': row['SubBlock'],
                'Name': row['Name'], 'Tags': row['Tags'], 'Status': status,
                'Details': f"{plugin}:{local_id:06X}={row['EditorID']} ({source})",
            })
        if perk_keys:
            extra = sorted(k for k in perk_keys if k not in tracker_keys)
            plog(f"\n[info] perks in A that are not in the tracker ({len(extra)}) - service/"
                 f"racial/item/quest perks outside the table:")
            for pl, lid in extra:
                plog(f"  {pl}:{lid:06X}")
        plog("\nNot obtained:")
        for fr in final_rows:
            if fr['Status'] != 'OBTAINED':
                plog(f"  [{fr['SubBlock'] or fr['Block']}] {fr['Name']}: {fr['Status']}"
                     + (" (optional - not counted)"
                        if 'Optional' in fr['Tags'].split('|') else ""))
        plog(f"\nStatus totals of {len(final_rows)}: " +
             ", ".join(f"{k}={v}" for k, v in counts.items()))
        plog(f"Score with optional rule: {done_n}/{total_n}")

        with open(perks_final_csv_path, 'w', encoding='utf-8', newline='') as csvf:
            writer = csv.DictWriter(csvf, delimiter=';', fieldnames=[
                'Order', 'Block', 'SubBlock', 'Name', 'Tags', 'Status', 'Details'])
            writer.writeheader()
            writer.writerows(final_rows)

    with open(perks_out_path, 'w', encoding='utf-8') as out:
        out.write('\n'.join(perk_lines))

    # ------------------------------------------------------------------
    _stage(11)
    # COLLECTIBLES (see the big comment at coll_read_initial)
    # ------------------------------------------------------------------
    coll_out_path = out_base(path) + '.collectibles_report.txt'
    coll_final_csv_path = out_base(path) + '.collectibles_final.csv'
    coll_lines = []

    def clog(msg):
        coll_lines.append(msg)

    coll_tracker_rows = []
    if collectibles_tracker_path and collectibles_houses_path:
        coll_tracker_rows = load_collectibles_tracker(collectibles_tracker_path)
        coll_cells, coll_holders = load_collectibles_houses(collectibles_houses_path)
        clog(f"Collectibles tracker: {collectibles_tracker_path} ({len(coll_tracker_rows)} rows)")
        clog(f"Homes: {collectibles_houses_path} ({len(coll_cells)} cells, "
             f"{len(coll_holders)} containers/mannequins)")

        def cres(raw):
            p_, l_, k_ = resolve_refid(raw, full_plugins, lite_plugins, form_ids)
            return ((p_ or '').lower(), l_, k_)

        coll_found, coll_unknown, coll_ignored, holders_seen = stored_items_scan(
            coll_tracker_rows, coll_cells, coll_holders, location_forms, achr_forms, cres)

        final_rows = []
        counts = {'OBTAINED': 0, 'NOT OBTAINED': 0, 'UNKNOWN': 0}
        for row in coll_tracker_rows:
            per_base = [coll_found.get(bk, []) for bk in row['_bases']]
            mode = row['Mode'].strip().upper()
            required = int(row['Required'])
            if mode == 'ALL':
                have = sum(1 for v in per_base if v)
                ok = have == len(row['_bases'])
                progress = f"{have}/{len(row['_bases'])}"
            elif mode == 'COUNT':
                have = sum(n for v in per_base for _, _, n in v)
                ok = have >= required
                progress = f"{min(have, required)}/{required}"
            else:
                ok = any(per_base)
                progress = ''
            if ok:
                status = 'OBTAINED'
            elif coll_unknown:
                status = 'UNKNOWN'
            else:
                status = 'NOT OBTAINED'
            counts[status] += 1
            where = sorted({h for v in per_base for h, _, _ in v})
            final_rows.append({
                'Order': row['Order'], 'Block': row['Block'], 'Name': row['Name'],
                'Tags': row['Tags'], 'Status': status, 'Progress': progress,
                'Details': '|'.join(where),
            })

        clog(f"\nTotal: OBTAINED {counts['OBTAINED']}/{len(final_rows)}, "
             f"NOT OBTAINED {counts['NOT OBTAINED']}, UNKNOWN {counts['UNKNOWN']}")
        clog(f"Home containers/mannequins with a record in the save: {len(holders_seen)} of "
             f"{len(coll_holders)} (no record = never touched)")
        clog(f"Persistent items not in the world (old cell ignored): {len(coll_ignored)}")
        for g in coll_ignored:
            clog(f"  - {g}")
        clog(f"Not parsed (-> UNKNOWN for rows not found): {len(coll_unknown)}")
        for u in coll_unknown:
            clog(f"  ! {u}")
        clog("")
        for row, fr in zip(coll_tracker_rows, final_rows):
            clog(f"[{fr['Status']:<12}] {fr['Block']} | {fr['Name']}"
                 + (f" ({fr['Progress']})" if fr['Progress'] else ''))
            for bk in row['_bases']:
                for hh, how, n in coll_found.get(bk, []):
                    clog(f"      {hh}: {how}" + (f" x{n}" if n != 1 else ''))

        with open(coll_final_csv_path, 'w', encoding='utf-8', newline='') as csvf:
            writer = csv.DictWriter(csvf, delimiter=';', fieldnames=[
                'Order', 'Block', 'Name', 'Tags', 'Status', 'Progress', 'Details'])
            writer.writeheader()
            writer.writerows(final_rows)
    else:
        clog("Collectibles were not computed: collectibles_tracker.csv (argument 10) "
             "and collectibles_houses.csv (11) are required.")

    with open(coll_out_path, 'w', encoding='utf-8') as out:
        out.write('\n'.join(coll_lines))

    # ------------------------------------------------------------------
    _stage(12)
    # BOOKS (the same home search as Collectibles: stored_items_scan)
    # books_tracker.csv (Order;Block;SubBlock;Name;Tags;BaseKeys;BaseEditorIDs;
    # PersistentRefs, HTML order) - argument 12, homes - the same collectibles_houses.csv
    # (11). Only a book lying in a tracked home counts
    # (PlayerBookShelfContainer shelf / container / in the world / mannequin).
    # Reading a book and the player inventory do NOT count.
    # ------------------------------------------------------------------
    books_out_path = out_base(path) + '.books_report.txt'
    books_final_csv_path = out_base(path) + '.books_final.csv'
    book_lines = []

    def blog(msg):
        book_lines.append(msg)

    book_tracker_rows = []
    if books_tracker_path and collectibles_houses_path:
        book_tracker_rows = load_collectibles_tracker(books_tracker_path)
        b_cells, b_holders = load_collectibles_houses(collectibles_houses_path)
        blog(f"Books tracker: {books_tracker_path} ({len(book_tracker_rows)} rows)")
        blog(f"Homes: {collectibles_houses_path} ({len(b_cells)} cells, "
             f"{len(b_holders)} containers/mannequins)")

        def bres(raw):
            p_, l_, k_ = resolve_refid(raw, full_plugins, lite_plugins, form_ids)
            return ((p_ or '').lower(), l_, k_)

        b_found, b_unknown, b_ignored, b_seen = stored_items_scan(
            book_tracker_rows, b_cells, b_holders, location_forms, achr_forms, bres)

        b_final = []
        b_counts = {'OBTAINED': 0, 'NOT OBTAINED': 0, 'UNKNOWN': 0}
        for row in book_tracker_rows:
            per_base = [b_found.get(bk, []) for bk in row['_bases']]
            if any(per_base):
                status = 'OBTAINED'
            elif b_unknown:
                status = 'UNKNOWN'
            else:
                status = 'NOT OBTAINED'
            b_counts[status] += 1
            where = sorted({h for v in per_base for h, _, _ in v})
            b_final.append({
                'Order': row['Order'], 'Block': row['Block'], 'SubBlock': row['SubBlock'],
                'Name': row['Name'], 'Tags': row['Tags'], 'Status': status,
                'Details': '|'.join(where),
            })

        blog(f"\nTotal: OBTAINED {b_counts['OBTAINED']}/{len(b_final)}, "
             f"NOT OBTAINED {b_counts['NOT OBTAINED']}, UNKNOWN {b_counts['UNKNOWN']}")
        sk_rows = [r for r in b_final if r['SubBlock']]   # skill books = rows in a skill sub-block
        blog(f"Skill books: {sum(r['Status'] == 'OBTAINED' for r in sk_rows)}/{len(sk_rows)}")
        blog(f"Home containers/mannequins with a record in the save: {len(b_seen)} of "
             f"{len(b_holders)} (no record = never touched)")
        blog(f"Persistent books not in the world (old cell ignored): {len(b_ignored)}")
        for g in b_ignored:
            blog(f"  - {g}")
        blog(f"Not parsed (-> UNKNOWN for rows not found): {len(b_unknown)}")
        for u in b_unknown:
            blog(f"  ! {u}")
        blog("")
        for row, fr in zip(book_tracker_rows, b_final):
            label = f"{fr['Block']}/{fr['SubBlock']}" if fr['SubBlock'] else fr['Block']
            blog(f"[{fr['Status']:<12}] {label} | {fr['Name']}")
            for bk in row['_bases']:
                for hh, how, n in b_found.get(bk, []):
                    blog(f"      {hh}: {how}" + (f" x{n}" if n != 1 else ''))

        with open(books_final_csv_path, 'w', encoding='utf-8', newline='') as csvf:
            writer = csv.DictWriter(csvf, delimiter=';', fieldnames=[
                'Order', 'Block', 'SubBlock', 'Name', 'Tags', 'Status', 'Details'])
            writer.writeheader()
            writer.writerows(b_final)
    else:
        blog("Books were not computed: collectibles_houses.csv (argument 11) "
             "and books_tracker.csv (12) are required.")

    with open(books_out_path, 'w', encoding='utf-8') as out:
        out.write('\n'.join(book_lines))

    _stage(13)
    tracker_json_path = write_tracker_json(path, header, form_version, full_plugins, lite_plugins, {
        'quests': quests_final_csv_path if quest_tracker else None,
        'locations': final_csv_path if tracker else None,
        'spells': spells_final_csv_path if spells_tracker_rows else None,
        'shouts': shouts_final_csv_path if shouts_tracker_rows else None,
        'enchanting': ench_final_csv_path if ench_tracker_rows else None,
        'ingredients': ingr_final_csv_path if ingr_tracker_rows else None,
        'perks': perks_final_csv_path if perks_tracker_rows else None,
        'collectibles': coll_final_csv_path if coll_tracker_rows else None,
        'books': books_final_csv_path if book_tracker_rows else None,
    })

    print(f"Done.")
    print(f"For the tracker: {tracker_json_path}")
    print(f"Quests (raw):    report {quests_out_path}, CSV {quests_csv_path}")
    if quest_tracker:
        print(f"Quests (final):  report {quests_final_report_path}, CSV {quests_final_csv_path}")
    else:
        print(f"[!] The final quest CSV was NOT created - quests_tracker.csv was not given "
              f"as the fourth argument.")
    print(f"Locations (raw): report {locations_out_path}, CSV {locations_csv_path}")
    if tracker:
        print(f"Locations (final): report {final_report_path}, CSV {final_csv_path}")
    else:
        print(f"[!] The final location CSV was NOT created - locations_tracker.csv was not "
              f"given as the second argument.")
    print(f"Spells:          report {spells_out_path}"
          + (f", CSV {spells_final_csv_path}" if spells_tracker_rows else ""))
    if not spells_tracker_rows:
        print(f"[!] The final spell CSV was NOT created - spells_tracker.csv was not "
              f"given as the fifth argument.")
    print(f"Shouts:          report {shouts_out_path}"
          + (f", CSV {shouts_final_csv_path}" if shouts_tracker_rows else ""))
    if not shouts_tracker_rows:
        print(f"[!] The final shout CSV was NOT created - shouts_tracker.csv was not "
              f"given as the sixth argument.")
    print(f"Enchanting:      report {ench_out_path}"
          + (f", CSV {ench_final_csv_path}" if ench_tracker_rows else ""))
    print(f"Ingredients:     report {ingr_out_path}"
          + (f", CSV {ingr_final_csv_path}" if ingr_tracker_rows else ""))
    if not ingr_tracker_rows:
        print(f"[!] The final ingredient CSV was NOT created - ingredients_tracker.csv was "
              f"not given as the eighth argument.")
    if not ench_tracker_rows:
        print(f"[!] The final enchanting CSV was NOT created - enchanting_tracker.csv was "
              f"not given as the seventh argument.")
    print(f"Perks:           report {perks_out_path}"
          + (f", CSV {perks_final_csv_path}" if perks_tracker_rows else ""))
    if not perks_tracker_rows:
        print(f"[!] The final perk CSV was NOT created - perks_tracker.csv was not "
              f"given as the ninth argument.")
    print(f"Collectibles:    report {coll_out_path}"
          + (f", CSV {coll_final_csv_path}" if coll_tracker_rows else ""))
    if not coll_tracker_rows:
        print(f"[!] The final collectibles CSV was NOT created - collectibles_tracker.csv "
              f"and collectibles_houses.csv were not given as arguments 10 and 11.")
    print(f"Books:           report {books_out_path}"
          + (f", CSV {books_final_csv_path}" if book_tracker_rows else ""))
    if not book_tracker_rows:
        print(f"[!] The final books CSV was NOT created - collectibles_houses.csv "
              f"and books_tracker.csv were not given as arguments 11 and 12.")
    print(f"Plugins:         CSV {plugins_out_path} "
          f"({number_of_full} full + {number_of_lite} light, CC: {plugins_cc})")
    print(f"(the output is deliberately not printed to the console directly, "
          f"to avoid a UnicodeEncodeError from the PowerShell encoding)")


CSV_ORDER = ('locations_tracker.csv', 'MapMarkerExport.csv', 'quests_tracker.csv',
             'spells_tracker.csv', 'shouts_tracker.csv', 'enchanting_tracker.csv',
             'ingredients_tracker.csv', 'perks_tracker.csv', 'collectibles_tracker.csv',
             'collectibles_houses.csv', 'books_tracker.csv')


def run(save_path, csv_data, progress=None):
    """Parses one save for the desktop app and returns the tracker dict
    (format skyrim-tracker/1, the same content as --json-only writes).
    csv_data - {file name: raw bytes} for every name in CSV_ORDER. Reports,
    *_final.csv and the JSON go to a temporary folder that is removed; nothing
    is written next to the save."""
    import io, shutil, tempfile, contextlib
    global OUT_BASE, JSON_PATH, PROGRESS, LAST_RESULT
    CSV_DATA.clear()
    CSV_DATA.update(csv_data)
    tmp = tempfile.mkdtemp(prefix='skyrim_tracker_')
    OUT_BASE = os.path.join(tmp, 'save')
    JSON_PATH = os.path.join(tmp, 'save.tracker.json')
    PROGRESS = progress
    LAST_RESULT = None
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            main(save_path, *CSV_ORDER)
        return LAST_RESULT
    finally:
        OUT_BASE = JSON_PATH = PROGRESS = None
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: py parse_ess.py <path_to_save.ess> "
              "[locations_tracker.csv] [MapMarkerExport.csv] "
              "[quests_tracker.csv] [spells_tracker.csv] [shouts_tracker.csv] "
              "[enchanting_tracker.csv] [ingredients_tracker.csv] [perks_tracker.csv] "
              "[collectibles_tracker.csv] [collectibles_houses.csv] [books_tracker.csv] [--json-only]")
        sys.exit(1)
    # '-' (or an empty argument) = skip this tracker, so that only the needed
    # positions can be given: py parse_ess.py save.ess - - - ... books.csv
    # --json-only (anywhere on the line): write only <save>.tracker.json next to
    # the save; reports and *_final.csv go to a temp folder that is deleted
    json_only = '--json-only' in sys.argv
    sys.argv = [a for a in sys.argv if a != '--json-only']
    sys.argv = [a if a not in ('-', '') else None for a in sys.argv]
    tracker_csv = sys.argv[2] if len(sys.argv) > 2 else None
    always_visible_csv = sys.argv[3] if len(sys.argv) > 3 else None
    quest_tracker_csv = sys.argv[4] if len(sys.argv) > 4 else None
    spells_tracker_csv = sys.argv[5] if len(sys.argv) > 5 else None
    shouts_tracker_csv = sys.argv[6] if len(sys.argv) > 6 else None
    enchanting_tracker_csv = sys.argv[7] if len(sys.argv) > 7 else None
    ingredients_tracker_csv = sys.argv[8] if len(sys.argv) > 8 else None
    perks_tracker_csv = sys.argv[9] if len(sys.argv) > 9 else None
    collectibles_tracker_csv = sys.argv[10] if len(sys.argv) > 10 else None
    collectibles_houses_csv = sys.argv[11] if len(sys.argv) > 11 else None
    books_tracker_csv = sys.argv[12] if len(sys.argv) > 12 else None
    args = (sys.argv[1], tracker_csv, always_visible_csv, quest_tracker_csv,
            spells_tracker_csv, shouts_tracker_csv, enchanting_tracker_csv,
            ingredients_tracker_csv, perks_tracker_csv,
            collectibles_tracker_csv, collectibles_houses_csv, books_tracker_csv)
    if not json_only:
        main(*args)
    else:
        import io, shutil, tempfile, contextlib
        tmp = tempfile.mkdtemp(prefix='skyrim_tracker_')
        OUT_BASE = os.path.join(tmp, os.path.splitext(os.path.basename(sys.argv[1]))[0])
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                main(*args)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        print(f"Done: {os.path.splitext(sys.argv[1])[0] + '.tracker.json'}")
