//! Reads a Skyrim save and builds tracker.json from it and the tracker tables.

use std::collections::{HashMap, HashSet};

use crate::inflate::zlib_decompress;
use crate::lz4::decompress_block;
use crate::pycsv::{decode_utf8_sig, dict_reader, py_int10, py_int16, Row};
use crate::pyjson;
use crate::reader::{Eof, Reader};

// ---------------------------------------------------------------------------
// constants
const QUST_TYPE_CODE: u8 = 8;
const REFR_TYPE_CODE: u8 = 0;
const ACHR_TYPE_CODE: u8 = 1;
const NPC_TYPE_CODE: u8 = 9;
const WOOP_TYPE_CODE: u8 = 34;
const ENCH_TYPE_CODE: u8 = 48;
const INGR_TYPE_CODE: u8 = 16;
const INGR_OBSERVED_FLAGS: u32 = 0x8000_0000;
const PLAYER_LOCAL_ID: i64 = 0x14;
const PLAYER_BASE_LOCAL_ID: i64 = 0x07;
const K_MIN_ACTOR_SPELLS: u32 = 32;
const K_MAX_ACTOR_SPELLS: u32 = 2048;
const ACHR_ACTOR_EXTRA_DATA_BITS: [u32; 10] = [6, 9, 11, 17, 18, 25, 26, 29, 30, 31];
const PERK_BLOCK_MIN_A: u32 = 10;
const PERK_BLOCK_MAX_A: u32 = 4096;
const COLL_REFR_EXTRA_BITS_A: &[u32] = &[6, 10, 11, 12, 17, 25, 26, 29, 31];
const COLL_REFR_EXTRA_BITS_B: &[u32] = &[6, 10, 11, 12, 17, 25, 26, 29, 31, 30];
const COLL_FORM_FLAG_DELETED: u32 = 0x20;
const COLL_EXTRA_NOT_IN_WORLD: u8 = 0x1C;
pub const TRACKER_JSON_FORMAT: &str = "skyrim-tracker/2";

/// the tracker tables
pub const CSV_ORDER: [&str; 11] = [
    "locations_tracker.csv",
    "MapMarkerExport.csv",
    "quests_tracker.csv",
    "spells_tracker.csv",
    "shouts_tracker.csv",
    "enchanting_tracker.csv",
    "ingredients_tracker.csv",
    "perks_tracker.csv",
    "collectibles_tracker.csv",
    "collectibles_houses.csv",
    "books_tracker.csv",
];

/// loading stages, as the loader on the page shows them
pub const STAGE_NAMES: [&str; 14] = [
    "Reading save", "Decompressing", "Plugins", "Change forms", "Quests", "Locations", "Spells",
    "Shouts", "Enchanting", "Ingredients", "Perks", "Collectibles", "Books", "Building tracker",
];

#[derive(Debug)]
pub struct ParseError {
    /// the stage that failed
    pub stage: usize,
    pub message: String,
}

impl std::fmt::Display for ParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "stage {} ({}): {}", self.stage, STAGE_NAMES[self.stage.min(13)], self.message)
    }
}

/// file name -> contents
pub type Tables = HashMap<String, Vec<u8>>;

// ---------------------------------------------------------------------------
// errors used while walking a change form (the text is for debugging)
#[allow(dead_code)]
enum PErr {
    Abort(String),
    Eof(String),
}
impl From<Eof> for PErr {
    fn from(e: Eof) -> Self {
        PErr::Eof(e.0)
    }
}

// ---------------------------------------------------------------------------
// header
struct Header {
    starting_offset: usize,
    comp_type: u16,
    version: u32,
    save_number: u32,
    name: String,
    level: u32,
    location: String,
    game_date: String,
    race_eid: String,
    sex: u16,
    cur_xp: f32,
    needed_xp: f32,
}

fn parse_header(f: &mut Reader) -> Result<Header, String> {
    let e = |x: Eof| x.0;
    let magic = f.read(13).map_err(e)?;
    if magic != b"TESV_SAVEGAME" {
        return Err(format!(
            "Unexpected signature: {:?}. Is this really a Skyrim SE/AE save file?",
            String::from_utf8_lossy(magic)
        ));
    }
    let header_size = f.u32().map_err(e)? as usize;
    let header_start = f.pos;
    let version = f.u32().map_err(e)?;
    let save_number = f.u32().map_err(e)?;
    let name = f.wstring().map_err(e)?;
    let level = f.u32().map_err(e)?;
    let location = f.wstring().map_err(e)?;
    let game_date = f.wstring().map_err(e)?;
    let race_eid = f.wstring().map_err(e)?;
    let sex = f.u16().map_err(e)?;
    let cur_xp = f.f32().map_err(e)?;
    let needed_xp = f.f32().map_err(e)?;
    let _filetime = f.u64().map_err(e)?;
    let shot_w = f.u32().map_err(e)? as usize;
    let shot_h = f.u32().map_err(e)? as usize;
    let comp_type = f.u16().map_err(e)?;
    let consumed = f.pos - header_start;
    if consumed != header_size {
        return Err(format!(
            "Header size mismatch: HEADERSIZE={header_size}, actually read {consumed} bytes. \
             This may not be a regular SKYRIM_SE Steam save (VR/another platform?), where the \
             compression field is laid out differently."
        ));
    }
    let shot = 4usize.checked_mul(shot_w).and_then(|v| v.checked_mul(shot_h)).unwrap_or(usize::MAX);
    f.read(shot).map_err(e)?;
    Ok(Header {
        starting_offset: f.pos,
        comp_type,
        version,
        save_number,
        name,
        level,
        location,
        game_date,
        race_eid,
        sex,
        cur_xp,
        needed_xp,
    })
}

fn decompress_body(f: &mut Reader, comp_type: u16) -> Result<Vec<u8>, String> {
    if comp_type == 0 {
        return Ok(f.data[f.pos..].to_vec());
    }
    let e = |x: Eof| x.0;
    let uncompressed_len = f.u32().map_err(e)? as usize;
    let compressed_len = f.u32().map_err(e)? as usize;
    let comp = f.read(compressed_len).map_err(e)?;
    match comp_type {
        1 => zlib_decompress(comp).map_err(|x| format!("Error while decompressing data: {}", x.0)),
        2 => decompress_block(comp, uncompressed_len).map_err(|x| x.0),
        _ => Err(format!("Unknown compression type: {comp_type}")),
    }
}

// ---------------------------------------------------------------------------
// RefID resolution
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Kind {
    Zero,
    FormIdx,
    FormIdxOutOfRange,
    Default,
    Created,
    Invalid,
}

struct Plugins {
    full: Vec<String>,
    lite: Vec<String>,
    full_lc: Vec<String>,
    lite_lc: Vec<String>,
    form_ids: Vec<u32>,
}

#[derive(Clone, Copy)]
enum P {
    None,
    Full(usize),
    Lite(usize),
    Created,
}

impl Plugins {
    fn get_plugin_for(&self, formid: u32) -> P {
        let index = ((formid >> 24) & 0xFF) as usize;
        let subindex = ((formid & 0xFF_FFFF) >> 12) as usize;
        if index < 0xFE && index < self.full.len() {
            P::Full(index)
        } else if index == 0xFE && subindex < self.lite.len() {
            P::Lite(subindex)
        } else {
            P::None
        }
    }

    fn resolve_p(&self, raw: u32) -> (P, i64, Kind) {
        let val_part = raw & 0x3F_FFFF;
        let type_idx = (raw >> 22) & 3;
        if val_part == 0 {
            return (P::None, 0, Kind::Zero);
        }
        match type_idx {
            0 => {
                let form_index = val_part as usize - 1;
                if form_index < self.form_ids.len() {
                    let formid = self.form_ids[form_index];
                    let p = self.get_plugin_for(formid);
                    let is_lite = matches!(p, P::Lite(_));
                    let local = formid & if is_lite { 0xFFF } else { 0xFF_FFFF };
                    (p, local as i64, Kind::FormIdx)
                } else {
                    (P::None, -1, Kind::FormIdxOutOfRange)
                }
            }
            1 => {
                let p = if self.full.is_empty() { P::None } else { P::Full(0) };
                (p, val_part as i64, Kind::Default)
            }
            2 => (P::Created, val_part as i64, Kind::Created),
            _ => (P::None, 0, Kind::Invalid),
        }
    }

    /// plugin and record a reference points to
    fn resolve(&self, raw: u32) -> (Option<&str>, i64, Kind) {
        let (p, l, k) = self.resolve_p(raw);
        let name = match p {
            P::None => None,
            P::Full(i) => Some(self.full[i].as_str()),
            P::Lite(i) => Some(self.lite[i].as_str()),
            P::Created => Some("(Created)"),
        };
        (name, l, k)
    }

    /// the same, plugin name in lower case
    fn resolve_lc(&self, raw: u32) -> (&str, i64, Kind) {
        let (p, l, k) = self.resolve_p(raw);
        let name = match p {
            P::None => "",
            P::Full(i) => self.full_lc[i].as_str(),
            P::Lite(i) => self.lite_lc[i].as_str(),
            P::Created => "(created)",
        };
        (name, l, k)
    }
}

/// values by plugin and record
struct PKMap<V> {
    m: HashMap<String, HashMap<i64, V>>,
}
impl<V> PKMap<V> {
    fn new() -> Self {
        PKMap { m: HashMap::new() }
    }
    fn insert(&mut self, p: &str, l: i64, v: V) {
        self.m.entry(p.to_string()).or_default().insert(l, v);
    }
    fn get(&self, p: &str, l: i64) -> Option<&V> {
        self.m.get(p).and_then(|x| x.get(&l))
    }
    fn get_mut(&mut self, p: &str, l: i64) -> Option<&mut V> {
        self.m.get_mut(p).and_then(|x| x.get_mut(&l))
    }
    fn contains(&self, p: &str, l: i64) -> bool {
        self.get(p, l).is_some()
    }
}
type PKSet = PKMap<()>;
impl PKSet {
    fn add(&mut self, p: &str, l: i64) {
        self.insert(p, l, ());
    }
}

// ---------------------------------------------------------------------------
// change forms
struct ChangeForm<'a> {
    refid: u32,
    change_flags: u32,
    length2: u32,
    data: &'a [u8],
}

impl ChangeForm<'_> {
    /// change form data, unpacked if compressed
    fn payload(&self) -> Result<std::borrow::Cow<'_, [u8]>, String> {
        if self.length2 > 0 {
            zlib_decompress(self.data).map(std::borrow::Cow::Owned).map_err(|e| e.0.to_string())
        } else {
            Ok(std::borrow::Cow::Borrowed(self.data))
        }
    }
}

fn has_bit(flags: u32, n: u32) -> bool {
    (flags >> n) & 1 == 1
}

// --- QUST
struct QustResult {
    quest_flags: Option<u16>,
    stage_status: Vec<(i16, u8)>,
}

fn parse_qust_changeform(data: &[u8], change_flags: u32) -> Option<QustResult> {
    if has_bit(change_flags, 0) {
        return None;
    }
    let mut r = Reader::new(data);
    let res = (|| -> Result<QustResult, Eof> {
        let mut quest_flags = None;
        if has_bit(change_flags, 1) {
            quest_flags = Some(r.u16()?);
        }
        if has_bit(change_flags, 2) {
            r.f32()?;
        }
        let mut stage_status = Vec::new();
        if has_bit(change_flags, 31) {
            let count = r.vsval()?;
            for _ in 0..count {
                let stage = r.i16()?;
                let status = r.u8()?;
                stage_status.push((stage, status));
            }
        }
        Ok(QustResult { quest_flags, stage_status })
    })();
    res.ok()
}

// --- ExtraData
fn read_vs_count_skip(r: &mut Reader, size: usize) -> Result<(), PErr> {
    let count = r.vsval()? as usize;
    r.read(size * count)?;
    Ok(())
}

fn parse_extra_data_element(r: &mut Reader) -> Result<(u8, Option<u8>), PErr> {
    let type_code = r.u8()?;
    let mut map_marker = None;
    match type_code {
        0 => {}
        4 => {
            parse_extra_data_element(r)?;
        }
        8 => {
            parse_extra_data_element(r)?;
            parse_extra_data_element(r)?;
        }
        12 => {
            parse_extra_data_element(r)?;
            parse_extra_data_element(r)?;
            parse_extra_data_element(r)?;
        }
        22 | 23 => {}
        24 => {
            r.refid_raw()?;
            r.read(12)?;
            r.f32()?;
        }
        25 => {
            r.refid_raw()?;
            r.refid_raw()?;
            r.u32()?;
            r.read(3)?;
        }
        26 => {
            if r.refid_raw()? == 0 {
                return Err(PErr::Abort("TrespassPackage(26) incomplete (ref=0)".into()));
            }
        }
        27 => read_vs_count_skip(r, 4)?,
        28 => {
            r.refid_raw()?;
        }
        29 => {}
        30 => {
            r.u32()?;
        }
        31 => {
            r.u8()?;
        }
        32 => {}
        33 | 34 | 35 => {
            r.refid_raw()?;
        }
        36 => {
            r.u16()?;
        }
        37 => {
            r.f32()?;
        }
        39 => {
            r.u32()?;
        }
        40 => {
            r.f32()?;
        }
        42 => {
            r.read(2)?;
            r.refid_raw()?;
            r.u32()?;
            r.u32()?;
        }
        43 => {
            r.read(12)?;
            r.read(12)?;
            r.u8()?;
            r.refid_raw()?;
        }
        44 => map_marker = Some(r.u8()?),
        45 => {
            return Err(PErr::Abort(
                "LeveledCreature(45): ChangeFormNPC.java structure not confirmed".into(),
            ))
        }
        46 => {
            r.u32()?;
            r.u8()?;
        }
        47 => {
            r.f32()?;
        }
        49 => {
            r.u32()?;
            r.refid_raw()?;
            r.u32()?;
            r.u32()?;
            r.refid_raw()?;
            r.f32()?;
            r.refid_raw()?;
            r.refid_raw()?;
        }
        50 => {
            r.refid_raw()?;
            let count = r.vsval()?;
            for _ in 0..count {
                r.refid_raw()?;
                r.u8()?;
                r.vsval()?;
                read_vs_count_skip(r, 1)?;
            }
        }
        52 => read_vs_count_skip(r, 8)?,
        53 => {}
        56 => {
            r.refid_raw()?;
        }
        61 => {}
        62 => {
            r.refid_raw()?;
            r.u32()?;
        }
        68 => read_vs_count_skip(r, 4)?,
        69 | 72 => {
            r.refid_raw()?;
        }
        73 => {
            r.u8()?;
        }
        76 => {
            r.wstring_raw()?;
            r.read(5)?;
            for _ in 0..4 {
                r.refid_raw()?;
            }
        }
        77 => {
            r.u8()?;
        }
        79 => {
            r.read(2)?;
        }
        83 => {
            r.u32()?;
        }
        84 => {
            r.u8()?;
        }
        85 => {
            r.f32()?;
        }
        88 => {
            r.refid_raw()?;
            r.u32()?;
        }
        89 => {
            r.f32()?;
        }
        91 => {
            let count = r.vsval()?;
            for _ in 0..count {
                r.refid_raw()?;
                r.u8()?;
            }
            r.refid_raw()?;
            r.u8()?;
        }
        92 => {
            r.u16()?;
            r.u32()?;
            r.u32()?;
            r.u8()?;
            r.refid_raw()?;
            let count = r.vsval()?;
            for _ in 0..count {
                r.read(4)?;
                let inner = r.vsval()?;
                for _ in 0..inner {
                    r.refid_raw()?;
                }
            }
        }
        93 => {
            r.u32()?;
        }
        101 => {
            r.refid_raw()?;
        }
        102 => {
            r.refid_raw()?;
            r.refid_raw()?;
        }
        104 => {
            r.refid_raw()?;
        }
        106 => {
            r.refid_raw()?;
            r.u32()?;
        }
        111 => {
            let count = r.vsval()?;
            for _ in 0..count {
                r.refid_raw()?;
                r.u32()?;
                r.u32()?;
            }
        }
        112 => {
            r.refid_raw()?;
        }
        113 => {
            r.refid_raw()?;
            r.u8()?;
            r.u32()?;
            r.refid_raw()?;
            r.wstring_raw()?;
            r.wstring_raw()?;
            r.u32()?;
            r.u32()?;
            r.u8()?;
            r.refid_raw()?;
            r.refid_raw()?;
            r.refid_raw()?;
            r.u8()?;
        }
        120 => {
            let count = r.vsval()?;
            for _ in 0..count {
                r.refid_raw()?;
                r.u32()?;
                r.u8()?;
            }
        }
        133 => {
            r.refid_raw()?;
        }
        135 => {
            for _ in 0..4 {
                r.refid_raw()?;
            }
        }
        136 => {
            let count = r.vsval()?;
            for _ in 0..count {
                r.refid_raw()?;
                r.u32()?;
            }
        }
        140 => {
            let count = r.vsval()?;
            for _ in 0..count {
                r.refid_raw()?;
            }
        }
        142 | 146 => {
            r.refid_raw()?;
        }
        149 => {
            r.refid_raw()?;
            r.u32()?;
        }
        150 => {
            r.u8()?;
        }
        152 => {
            let count = r.vsval()?;
            for _ in 0..count {
                let rf = r.refid_raw()?;
                if rf != 0 {
                    let v = r.i16()?;
                    if v != -1 {
                        r.u32()?;
                        r.read(32)?;
                    }
                }
            }
            r.u16()?;
            r.u16()?;
        }
        153 => {
            let ref1 = r.refid_raw()?;
            let ref2 = r.refid_raw()?;
            let unk = r.i32()?;
            if ref1 == 0 && ref2 == 0 && unk == -2 {
                r.wstring_raw()?;
            }
        }
        155 => {
            r.refid_raw()?;
            r.u16()?;
        }
        156 => {
            r.u8()?;
        }
        157 => {
            r.refid_raw()?;
        }
        159 => {
            r.u32()?;
            r.u16()?;
        }
        160 => {
            r.u32()?;
        }
        161 => {
            r.read(4 * 18)?;
            r.read(4 * 4)?;
        }
        164 => {
            r.refid_raw()?;
        }
        169 => {
            r.u32()?;
            r.refid_raw()?;
            r.refid_raw()?;
            r.u8()?;
        }
        174 => {
            r.u32()?;
            r.refid_raw()?;
            r.wstring_raw()?;
            r.wstring_raw()?;
            r.read(12)?;
            r.read(12)?;
            r.u32()?;
            r.f32()?;
        }
        175 => {
            let count = r.u32()?;
            for _ in 0..count {
                r.refid_raw()?;
                r.u32()?;
            }
        }
        176 => {
            r.f32()?;
            r.f32()?;
        }
        t => {
            return Err(PErr::Abort(format!(
                "Unknown ExtraData type={t} (no such case in ChangeFormExtraDataData.java)"
            )))
        }
    }
    Ok((type_code, map_marker))
}

/// which start data a reference has (the order of checks matters)
fn initial_type(change_flags: u32, kind: Kind) -> u8 {
    if kind == Kind::Created {
        5
    } else if has_bit(change_flags, 25) || has_bit(change_flags, 3) {
        6
    } else if has_bit(change_flags, 2) || has_bit(change_flags, 1) {
        4
    } else {
        0
    }
}

/// reads the start data: cell and base record
fn read_initial(r: &mut Reader, it: u8) -> Result<(Option<u32>, Option<u32>), Eof> {
    let (mut cell, mut base) = (None, None);
    match it {
        4 => {
            cell = Some(r.refid_raw()?);
            r.read(12)?;
            r.read(12)?;
        }
        5 => {
            cell = Some(r.refid_raw()?);
            r.read(12)?;
            r.read(12)?;
            r.read(1)?;
            base = Some(r.refid_raw()?);
        }
        6 => {
            cell = Some(r.refid_raw()?);
            r.read(12)?;
            r.read(12)?;
            r.refid_raw()?;
            r.read(2)?;
            r.read(2)?;
        }
        _ => {}
    }
    Ok((cell, base))
}

// --- locations
#[derive(Clone, Copy, PartialEq)]
enum LocStatus {
    Discovered,
    NotDiscovered,
    NoOverride,
    Unknown,
}

fn parse_location_marker_changeform(payload: &[u8], cf: u32, kind: Kind) -> LocStatus {
    let mut r = Reader::new(payload);
    let res = (|| -> Result<LocStatus, PErr> {
        read_initial(&mut r, initial_type(cf, kind))?;
        if has_bit(cf, 2) {
            read_vs_count_skip(&mut r, 1)?;
        }
        if has_bit(cf, 0) {
            r.read(4)?;
            r.read(2)?;
        }
        if has_bit(cf, 7) {
            r.refid_raw()?;
        }
        if has_bit(cf, 4) {
            r.f32()?;
        }
        if !has_bit(cf, 31) {
            return Ok(LocStatus::NoOverride);
        }
        let count = r.vsval()?;
        if count > 1024 {
            return Err(PErr::Abort(format!("Invalid EXTRA_DATA_COUNT={count}")));
        }
        let mut value = None;
        for _ in 0..count {
            let (t, v) = parse_extra_data_element(&mut r)?;
            if t == 44 {
                value = v;
            }
        }
        Ok(match value {
            None => LocStatus::Unknown,
            Some(v) if v & 0x02 != 0 => LocStatus::Discovered,
            Some(_) => LocStatus::NotDiscovered,
        })
    })();
    res.unwrap_or(LocStatus::Unknown)
}

// --- spells
fn read_spell_array_raw(block: &[u8], at: usize) -> Option<Vec<u32>> {
    if block.len() - at < 4 {
        return None;
    }
    let count = u32::from_le_bytes([block[at], block[at + 1], block[at + 2], block[at + 3]]);
    if !(K_MIN_ACTOR_SPELLS..=K_MAX_ACTOR_SPELLS).contains(&count) {
        return None;
    }
    let mut at = at + 4;
    if (block.len() - at) / 3 < count as usize {
        return None;
    }
    let mut found = Vec::with_capacity(count as usize);
    let mut seen = HashSet::with_capacity(count as usize);
    for _ in 0..count {
        let raw = (block[at] as u32) << 16 | (block[at + 1] as u32) << 8 | block[at + 2] as u32;
        let val_part = raw & 0x3F_FFFF;
        let type_idx = (raw >> 22) & 3;
        if val_part == 0 || type_idx == 3 {
            return None;
        }
        if !seen.insert(raw) {
            return None;
        }
        found.push(raw);
        at += 3;
    }
    Some(found)
}

fn find_actor_spells_raw(block: &[u8]) -> Vec<u32> {
    let mut out: Vec<u32> = Vec::new();
    let n = block.len();
    let mut i = 0;
    while i + 4 <= n {
        if let Some(spells) = read_spell_array_raw(block, i) {
            if !out.is_empty() {
                return Vec::new(); // ambiguous
            }
            out = spells;
        }
        i += 1;
    }
    out
}

fn decode_inventory(r: &mut Reader, keep: bool) -> Result<Vec<(u32, i32)>, PErr> {
    let mut stacks = Vec::new();
    let count = r.vsval()?;
    if count > 200_000 {
        return Err(PErr::Abort(format!("Invalid INVENTORY_COUNT={count}")));
    }
    for _ in 0..count {
        let item = r.refid_raw()?;
        let n = r.i32()?;
        if keep {
            stacks.push((item, n));
        }
        let lists = r.vsval()?;
        if lists > 4096 {
            return Err(PErr::Abort(format!("Invalid INVENTORY_EXTRA_LISTS={lists}")));
        }
        for _ in 0..lists {
            let inner = r.vsval()?;
            if inner > 4096 {
                return Err(PErr::Abort(format!("Invalid EXTRA_DATA_COUNT (inventory)={inner}")));
            }
            for _ in 0..inner {
                parse_extra_data_element(r)?;
            }
        }
    }
    Ok(stacks)
}

/// walks an actor up to the end of its inventory; returns the inventory
fn walk_achr(r: &mut Reader, cf: u32, kind: Kind, animation: bool) -> Result<Vec<(u32, i32)>, PErr> {
    read_initial(r, initial_type(cf, kind))?;
    if has_bit(cf, 2) {
        read_vs_count_skip(r, 1)?;
    }
    r.read(8)?;
    if has_bit(cf, 0) {
        r.read(4)?;
        r.read(2)?;
    }
    if has_bit(cf, 7) {
        r.refid_raw()?;
    }
    if has_bit(cf, 4) {
        r.f32()?;
    }
    if ACHR_ACTOR_EXTRA_DATA_BITS.iter().any(|&b| has_bit(cf, b)) {
        let count = r.vsval()?;
        if count > 4096 {
            return Err(PErr::Abort(format!("Invalid EXTRA_DATA_COUNT={count}")));
        }
        for _ in 0..count {
            parse_extra_data_element(r)?;
        }
    }
    let mut stacks = Vec::new();
    if has_bit(cf, 5) || has_bit(cf, 27) {
        stacks = decode_inventory(r, !animation)?;
    }
    if animation && has_bit(cf, 28) {
        read_vs_count_skip(r, 1)?;
    }
    Ok(stacks)
}

/// spells of an actor, and whether they were read cleanly
fn parse_achr_actor_spells(payload: &[u8], cf: u32, kind: Kind) -> (Vec<u32>, bool) {
    let mut r = Reader::new(payload);
    match walk_achr(&mut r, cf, kind, true) {
        Ok(_) => (find_actor_spells_raw(&payload[r.pos..]), true),
        Err(_) => (Vec::new(), false),
    }
}

fn parse_npc_base_spells(payload: &[u8], cf: u32) -> Vec<u32> {
    let mut r = Reader::new(payload);
    let res = (|| -> Result<Vec<u32>, PErr> {
        if has_bit(cf, 0) {
            r.read(6)?;
        }
        if has_bit(cf, 1) {
            r.u32()?;
            for _ in 0..8 {
                r.u16()?;
            }
            r.i16()?;
            r.u16()?;
        }
        if has_bit(cf, 6) {
            let count = r.vsval()?;
            if count > 4096 {
                return Err(PErr::Abort(format!("Invalid FACTIONS_COUNT={count}")));
            }
            for _ in 0..count {
                r.refid_raw()?;
                r.i8()?;
            }
        }
        if has_bit(cf, 4) {
            let mut lists: [Vec<u32>; 3] = [Vec::new(), Vec::new(), Vec::new()];
            for (i, key) in ["spells", "levelled_spells", "shouts"].iter().enumerate() {
                let count = r.vsval()?;
                if count > 4096 {
                    return Err(PErr::Abort(format!("Invalid SPELLLIST_COUNT={count} ({key})")));
                }
                for _ in 0..count {
                    lists[i].push(r.refid_raw()?);
                }
            }
            return Ok(std::mem::take(&mut lists[0]));
        }
        Ok(Vec::new())
    })();
    res.unwrap_or_default()
}

// --- perks
fn vsval_at(d: &[u8], p: usize) -> Option<(u32, usize)> {
    if p >= d.len() {
        return None;
    }
    let b0 = d[p] as u32;
    let size = b0 & 3;
    let need = if size == 0 { 1 } else if size == 1 { 2 } else { 3 };
    if p + need > d.len() {
        return None;
    }
    let raw = match size {
        0 => b0,
        1 => b0 | (d[p + 1] as u32) << 8,
        _ => b0 | (d[p + 1] as u32) << 8 | (d[p + 2] as u32) << 16,
    };
    Some((raw >> 2, p + need))
}

fn refid_ok(raw: u32) -> bool {
    (raw & 0x3F_FFFF) != 0 && ((raw >> 22) & 3) != 3
}

fn rid(d: &[u8], p: usize) -> u32 {
    (d[p] as u32) << 16 | (d[p + 1] as u32) << 8 | d[p + 2] as u32
}

fn read_perk_block(d: &[u8], at: usize) -> Option<Vec<u32>> {
    let (n, mut p) = vsval_at(d, at)?;
    if !(PERK_BLOCK_MIN_A..=PERK_BLOCK_MAX_A).contains(&n) || p + 4 * n as usize > d.len() {
        return None;
    }
    let mut a = Vec::with_capacity(n as usize);
    let mut seen = HashSet::with_capacity(n as usize);
    for _ in 0..n {
        let raw = rid(d, p);
        if !refid_ok(raw) || !seen.insert(raw) {
            return None;
        }
        a.push(raw);
        p += 4;
    }
    let (m, mut p) = vsval_at(d, p)?;
    if m < 1 || m > n || p + 3 * m as usize > d.len() {
        return None;
    }
    for _ in 0..m {
        if !seen.contains(&rid(d, p)) {
            return None;
        }
        p += 3;
    }
    let (k, mut p) = vsval_at(d, p)?;
    if k > n || p + 7 * k as usize > d.len() {
        return None;
    }
    for _ in 0..k {
        if !seen.contains(&rid(d, p)) {
            return None;
        }
        p += 7;
    }
    Some(a)
}

fn find_perk_block(payload: &[u8]) -> Vec<Vec<u32>> {
    (0..payload.len()).filter_map(|i| read_perk_block(payload, i)).collect()
}

// --- collectibles / books
struct CollParsed {
    cell: Option<u32>,
    base: Option<u32>,
    form_flags: Option<u32>,
    extra_types: Vec<u8>,
    stacks: Vec<(u32, i32)>,
}

fn coll_parse_refr(payload: &[u8], cf: u32, kind: Kind, extra_bits: &[u32]) -> Result<CollParsed, PErr> {
    let mut r = Reader::new(payload);
    let (cell, mut base) = read_initial(&mut r, initial_type(cf, kind))?;
    if has_bit(cf, 2) {
        read_vs_count_skip(&mut r, 1)?;
    }
    let mut form_flags = None;
    if has_bit(cf, 0) {
        form_flags = Some(r.u32()?);
        r.read(2)?;
    }
    if has_bit(cf, 7) {
        base = Some(r.refid_raw()?);
    }
    if has_bit(cf, 4) {
        r.f32()?;
    }
    let mut extra_types = Vec::new();
    if extra_bits.iter().any(|&b| has_bit(cf, b)) {
        let c = r.vsval()?;
        if c > 4096 {
            return Err(PErr::Abort(format!("EXTRA_DATA_COUNT={c}")));
        }
        for _ in 0..c {
            // past the end: treated as the end of the data
            let t = *payload.get(r.pos).ok_or_else(|| PErr::Eof("index out of range".into()))?;
            extra_types.push(t);
            parse_extra_data_element(&mut r)?;
        }
    }
    let mut stacks = Vec::new();
    if has_bit(cf, 5) || has_bit(cf, 27) {
        stacks = decode_inventory(&mut r, true)?;
    }
    Ok(CollParsed { cell, base, form_flags, extra_types, stacks })
}

fn coll_parse_achr_inventory(payload: &[u8], cf: u32, kind: Kind) -> Result<Vec<(u32, i32)>, PErr> {
    let mut r = Reader::new(payload);
    walk_achr(&mut r, cf, kind, false)
}

struct CollRow<'a> {
    row: &'a Row,
    bases: Vec<(String, i64)>,
    prefs: Vec<(String, i64)>,
}

fn coll_key(s: &str) -> Result<(String, i64), String> {
    let parts: Vec<&str> = s.split(':').collect();
    if parts.len() != 2 {
        return Err(format!("bad Plugin:LocalID {s:?}"));
    }
    Ok((parts[0].trim().to_lowercase(), py_int16(parts[1].trim())?))
}

fn load_collectibles_tracker(rows: &[Row]) -> Result<Vec<CollRow<'_>>, String> {
    let mut out = Vec::new();
    for r in rows {
        let mut bases = Vec::new();
        for x in r.req("BaseKeys")?.split('|') {
            if !x.trim().is_empty() {
                bases.push(coll_key(x)?);
            }
        }
        let mut prefs = Vec::new();
        for x in r.req("PersistentRefs")?.split('|') {
            if !x.trim().is_empty() {
                prefs.push(coll_key(x)?);
            }
        }
        out.push(CollRow { row: r, bases, prefs });
    }
    Ok(out)
}

#[derive(Clone)]
struct Holder {
    kind: String,
    house: String,
}

fn load_collectibles_houses(rows: &[Row]) -> Result<(PKMap<String>, PKMap<Holder>), String> {
    let mut cells = PKMap::new();
    let mut holders = PKMap::new();
    for r in rows {
        let p = r.req("Plugin")?.trim().to_lowercase();
        let l = py_int16(r.req("LocalID")?.trim())?;
        if r.req("Kind")? == "CELL" {
            cells.insert(&p, l, r.req("House")?.to_string());
        } else {
            holders.insert(&p, l, Holder { kind: r.req("Kind")?.to_string(), house: r.req("House")?.to_string() });
        }
    }
    Ok((cells, holders))
}

/// collectibles stored in the player's homes
fn stored_items_scan(
    rows: &[CollRow],
    cells: &PKMap<String>,
    holders: &PKMap<Holder>,
    refr: &[ChangeForm],
    achr: &[ChangeForm],
    pl: &Plugins,
) -> (PKMap<Vec<(String, i64)>>, bool) {
    let mut base_keys = PKSet::new();
    let mut pref_to_base: PKMap<(String, i64)> = PKMap::new();
    for row in rows {
        for (p, l) in &row.bases {
            base_keys.add(p, *l);
        }
        for (p, l) in &row.prefs {
            if let Some(b) = row.bases.first() {
                pref_to_base.insert(p, *l, b.clone());
            }
        }
    }
    let mut found: PKMap<Vec<(String, i64)>> = PKMap::new();
    let mut unknown = false;
    let add_hit = |found: &mut PKMap<Vec<(String, i64)>>, p: &str, l: i64, house: &str, n: i64| {
        if let Some(v) = found.get_mut(p, l) {
            v.push((house.to_string(), n));
        } else {
            found.insert(p, l, vec![(house.to_string(), n)]);
        }
    };

    for cf in refr {
        let (p_, l_, k_) = pl.resolve_lc(cf.refid);
        let holder = holders.get(p_, l_);
        let is_holder = holder.map(|h| h.kind == "CONTAINER").unwrap_or(false);
        let is_pref = pref_to_base.contains(p_, l_);
        if !(is_holder || is_pref || k_ == Kind::Created) {
            continue;
        }
        let payload = match cf.payload() {
            Ok(x) => x,
            Err(_) => {
                if is_holder || is_pref {
                    unknown = true;
                }
                continue;
            }
        };
        let mut parsed = None;
        for bits in [COLL_REFR_EXTRA_BITS_A, COLL_REFR_EXTRA_BITS_B] {
            if let Ok(x) = coll_parse_refr(&payload, cf.change_flags, k_, bits) {
                parsed = Some(x);
                break;
            }
        }
        let parsed = match parsed {
            Some(x) => x,
            None => {
                if is_holder || is_pref {
                    unknown = true;
                    continue;
                }
                if k_ != Kind::Created {
                    continue;
                }
                let mut r = Reader::new(&payload);
                match read_initial(&mut r, initial_type(cf.change_flags, k_)) {
                    Ok((cell, base)) => CollParsed { cell, base, form_flags: None, extra_types: Vec::new(), stacks: Vec::new() },
                    Err(_) => continue,
                }
            }
        };
        let house = parsed.cell.and_then(|c| {
            let (cp, cl, _) = pl.resolve_lc(c);
            cells.get(cp, cl).cloned()
        })
        .filter(|h| !h.is_empty()); // empty name = no home
        if k_ == Kind::Created {
            if let (Some(h), Some(b)) = (&house, parsed.base) {
                let (bp, bl, _) = pl.resolve_lc(b);
                if base_keys.contains(bp, bl) {
                    add_hit(&mut found, bp, bl, h, 1);
                }
            }
        }
        if is_pref {
            if let Some(h) = &house {
                let gone = parsed.form_flags.map(|f| f & COLL_FORM_FLAG_DELETED != 0).unwrap_or(false)
                    || parsed.extra_types.contains(&COLL_EXTRA_NOT_IN_WORLD);
                if !gone {
                    let (bp, bl) = pref_to_base.get(p_, l_).unwrap().clone();
                    add_hit(&mut found, &bp, bl, h, 1);
                }
            }
        }
        if is_holder {
            let hh = holder.unwrap().house.clone();
            for (srid, n) in &parsed.stacks {
                let (sp, sl, _) = pl.resolve_lc(*srid);
                if base_keys.contains(sp, sl) && *n > 0 {
                    add_hit(&mut found, sp, sl, &hh, *n as i64);
                }
            }
        }
    }

    for cf in achr {
        let (p_, l_, k_) = pl.resolve_lc(cf.refid);
        let holder = match holders.get(p_, l_) {
            Some(h) if h.kind == "MANNEQUIN" => h.clone(),
            _ => continue,
        };
        let stacks = match cf.payload() {
            Ok(payload) => match coll_parse_achr_inventory(&payload, cf.change_flags, k_) {
                Ok(s) => s,
                Err(_) => {
                    unknown = true;
                    continue;
                }
            },
            Err(_) => {
                unknown = true;
                continue;
            }
        };
        for (srid, n) in stacks {
            let (sp, sl, _) = pl.resolve_lc(srid);
            if base_keys.contains(sp, sl) && n > 0 {
                add_hit(&mut found, sp, sl, &holder.house, n as i64);
            }
        }
    }
    (found, unknown)
}

// ---------------------------------------------------------------------------
// calendar
fn read_calendar(body: &[u8], table1_offset: u32, table1_count: u32, starting_offset: usize) -> Option<[f64; 5]> {
    let start = (table1_offset as i64) - starting_offset as i64;
    if start < 0 {
        return None;
    }
    let mut t = Reader::new(body);
    t.pos = start as usize;
    let mut block = None;
    for _ in 0..table1_count {
        let gtype = t.u32().ok()?;
        let glen = t.u32().ok()? as usize;
        if gtype == 3 {
            let a = t.pos.min(body.len());
            let b = t.pos.saturating_add(glen).min(body.len());
            block = Some(&body[a..b]);
            break;
        }
        t.pos = t.pos.saturating_add(glen);
    }
    let block = block?;
    let mut r = Reader::new(block);
    let count = r.vsval().ok()?;
    let mut found: [Option<f32>; 5] = [None; 5];
    for _ in 0..count {
        let raw = r.refid_raw().ok()?;
        let value = r.f32().ok()?;
        if raw >> 22 == 1 {
            let v = raw & 0x3F_FFFF;
            if (0x35..=0x39).contains(&v) {
                found[(v - 0x35) as usize] = Some(value);
            }
        }
    }
    if r.pos != block.len() {
        return None;
    }
    let mut out = [0f64; 5];
    for i in 0..5 {
        out[i] = found[i]? as f64;
    }
    Some(out)
}

// ---------------------------------------------------------------------------
// tables
fn table<'t>(tables: &'t Tables, name: &str) -> Result<&'t [u8], String> {
    tables.get(name).map(|v| v.as_slice()).ok_or_else(|| format!("table {name} missing"))
}

fn read_table(tables: &Tables, name: &str, replace: bool) -> Result<Vec<Row>, String> {
    let text = decode_utf8_sig(table(tables, name)?, replace)?;
    Ok(dict_reader(&text))
}

struct QRow {
    order: String,
    key: String,
    candidates: Vec<(String, i64, String)>,
    overrides: HashMap<String, i64>,
    handle: bool,
}

fn load_quest_tracker(rows: &[Row]) -> Result<Vec<QRow>, String> {
    let mut out = Vec::new();
    for row in rows {
        let mut candidates = Vec::new();
        for entry in row.req("FormIDCandidates")?.split('|') {
            let entry = entry.trim();
            if entry.is_empty() {
                continue;
            }
            let (left, sub) = entry.rsplit_once('=').ok_or("not enough values to unpack")?;
            let (plugin, fid) = left.split_once(':').ok_or("not enough values to unpack")?;
            let local = py_int16(fid.trim())? & 0xFF_FFFF;
            candidates.push((plugin.trim().to_string(), local, sub.trim().to_string()));
        }
        let mut overrides = HashMap::new();
        for entry in row.req("OverrideMap")?.split('|') {
            let entry = entry.trim();
            if entry.is_empty() {
                continue;
            }
            let (sub, thr) = entry.rsplit_once(':').ok_or("not enough values to unpack")?;
            overrides.insert(sub.trim().to_string(), py_int10(thr.trim())?);
        }
        let cat = match row.get("Category") {
            Some(c) if !c.is_empty() => c,
            _ => "flag",
        }
        .trim()
        .to_lowercase();
        let handle = cat == "handle";
        if handle {
            candidates.clear();
            overrides.clear();
        } else if candidates.is_empty() {
            return Err(format!(
                "quests_tracker.csv: row Order={} ({}) has no FormIDCandidates",
                row.req("Order")?,
                row.req("Name")?
            ));
        }
        out.push(QRow {
            order: row.req("Order")?.to_string(),
            key: row.req("Key")?.to_string(),
            candidates,
            overrides,
            handle,
        });
    }
    Ok(out)
}

struct LocRow {
    order: String,
    markers: Vec<(String, i64)>,
}

fn load_location_tracker(rows: &[Row]) -> Result<Vec<LocRow>, String> {
    let mut out = Vec::new();
    for row in rows {
        let mut markers = Vec::new();
        for entry in row.req("MarkerFormIDs")?.split('|') {
            let entry = entry.trim();
            if let Some((p, f)) = entry.split_once(':') {
                markers.push((p.trim().to_string(), py_int16(f.trim())? & 0xFF_FFFF));
            }
        }
        if markers.is_empty() {
            return Err(format!(
                "locations_tracker.csv: row {} ({}) has no MarkerFormIDs",
                row.req("Order")?,
                row.req("Name")?
            ));
        }
        out.push(LocRow { order: row.req("Order")?.trim().to_string(), markers });
    }
    Ok(out)
}

fn load_always_visible(rows: &[Row]) -> PKMap<bool> {
    let mut result: PKMap<bool> = PKMap::new();
    for row in rows {
        let fid = row.get("FormID").unwrap_or("").trim();
        let plugin = row.get("Plugin").unwrap_or("").trim();
        if fid.is_empty() || plugin.is_empty() {
            continue;
        }
        let local = match py_int16(fid) {
            Ok(v) => v & 0xFF_FFFF,
            Err(_) => continue,
        };
        let av = if row.has("CanTravelTo") {
            row.get("CanTravelTo").unwrap_or("").trim() == "1"
        } else {
            row.get("AlwaysVisible").unwrap_or("").trim() == "1"
        };
        if let Some(true) = result.get(plugin, local) {
            continue;
        }
        result.insert(plugin, local, av);
    }
    result
}

/// table order -> row key
fn row_key_map(cat: &str, pairs: Vec<(String, Option<String>)>) -> Result<Vec<(String, String)>, String> {
    let mut out: Vec<(String, String)> = Vec::new();
    for (order, key) in pairs {
        let order = order.trim().to_string();
        let key = key.unwrap_or_default().trim().to_string();
        if key.is_empty() {
            return Err(format!("{cat}: row Order={order} has no key"));
        }
        if out.iter().any(|(_, k)| *k == key) {
            return Err(format!("{cat}: key {key:?} (Order={order}) is not unique"));
        }
        if let Some(e) = out.iter_mut().find(|(o, _)| *o == order) {
            e.1 = key;
        } else {
            out.push((order, key));
        }
    }
    Ok(out)
}

// ---------------------------------------------------------------------------
// tracker.json assembly (write_tracker_json)

/// one tracker row with its result
struct Final {
    order: String,
    status: &'static str,
    known: Option<String>,    // ingredients
    progress: Option<String>, // collectibles
}

fn fin(order: &str, status: &'static str) -> Final {
    Final { order: order.to_string(), status, known: None, progress: None }
}

/// keys keep the order they were first set in
struct ODict(Vec<(String, String)>);
impl ODict {
    fn set(&mut self, k: &str, v: String) {
        if let Some(e) = self.0.iter_mut().find(|(kk, _)| kk == k) {
            e.1 = v;
        } else {
            self.0.push((k.to_string(), v));
        }
    }
}

fn json_list(out: &mut String, list: &[String]) {
    out.push('[');
    for (i, s) in list.iter().enumerate() {
        if i > 0 {
            out.push(',');
        }
        pyjson::string(out, s);
    }
    out.push(']');
}

fn category_json(cat: &str, rows: &[Final], keys: &[(String, String)]) -> Result<String, String> {
    const DONE: [&str; 5] = ["DONE (flag)", "DONE (stage override)", "DISCOVERED", "LEARNED", "OBTAINED"];
    let mut done: Vec<String> = Vec::new();
    let mut unknown: Vec<String> = Vec::new();
    let mut failed: Option<Vec<String>> = None;
    let mut known = ODict(Vec::new());
    let mut counts: Option<ODict> = None;
    for r in rows {
        let o = r.order.trim();
        let key = keys
            .iter()
            .find(|(ord, _)| ord == o)
            .map(|(_, k)| k.clone())
            .ok_or_else(|| format!("KeyError: {o:?} ({cat})"))?;
        let st = r.status.trim();
        if st == "UNKNOWN" {
            unknown.push(key.clone());
        }
        if cat == "ingredients" {
            if let Some(k) = &r.known {
                if k.contains('Y') {
                    known.set(&key, k.clone());
                }
            }
            continue;
        }
        if DONE.contains(&st) {
            done.push(key.clone());
        }
        if cat == "quests" && st == "FAILED" {
            failed.get_or_insert_with(Vec::new).push(key.clone());
        }
        if cat == "collectibles" {
            if let Some(p) = r.progress.as_ref().filter(|p| !p.is_empty()) {
                let have = py_int10(p.split('/').next().unwrap())?;
                counts.get_or_insert_with(|| ODict(Vec::new())).set(&key, have.to_string());
            }
        }
    }
    let mut s = String::from("{");
    if cat == "ingredients" {
        s.push_str("\"known\":{");
        for (i, (k, v)) in known.0.iter().enumerate() {
            if i > 0 {
                s.push(',');
            }
            pyjson::string(&mut s, k);
            s.push(':');
            pyjson::string(&mut s, v);
        }
        s.push_str("},\"unknown\":");
        json_list(&mut s, &unknown);
    } else {
        s.push_str("\"done\":");
        json_list(&mut s, &done);
        s.push_str(",\"unknown\":");
        json_list(&mut s, &unknown);
        if let Some(f) = &failed {
            s.push_str(",\"failed\":");
            json_list(&mut s, f);
        }
        if let Some(c) = &counts {
            s.push_str(",\"counts\":{");
            for (i, (k, v)) in c.0.iter().enumerate() {
                if i > 0 {
                    s.push(',');
                }
                pyjson::string(&mut s, k);
                s.push(':');
                s.push_str(v);
            }
            s.push('}');
        }
    }
    s.push('}');
    Ok(s)
}

// ---------------------------------------------------------------------------
// main

/// Reads a save and returns the tracker.json text.
/// `file_name` is the save's file name; `progress` gets each stage as it starts.
pub fn parse_save(
    raw: &[u8],
    file_name: &str,
    tables: &Tables,
    progress: &mut dyn FnMut(usize),
) -> Result<String, ParseError> {
    let mut stage = 0usize;
    let fail = |stage: usize, m: String| ParseError { stage, message: m };
    macro_rules! st {
        ($i:expr) => {{
            stage = $i;
            progress(stage);
        }};
    }
    macro_rules! tryst {
        ($e:expr) => {
            $e.map_err(|m: String| fail(stage, m))?
        };
    }

    // tables first
    let quest_rows_raw = tryst!(read_table(tables, "quests_tracker.csv", false));
    let quest_tracker = tryst!(load_quest_tracker(&quest_rows_raw));
    let mut quest_filter = PKSet::new();
    for q in &quest_tracker {
        for (p, l, _) in &q.candidates {
            quest_filter.add(p, *l);
        }
    }
    let loc_rows_raw = tryst!(read_table(tables, "locations_tracker.csv", false));
    let loc_tracker = tryst!(load_location_tracker(&loc_rows_raw));
    let mut marker_filter = PKSet::new();
    for l in &loc_tracker {
        for (p, id) in &l.markers {
            marker_filter.add(p, *id);
        }
    }
    let av_rows = tryst!(read_table(tables, "MapMarkerExport.csv", true));
    let always_visible = load_always_visible(&av_rows);

    st!(0);
    let mut f = Reader::new(raw);
    let header = tryst!(parse_header(&mut f));
    let starting_offset = header.starting_offset;

    st!(1);
    let body = tryst!(decompress_body(&mut f, header.comp_type));
    let mut b = Reader::new(&body);

    st!(2);
    let e = |x: Eof| x.0;
    let form_version = tryst!(b.u8().map_err(e));
    let supports_esl = form_version >= 78;
    let _plugin_info_size = tryst!(b.u32().map_err(e));
    let number_of_full = tryst!(b.u8().map_err(e));
    let mut full = Vec::new();
    for _ in 0..number_of_full {
        full.push(tryst!(b.wstring().map_err(e)));
    }
    let mut lite = Vec::new();
    if supports_esl {
        let n = tryst!(b.u16().map_err(e));
        for _ in 0..n {
            lite.push(tryst!(b.wstring().map_err(e)));
        }
    }

    st!(3);
    let mut flt = [0u32; 10];
    for v in flt.iter_mut() {
        *v = tryst!(b.u32().map_err(e));
    }
    tryst!(b.read(15 * 4).map(|_| ()).map_err(e));
    let [formid_array_count_offset, _unknown_table3_offset, table1_offset, _table2_offset, changeforms_offset, _table3_offset, table1_count, _table2_count, _table3_count, changeform_count] = flt;

    let calendar = read_calendar(&body, table1_offset, table1_count, starting_offset);

    let fpos = formid_array_count_offset as i64 - starting_offset as i64;
    if fpos < 0 {
        return Err(fail(stage, format!("FormID array offset {fpos} is before the file body")));
    }
    b.pos = fpos as usize;
    let formid_count = tryst!(b.u32().map_err(e));
    let mut form_ids = Vec::with_capacity(formid_count as usize);
    for _ in 0..formid_count {
        form_ids.push(tryst!(b.u32().map_err(e)));
    }
    let body_pos = changeforms_offset as i64 - starting_offset as i64;
    if !(0..=body.len() as i64).contains(&body_pos) {
        return Err(fail(
            stage,
            format!(
                "changeFormsOffset ({changeforms_offset}) - startingOffset ({starting_offset}) = {body_pos}, \
                 which is outside the file body (0..{}).",
                body.len()
            ),
        ));
    }
    b.pos = body_pos as usize;

    let pl = Plugins {
        full_lc: full.iter().map(|s| s.to_lowercase()).collect(),
        lite_lc: lite.iter().map(|s| s.to_lowercase()).collect(),
        full,
        lite,
        form_ids,
    };

    let mut quest_forms = Vec::new();
    let mut location_forms = Vec::new();
    let mut shout_forms = Vec::new();
    let mut ench_forms = Vec::new();
    let mut ingr_forms = Vec::new();
    let mut achr_forms: Vec<ChangeForm> = Vec::new();
    let mut achr_player: Option<(usize, Kind)> = None; // index into achr_forms
    let mut npc_player: Option<ChangeForm> = None;

    for _ in 0..changeform_count {
        let rec = (|| -> Result<(ChangeForm, u8), Eof> {
            let refid = b.refid_raw()?;
            let change_flags = b.u32()?;
            let typefield = b.u8()?;
            let _version = b.i8()?;
            let type_code = typefield & 0x3F;
            let (length1, length2) = match typefield >> 6 {
                0 => (b.u8()? as u32, b.u8()? as u32),
                1 => (b.u16()? as u32, b.u16()? as u32),
                _ => (b.u32()?, b.u32()?),
            };
            let data = b.read(length1 as usize)?;
            Ok((ChangeForm { refid, change_flags, length2, data }, type_code))
        })();
        let (cf, type_code) = match rec {
            Ok(x) => x,
            Err(_) => break,
        };
        match type_code {
            QUST_TYPE_CODE => quest_forms.push(cf),
            REFR_TYPE_CODE => location_forms.push(cf),
            WOOP_TYPE_CODE => shout_forms.push(cf),
            INGR_TYPE_CODE => ingr_forms.push(cf),
            ENCH_TYPE_CODE => ench_forms.push(cf),
            ACHR_TYPE_CODE => {
                let (p, l, k) = pl.resolve(cf.refid);
                if p.is_some() && l == PLAYER_LOCAL_ID && !pl.full.is_empty() && p == Some(pl.full[0].as_str()) {
                    achr_player = Some((achr_forms.len(), k));
                }
                achr_forms.push(cf);
            }
            NPC_TYPE_CODE => {
                let (p, l, _) = pl.resolve(cf.refid);
                if p.is_some() && l == PLAYER_BASE_LOCAL_ID && !pl.full.is_empty() && p == Some(pl.full[0].as_str()) {
                    npc_player = Some(cf);
                }
            }
            _ => {}
        }
    }

    // ------------------------------------------------------------------ QUST
    st!(4);
    struct QStat {
        bit1: Option<bool>,
        bit6: Option<bool>,
        max_reached: Option<i16>,
    }
    let mut qstat: PKMap<QStat> = PKMap::new();
    for cf in &quest_forms {
        let (plugin, local, _) = pl.resolve(cf.refid);
        let Some(plugin) = plugin else { continue };
        if !quest_filter.contains(plugin, local) {
            continue;
        }
        let Ok(payload) = cf.payload() else { continue };
        let Some(res) = parse_qust_changeform(&payload, cf.change_flags) else { continue };
        let reached = res.stage_status.iter().filter(|(_, s)| *s == 1).map(|(n, _)| *n).max();
        qstat.insert(
            plugin,
            local,
            QStat {
                bit1: res.quest_flags.map(|f| (f >> 1) & 1 == 1),
                bit6: res.quest_flags.map(|f| (f >> 6) & 1 == 1),
                max_reached: reached,
            },
        );
    }
    let mut quest_final = Vec::new();
    for qt in &quest_tracker {
        if qt.handle {
            quest_final.push(fin(&qt.order, "HANDLE"));
            continue;
        }
        let mut statuses = Vec::new();
        for (p, l, sub) in &qt.candidates {
            let s = match qstat.get(p, *l) {
                None => "NOT_IN_SAVE",
                Some(st) => {
                    if st.bit6 == Some(true) {
                        "FAILED"
                    } else if st.bit1 == Some(true) {
                        "DONE (flag)"
                    } else if matches!((qt.overrides.get(sub), st.max_reached), (Some(t), Some(m)) if m as i64 >= *t) {
                        "DONE (stage override)"
                    } else if st.bit1 == Some(false) {
                        "NOT DONE"
                    } else {
                        "UNKNOWN"
                    }
                }
            };
            statuses.push(s);
        }
        let prio = ["DONE (flag)", "DONE (stage override)", "FAILED", "NOT DONE", "UNKNOWN", "NOT_IN_SAVE"];
        let final_status = prio.iter().find(|p| statuses.contains(p)).copied().unwrap_or("NOT_IN_SAVE");
        quest_final.push(fin(&qt.order, final_status));
    }

    // ------------------------------------------------------------- locations
    st!(5);
    let mut per_marker: PKMap<LocStatus> = PKMap::new();
    for cf in &location_forms {
        let (plugin, local, kind) = pl.resolve(cf.refid);
        let Some(plugin) = plugin else { continue };
        if !marker_filter.contains(plugin, local) {
            continue;
        }
        let Ok(payload) = cf.payload() else { continue };
        let st = parse_location_marker_changeform(&payload, cf.change_flags, kind);
        per_marker.insert(plugin, local, st);
    }
    let mut loc_final = Vec::new();
    for loc in &loc_tracker {
        let mut effs = Vec::new();
        for (p, l) in &loc.markers {
            let eff = match per_marker.get(p, *l) {
                Some(LocStatus::Discovered) => LocStatus::Discovered,
                Some(LocStatus::NotDiscovered) => LocStatus::NotDiscovered,
                Some(LocStatus::Unknown) => LocStatus::Unknown,
                _ => match always_visible.get(p, *l) {
                    Some(true) => LocStatus::Discovered,
                    Some(false) => LocStatus::NotDiscovered,
                    None => LocStatus::Unknown,
                },
            };
            effs.push(eff);
        }
        let s = if effs.contains(&LocStatus::Discovered) {
            "DISCOVERED"
        } else if effs.contains(&LocStatus::Unknown) {
            "UNKNOWN"
        } else {
            "NOT_DISCOVERED"
        };
        loc_final.push(fin(&loc.order, s));
    }

    // ---------------------------------------------------------------- spells
    st!(6);
    let spells_rows = tryst!(read_table(tables, "spells_tracker.csv", false));
    let mut learned = PKSet::new();
    let mut spells_list_ok = false;
    if let Some((idx, kind)) = achr_player {
        let cf = &achr_forms[idx];
        if let Ok(payload) = cf.payload() {
            let (spells, ok) = parse_achr_actor_spells(&payload, cf.change_flags, kind);
            spells_list_ok = ok && !spells.is_empty();
            for raw in spells {
                let (p, l, _) = pl.resolve_lc(raw);
                if pl.resolve(raw).0.is_none() {
                    continue;
                }
                learned.add(p, l);
            }
        }
    }
    if let Some(cf) = &npc_player {
        if let Ok(payload) = cf.payload() {
            for raw in parse_npc_base_spells(&payload, cf.change_flags) {
                if pl.resolve(raw).0.is_none() {
                    continue;
                }
                let (p, l, _) = pl.resolve_lc(raw);
                learned.add(p, l);
            }
        }
    }
    let simple_final = |rows: &[Row], set: &PKSet, yes: &'static str, no: &'static str| -> Result<Vec<Final>, String> {
        let mut out = Vec::new();
        for row in rows {
            let p = row.req("Plugin")?.trim().to_lowercase();
            let l = py_int16(row.req("LocalID")?.trim())?;
            out.push(fin(row.req("Order")?, if set.contains(&p, l) { yes } else { no }));
        }
        Ok(out)
    };
    let spells_final = tryst!(simple_final(&spells_rows, &learned, "LEARNED", "NOT_LEARNED"));

    // ---------------------------------------------------------------- shouts
    st!(7);
    let shouts_rows = tryst!(read_table(tables, "shouts_tracker.csv", false));
    let mut shout_keys = PKSet::new();
    for cf in &shout_forms {
        if pl.resolve(cf.refid).0.is_none() {
            continue;
        }
        let (p, l, _) = pl.resolve_lc(cf.refid);
        shout_keys.add(p, l);
    }
    let shouts_final = tryst!(simple_final(&shouts_rows, &shout_keys, "LEARNED", "NOT_LEARNED"));

    // ------------------------------------------------------------ enchanting
    st!(8);
    let ench_rows = tryst!(read_table(tables, "enchanting_tracker.csv", false));
    let mut ench_keys = PKSet::new();
    for cf in &ench_forms {
        if pl.resolve(cf.refid).0.is_none() {
            continue;
        }
        let (p, l, _) = pl.resolve_lc(cf.refid);
        ench_keys.add(p, l);
    }
    let ench_final = tryst!(simple_final(&ench_rows, &ench_keys, "LEARNED", "NOT_LEARNED"));

    // ----------------------------------------------------------- ingredients
    st!(9);
    let ingr_rows = tryst!(read_table(tables, "ingredients_tracker.csv", false));
    let mut masks: PKMap<Option<u32>> = PKMap::new();
    for cf in &ingr_forms {
        if pl.resolve(cf.refid).0.is_none() {
            continue;
        }
        let (p, l, _) = pl.resolve_lc(cf.refid);
        let mut mask = None;
        if let Ok(payload) = cf.payload() {
            if cf.change_flags == INGR_OBSERVED_FLAGS && payload.len() == 4 {
                let v = u32::from_le_bytes([payload[0], payload[1], payload[2], payload[3]]);
                if v <= 0x0F {
                    mask = Some(v);
                }
            }
        }
        masks.insert(p, l, mask);
    }
    let ingr_final = tryst!((|| -> Result<Vec<Final>, String> {
        let mut out = Vec::new();
        for row in &ingr_rows {
            let p = row.req("Plugin")?.trim().to_lowercase();
            let l = py_int16(row.req("LocalID")?.trim())?;
            let mask = match masks.get(&p, l) {
                Some(m) => *m,
                None => Some(0),
            };
            let (status, known) = match mask {
                None => ("UNKNOWN", "????".to_string()),
                Some(m) => {
                    let bits: String = (0..4).map(|n| if m & (1 << n) != 0 { 'Y' } else { 'N' }).collect();
                    let k = bits.matches('Y').count();
                    (if k == 4 { "DISCOVERED" } else if k > 0 { "PARTIAL" } else { "NOT DISCOVERED" }, bits)
                }
            };
            // AltCandidates are only checked to be valid
            for a in row.get("AltCandidates").unwrap_or("").split('|').filter(|a| !a.is_empty()) {
                let (_, rest) = a.split_once(':').ok_or("not enough values to unpack")?;
                py_int16(rest.split('=').next().unwrap())?;
            }
            let mut f = fin(row.req("Order")?, status);
            f.known = Some(known);
            out.push(f);
        }
        Ok(out)
    })());

    // ----------------------------------------------------------------- perks
    st!(10);
    let perks_rows = tryst!(read_table(tables, "perks_tracker.csv", false));
    let mut perk_keys: Option<PKSet> = None;
    if let Some((idx, _)) = achr_player {
        if let Ok(payload) = achr_forms[idx].payload() {
            let hits = find_perk_block(&payload);
            if hits.len() == 1 {
                let mut set = PKSet::new();
                for raw in &hits[0] {
                    if pl.resolve(*raw).0.is_none() {
                        continue;
                    }
                    let (p, l, _) = pl.resolve_lc(*raw);
                    set.add(p, l);
                }
                perk_keys = Some(set);
            }
        }
    }
    let perks_final = tryst!((|| -> Result<Vec<Final>, String> {
        let mut out = Vec::new();
        for row in &perks_rows {
            let p = row.req("Plugin")?.trim().to_lowercase();
            let l = py_int16(row.req("LocalID")?.trim())?;
            let source = row.req("Source")?.trim().to_uppercase();
            let status = if source == "SPEL" {
                if !spells_list_ok {
                    "UNKNOWN"
                } else if learned.contains(&p, l) {
                    "OBTAINED"
                } else {
                    "NOT OBTAINED"
                }
            } else {
                match &perk_keys {
                    None => "UNKNOWN",
                    Some(s) if s.contains(&p, l) => "OBTAINED",
                    Some(_) => "NOT OBTAINED",
                }
            };
            out.push(fin(row.req("Order")?, status));
        }
        Ok(out)
    })());

    // ---------------------------------------------------------- collectibles
    st!(11);
    let coll_rows_raw = tryst!(read_table(tables, "collectibles_tracker.csv", false));
    let coll_rows = tryst!(load_collectibles_tracker(&coll_rows_raw));
    let houses_rows = tryst!(read_table(tables, "collectibles_houses.csv", false));
    let (cells, holders) = tryst!(load_collectibles_houses(&houses_rows));
    let (found, unknown) = stored_items_scan(&coll_rows, &cells, &holders, &location_forms, &achr_forms, &pl);
    let coll_final = tryst!((|| -> Result<Vec<Final>, String> {
        let mut out = Vec::new();
        for row in &coll_rows {
            let per_base: Vec<&[(String, i64)]> = row
                .bases
                .iter()
                .map(|(p, l)| found.get(p, *l).map(|v| v.as_slice()).unwrap_or(&[]))
                .collect();
            let mode = row.row.req("Mode")?.trim().to_uppercase();
            let required = py_int10(row.row.req("Required")?)?;
            let (ok, progress) = if mode == "ALL" {
                let have = per_base.iter().filter(|v| !v.is_empty()).count();
                (have == row.bases.len(), format!("{}/{}", have, row.bases.len()))
            } else if mode == "COUNT" {
                let have: i64 = per_base.iter().flat_map(|v| v.iter()).map(|(_, n)| *n).sum();
                (have >= required, format!("{}/{}", have.min(required), required))
            } else {
                (per_base.iter().any(|v| !v.is_empty()), String::new())
            };
            let status = if ok {
                "OBTAINED"
            } else if unknown {
                "UNKNOWN"
            } else {
                "NOT OBTAINED"
            };
            let mut f = fin(row.row.req("Order")?, status);
            f.progress = Some(progress);
            out.push(f);
        }
        Ok(out)
    })());

    // ----------------------------------------------------------------- books
    st!(12);
    let book_rows_raw = tryst!(read_table(tables, "books_tracker.csv", false));
    let book_rows = tryst!(load_collectibles_tracker(&book_rows_raw));
    let (b_found, b_unknown) = stored_items_scan(&book_rows, &cells, &holders, &location_forms, &achr_forms, &pl);
    let books_final = tryst!((|| -> Result<Vec<Final>, String> {
        let mut out = Vec::new();
        for row in &book_rows {
            let any = row.bases.iter().any(|(p, l)| found_nonempty(&b_found, p, *l));
            let status = if any {
                "OBTAINED"
            } else if b_unknown {
                "UNKNOWN"
            } else {
                "NOT OBTAINED"
            };
            out.push(fin(row.row.req("Order")?, status));
        }
        Ok(out)
    })());

    // ----------------------------------------------------- tracker.json
    st!(13);
    let rk = |cat: &str, rows: &[Row], col: &str| -> Result<Vec<(String, String)>, String> {
        let mut pairs = Vec::new();
        for r in rows {
            pairs.push((r.req("Order")?.to_string(), r.get(col).map(|s| s.to_string())));
        }
        row_key_map(cat, pairs)
    };
    let keys_quests = tryst!(row_key_map(
        "quests",
        quest_tracker.iter().map(|q| (q.order.clone(), Some(q.key.clone()))).collect()
    ));
    let keys_locations = tryst!(row_key_map(
        "locations",
        loc_tracker
            .iter()
            .map(|l| (l.order.clone(), Some(format!("{}:{:06X}", l.markers[0].0, l.markers[0].1))))
            .collect()
    ));
    let keys_spells = tryst!(rk("spells", &spells_rows, "EditorID"));
    let keys_shouts = tryst!(rk("shouts", &shouts_rows, "EditorID"));
    let keys_ench = tryst!(rk("enchanting", &ench_rows, "EditorID"));
    let keys_ingr = tryst!(rk("ingredients", &ingr_rows, "EditorID"));
    let keys_perks = tryst!(rk("perks", &perks_rows, "EditorID"));
    let keys_coll = tryst!(rk("collectibles", &coll_rows_raw, "BaseEditorIDs"));
    let keys_books = tryst!(rk("books", &book_rows_raw, "BaseEditorIDs"));

    let mut cats: Vec<(&str, String)> = Vec::new();
    let mut add = |cat: &'static str, rows: &[Final], keys: &[(String, String)], present: bool| -> Result<(), String> {
        if present {
            cats.push((cat, category_json(cat, rows, keys)?));
        }
        Ok(())
    };
    tryst!(add("quests", &quest_final, &keys_quests, !quest_tracker.is_empty()));
    tryst!(add("locations", &loc_final, &keys_locations, !loc_tracker.is_empty()));
    tryst!(add("spells", &spells_final, &keys_spells, !spells_rows.is_empty()));
    tryst!(add("shouts", &shouts_final, &keys_shouts, !shouts_rows.is_empty()));
    tryst!(add("enchanting", &ench_final, &keys_ench, !ench_rows.is_empty()));
    tryst!(add("ingredients", &ingr_final, &keys_ingr, !ingr_rows.is_empty()));
    tryst!(add("perks", &perks_final, &keys_perks, !perks_rows.is_empty()));
    tryst!(add("collectibles", &coll_final, &keys_coll, !coll_rows.is_empty()));
    tryst!(add("books", &books_final, &keys_books, !book_rows.is_empty()));

    let xp = tryst!(pyjson::round_int(header.cur_xp as f64).ok_or_else(|| "cannot convert float NaN to integer".to_string()));
    let xp_max = tryst!(pyjson::round_int(header.needed_xp as f64).ok_or_else(|| "cannot convert float NaN to integer".to_string()));

    let mut o = String::with_capacity(64 * 1024);
    o.push_str("{\"format\":");
    pyjson::string(&mut o, TRACKER_JSON_FORMAT);
    o.push_str(",\"save\":{\"file\":");
    pyjson::string(&mut o, file_name);
    o.push_str(&format!(
        ",\"number\":{},\"version\":{},\"formVersion\":{}}}",
        header.save_number, header.version, form_version
    ));
    o.push_str(",\"player\":{\"name\":");
    pyjson::string(&mut o, &header.name);
    o.push_str(&format!(",\"level\":{},\"xp\":{},\"xpMax\":{},\"race\":", header.level, xp, xp_max));
    pyjson::string(&mut o, &header.race_eid);
    o.push_str(&format!(",\"sex\":{},\"location\":", header.sex));
    pyjson::string(&mut o, &header.location);
    o.push_str(",\"playtime\":");
    pyjson::string(&mut o, &header.game_date);
    o.push_str(",\"calendar\":");
    o.push_str(&calendar_json(calendar));
    o.push_str("},\"plugins\":{\"full\":");
    json_list(&mut o, &pl.full);
    o.push_str(",\"light\":");
    json_list(&mut o, &pl.lite);
    o.push_str("},\"categories\":{");
    for (i, (cat, j)) in cats.iter().enumerate() {
        if i > 0 {
            o.push(',');
        }
        pyjson::string(&mut o, cat);
        o.push(':');
        o.push_str(j);
    }
    o.push_str("}}");
    Ok(o)
}

fn found_nonempty(found: &PKMap<Vec<(String, i64)>>, p: &str, l: i64) -> bool {
    found.get(p, l).map(|v| !v.is_empty()).unwrap_or(false)
}

/// in-game date and time; null if it cannot be read
fn calendar_json(cal: Option<[f64; 5]>) -> String {
    let Some(c) = cal else { return "null".into() };
    let mut ints = Vec::new();
    for v in &c[..3] {
        match pyjson::round_int(*v) {
            Some(s) => ints.push(s),
            None => return "null".into(),
        }
    }
    format!(
        "{{\"year\":{},\"month\":{},\"day\":{},\"hour\":{},\"daysPassed\":{}}}",
        ints[0],
        ints[1],
        ints[2],
        pyjson::float_repr(pyjson::round6(c[3])),
        pyjson::float_repr(pyjson::round6(c[4]))
    )
}
