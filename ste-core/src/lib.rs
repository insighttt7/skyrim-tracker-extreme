//! Skyrim Tracker Extreme save parser. Standard library only.

mod inflate;
mod lz4;
mod parse;
mod pycsv;
mod pyjson;
mod reader;

pub use parse::{parse_save, ParseError, Tables, CSV_ORDER, STAGE_NAMES};
