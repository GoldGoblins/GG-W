# Local GG compatibility changes

The original upstream checkout remains unchanged. In this compiled GG copy,
`script/model.rs` and `script/merchant.rs` retain the full cursor item until the local merchant
transaction completes. The original coordinates-only accessor remains
available and drains the same queue. The additional accessor preserves split
counts; refused sales can restore the same cursor after source validation,
without replacing a more recent cursor.

`script/party.rs` restores the real saved ready-check deadline and uses actual
own/leader GUIDs before its retained legacy index fallback. `script/trade.rs`
and the model add a bounded intent queue for an armed enchant cursor clicking
actual partner gear in non-transferred slot seven. Ordinary partner slots stay
inert; money and held-item precedence remain intact. The runtime freezes the
shown exact target and scroll, retains original bind/replace prompts, and waits
for both saved characters to accept the resulting immutable terms.

`local-adaptations.json` records the original and adapted revisions. The audit
checks both against the retained upstream source and current GG source.
Native merchant tests and actual Lua-to-GG transaction tests cover split
counts, rollback, cursor replacement and durable item custody.
