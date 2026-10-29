function currency(row) {return row.settlement_asset_id || "legacy-solana-SOL"}
function atomic(row) {return String((row.settlement || {}).price_atomic || row.price_lamports || "0").replace(/^0+(?=\d)/,"")}
function compareAtomic(a,b) {a=String(a).replace(/^0+(?=\d)/,"");b=String(b).replace(/^0+(?=\d)/,"");return a.length===b.length ? (a===b ? 0 : a<b ? -1 : 1) : a.length<b.length ? -1 : 1}
function apply(rows,filters) {
    var query=String(filters.query || "").toLowerCase()
    var result=(rows || []).filter(function(row) {
        var text=[row.title,row.maker,row.origin,row.material,row.description,row.collection_name].join(" ").toLowerCase()
        return (!query || text.indexOf(query)>=0)
            && (!filters.collection || row.collection_name===filters.collection)
            && (!filters.network || ((row.nft_binding || {}).chain_id || row.network)===filters.network)
            && (!filters.kind || row.kind===filters.kind)
            && (!filters.status || row.status===filters.status)
            && (!filters.currency || currency(row)===filters.currency)
            && (!filters.imagesOnly || !!row.image_url)
    })
    result.sort(function(a,b) {
        if(filters.sort==="price" && filters.currency)return compareAtomic(atomic(a),atomic(b)) || String(a.id).localeCompare(String(b.id))
        if(filters.sort==="name")return String(a.title).localeCompare(String(b.title))
        return Number(b.listed_at || 0)-Number(a.listed_at || 0) || String(a.id).localeCompare(String(b.id))
    })
    return result
}
