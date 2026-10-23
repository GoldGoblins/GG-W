//! Held-item placement adapted from GgEngine entities/equipment/resolve.rs (MIT/Apache-2.0).
//! Display ids are resolved by the original catalog; template inventory/sheath types
//! belong to the caller. No server-only item fields are guessed from a display id.
pub fn placement(slot: usize, inv_type: u32, item_sheath: u8, unit_sheath: u8) -> Option<u16> {
    match slot {
        2 => (unit_sheath == 2).then_some(if inv_type == 15 {2} else {1}),
        0 | 1 if unit_sheath == 1 => Some(match (slot, inv_type == 14) {
            (0, _) => 1, (_, true) => 0, (_, false) => 2,
        }),
        0 | 1 => match item_sheath {
            1 => Some(if slot == 0 {26} else {27}),
            2 => Some(if slot == 0 {30} else {31}),
            3 => Some(if slot == 0 {32} else {33}),
            4 => Some(28),
            _ => None,
        },
        _ => None,
    }
}

pub fn arm(slot: usize, inv_type: u32) -> usize {
    match slot {0 => 0, 1 => 1, _ if matches!(inv_type, 0x1a | 0x19) => 0, _ => 1}
}
