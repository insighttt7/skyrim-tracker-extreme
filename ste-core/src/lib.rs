//! Skyrim Tracker Extreme save parser. Standard library only.

mod inflate;
mod lz4;
mod parse;
mod pycsv;
pub mod pyjson;
mod reader;

pub use parse::{parse_save, ParseError, Tables, CSV_ORDER, STAGE_NAMES, TRACKER_JSON_FORMAT};

pub fn zlib_decompress(data: &[u8]) -> Result<Vec<u8>, String> {
    inflate::zlib_decompress(data).map_err(|e| e.0.to_string())
}

pub fn lz4_decompress(data: &[u8], size: usize) -> Result<Vec<u8>, String> {
    lz4::decompress_block(data, size).map_err(|e| e.0)
}
