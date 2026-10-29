import QtQuick
import QtQuick.Controls
import QtQuick.Shapes
import QtQuick.Window
import "." as RuntimeTheme

// Retained vectors for observed block relationships. There is no polling,
// Canvas, offscreen bitmap, timer or synthetic future block in this component.
Item {
    id: root
    objectName: "blockRelationsGraph"
    implicitHeight: 154
    clip: true
    property var graph: ({})
    property var measurements: []
    property var surfaceHost: null
    property string selectedHash: ""
    property bool followTip: true
    property bool pointMode: true
    property bool animateChanges: true
    property int edgeRendererType: Shape.GeometryRenderer
    // Full per-node geometry inspection is a fixture diagnostic. Binding it
    // to every animated x/y in production repeats an O(nodes) scan per node.
    property bool inspectGeometry: false
    // Optional diagnostics are off in the application. They count only real
    // refresh work and never schedule frames, IO or synthetic graph updates.
    property bool inspectRefresh: false
    property int refreshCount: 0
    property real refreshTotalMillis: 0
    property real refreshMaxMillis: 0
    property var refreshLastStages: ({})
    readonly property bool motionActive: animateChanges && visible && (!root.Window.window || root.Window.window.visible && root.Window.window.visibility !== Window.Minimized)
    readonly property bool dagMode: graph.topology === "MULTIPARENT_DAG"
    readonly property bool validProducerCount: graph.producer_count===undefined || Number.isInteger(graph.producer_count) && graph.producer_count>=1 && graph.producer_count<=16
    readonly property int producerCount: Number.isInteger(graph.producer_count) && graph.producer_count>=1 && graph.producer_count<=16 ? graph.producer_count : 4
    readonly property var producerIndices: {var result=[];for(var i=0;i<producerCount;i++)result.push(i);return result}
    readonly property bool supportedTopology: (!graph.topology || graph.topology === "CHAIN" || dagMode) && (!dagMode || validProducerCount)
    readonly property int displayLimit: pointMode ? Math.max(4,Math.min(128,Math.floor((width-24)/5))) : Math.max(4, Math.min(12, Math.floor((width-24)/52)))
    readonly property bool compactGraph: height < 170
    readonly property int retainedCount: _allRows.length
    readonly property int shownCount: _rows.length
    readonly property int edgeCount: _edges.length
    readonly property int highlightedCount: Object.keys(_reachable).length
    readonly property bool animationRunning: runningAnimations()
    readonly property bool geometryError: inspectGeometry && invalidGeometry()
    readonly property bool stale: graph.stale === true || !!graph.error
    readonly property var selectedBlock: lookup(selectedHash)
    readonly property var measurementColumns: mapMeasurements()
    readonly property var metrics: graph.metrics || ({})
    readonly property real pointStreamRate: Number(dagMode ? metrics.proposal_bps || metrics.bps || 0 : metrics.bps || 0)
    readonly property real pointPitch: Math.max(1,(width-58)/Math.max(1,displayLimit-1))
    readonly property bool coherentFlow: pointMode && isFinite(pointStreamRate) && pointStreamRate>=20
    property real _flowOffset:0
    property real _coordinateOrigin:0
    property real _coordinateTip:0
    property bool _coordinateInitialized:false
    readonly property string speedCaption: dagMode ? "Förslag/s " + metric(metrics.proposal_bps) + " · Validerade TX/s " + metric(metrics.tx_validation_rate) : "Block/s " + metric(metrics.bps) + " · TX/s " + metric(metrics.tps) + " · API p95 " + metric(metrics.ttf_p95_ms) + " ms"
    function metric(value) { return typeof value === "number" && isFinite(value) && value >= 0 ? value.toFixed(value < 10 ? 2 : 1) : "—" }
    property var _allRows: []
    property var _allByHash: ({})
    property var _rows: []
    property var _edges: []
    property var _allEdges: []
    property var _successorsByHash: ({})
    property var _rankGroups: []
    property int _columnCount: 1
    property int _maxRank: 0
    property var _reachable: ({})
    property var _lanes: [-1]
    property string _signature: ""
    property int _nodeGeneration: 0
    property var _nodeItems: ({})
    property var _nodeData: ({})
    property var _nodeOrder: []
    property var _edgeOrder: []
    property bool _ready: false
    signal copyRequested(string value)

    function hash(value) {
        value = String(value || "").toLowerCase().replace(/^0x/, "")
        return /^[0-9a-f]{64}$/.test(value) ? value : ""
    }
    function lookup(value) {
        return _allByHash[value] || null
    }
    function tail(value,limit) {
        // Qt may expose a QVariantList as an array-like sequence. Accept its
        // bounded tail without cloning an unbounded list or interpreting JSON.
        if(!value || typeof value.length!=="number" || !Number.isInteger(value.length) || value.length<0 || value.length>4096)return []
        var result=[]
        for(var i=Math.max(0,value.length-limit);i<value.length;i++)result.push(value[i])
        return result
    }
    function refresh() {
        if(!inspectRefresh){refreshGraph();return}
        var started=Date.now()
        try{refreshGraph()}
        finally{
            var elapsed=Date.now()-started
            refreshCount++;refreshTotalMillis+=elapsed
            refreshMaxMillis=Math.max(refreshMaxMillis,elapsed)
        }
    }
    function refreshGraph() {
        if(!root || !root._ready)return
        var work=inspectRefresh ? {started:Date.now()} : null
        var source=supportedTopology ? tail(graph.blocks,128) : [], rows=[], seen={}
        for(var i=0;i<source.length;i++) {
            var r=source[i], h=hash(r.hash), p=hash(r.parent_hash)
            if(!h || seen[h] || typeof r.height!=="number" || r.height<0 || r.height%1!==0) continue
            var parents=[], rank=r.height, genesis=false, sequence=-1
            if(dagMode) {
                if(typeof r.rank!=="number" || !Number.isSafeInteger(r.rank) || r.rank<0 || r.rank!==r.height)continue
                rank=r.rank
                if(!r.parent_hashes || typeof r.parent_hashes.length!=="number" || !Number.isInteger(r.parent_hashes.length) || r.parent_hashes.length<0 || r.parent_hashes.length>7)continue
                var rawParents=tail(r.parent_hashes,7), invalid=false
                for(var q=0;q<rawParents.length;q++) {
                    var parentHash=hash(rawParents[q])
                    if(!parentHash || parentHash===h || parents.indexOf(parentHash)>=0){invalid=true;break}
                    parents.push(parentHash)
                }
                if(invalid)continue
                genesis=rank===0 && r.state==="GENESIS" && parents.length===0
                if(!genesis && (r.state!=="ADMITTED_UNFINALIZED" || r.signature_verified!==true || parents.length===0 || !Number.isInteger(r.proposer_index) || r.proposer_index<0 || r.proposer_index>=producerCount))continue
                sequence=Number.isSafeInteger(r.producer_sequence) && r.producer_sequence>=0 ? r.producer_sequence : -1
                if(r.admission_index!==undefined && (!Number.isSafeInteger(r.admission_index) || r.admission_index<0))continue
            }
            seen[h]=true
            rows.push({hash:h,parent_hash:p,parent_hashes:parents,height:r.height,rank:rank,
                transaction_count:typeof r.transaction_count==="number" && isFinite(r.transaction_count) && r.transaction_count>=0 && r.transaction_count<=4096 && r.transaction_count%1===0 ? r.transaction_count : null,
                timestamp:typeof r.timestamp==="number" ? r.timestamp : null,
                certificate_verified:!dagMode && r.certificate_verified===true,
                signature_verified:dagMode && !genesis && r.signature_verified===true,
                genesis:genesis,producer_sequence:sequence,
                admission_index:dagMode ? r.admission_index===undefined ? i : r.admission_index : r.height,
                source_index:i,
                proposer_index:genesis ? -1 : typeof r.proposer_index==="number" && r.proposer_index>=0 && r.proposer_index<(dagMode ? producerCount : 16) && r.proposer_index%1===0 ? r.proposer_index : -1})
        }
        rows.sort(function(a,b){return dagMode && pointMode ? a.admission_index-b.admission_index || a.source_index-b.source_index : a.rank-b.rank || a.producer_sequence-b.producer_sequence || a.proposer_index-b.proposer_index || a.hash.localeCompare(b.hash)})
        var allByHash={},allEdges=[],edgeSeen={},successors={}
        for(i=0;i<rows.length;i++)allByHash[rows[i].hash]=rows[i]
        var supplied=tail(graph.edges,dagMode ? 896 : 128)
        for(i=0;i<supplied.length;i++) {
            var from=hash(supplied[i].from), to=hash(supplied[i].to), parent=allByHash[from], child=allByHash[to]
            if(!parent || !child || edgeSeen[from+to] || !validParent(parent,child))continue
            edgeSeen[from+to]=true;allEdges.push({from:from,to:to})
            if(!successors[from])successors[from]=[]
            successors[from].push(to)
        }
        _allRows=rows;_allByHash=allByHash;_allEdges=allEdges;_successorsByHash=successors
        var maxRank=0;for(i=0;i<rows.length;i++)maxRank=Math.max(maxRank,rows[i].rank);_maxRank=maxRank
        if(work)work.parsed=Date.now()
        var flowDelta=0,coordinateReset=false
        if(pointMode && rows.length) {
            var coordinateRows=rows.slice(-displayLimit),rawTip=coordinateRows[coordinateRows.length-1].admission_index
            var rawFirst=coordinateRows[0].admission_index,oldRawTip=_coordinateOrigin+_coordinateTip
            coordinateReset=!_coordinateInitialized || rawTip<oldRawTip || rawTip<_coordinateOrigin
            if(coordinateReset || rawTip-_coordinateOrigin>4096)_coordinateOrigin=rawFirst
            if(!coordinateReset)flowDelta=Math.max(0,(rawTip-oldRawTip)*pointPitch)
            _coordinateTip=rawTip-_coordinateOrigin;_coordinateInitialized=true
        } else if(pointMode) {_coordinateInitialized=false;coordinateReset=true;_coordinateTip=0;_coordinateOrigin=0}
        var oldColumns=_columnCount
        var visibleRows=dagMode ? dagWindow(rows) : rows.slice(-displayLimit), byHash={}, edges=[]
        for(i=0;i<visibleRows.length;i++)byHash[visibleRows[i].hash]=i
        for(i=0;i<allEdges.length;i++) {
            from=allEdges[i].from;to=allEdges[i].to;var a=byHash[from],b=byHash[to]
            if(a===undefined || b===undefined)continue
            edges.push({from:from,to:to,source:a,target:b})
        }
        var signature=JSON.stringify([dagMode,visibleRows,edges])
        if(signature===_signature){rebuildSelection();return}
        if(!pointMode && coherentFlow && _rows.length && visibleRows.length) {
            var anchor=_rows[_rows.length-1], newIndex=byHash[anchor.hash]
            if(newIndex!==undefined) {
                var oldX=dagMode ? oldColumns<2 ? plot.width/2 : 32+anchor.grid_column*Math.max(0,plot.width-60)/(oldColumns-1) : _rows.length<2 ? plot.width/2 : 30+(_rows.length-1)*Math.max(0,plot.width-58)/(_rows.length-1)
                var newX=dagMode ? _columnCount<2 ? plot.width/2 : 32+visibleRows[newIndex].grid_column*Math.max(0,plot.width-60)/(_columnCount-1) : visibleRows.length<2 ? plot.width/2 : 30+newIndex*Math.max(0,plot.width-58)/(visibleRows.length-1)
                flowDelta=Math.max(0,oldX-newX)
            }
        }
        _signature=signature;_rows=visibleRows;_edges=edges
        if(pointMode && motionActive && flowDelta>0 && !coordinateReset) {
            flowAnimation.stop()
            _flowOffset=Math.min(Math.min(8,2*pointPitch),_flowOffset+flowDelta)
            flowAnimation.duration=horizontalMotionMs(0)
            flowAnimation.from=_flowOffset;flowAnimation.start()
        } else if(!pointMode || coordinateReset) {flowAnimation.stop();_flowOffset=0}
        var lanes=[]
        for(i=0;i<visibleRows.length;i++) if(lanes.indexOf(visibleRows[i].proposer_index)<0) lanes.push(visibleRows[i].proposer_index)
        lanes.sort(function(a,b){return a-b});_lanes=lanes.length ? lanes : [-1]
        var wanted={};for(i=0;i<visibleRows.length;i++)wanted[visibleRows[i].hash]=true
        if(work)work.layout=Date.now()
        // A coalesced read can retire several adjacent blocks. Remove that
        // range in one model operation so every surviving index changes once.
        var nodeOrder=_nodeOrder.slice()
        for(i=nodeOrder.length-1;i>=0;) {
            if(wanted[nodeOrder[i]]){i--;continue}
            var end=i
            while(i>=0 && !wanted[nodeOrder[i]])i--
            nodeModel.remove(i+1,end-i)
            nodeOrder.splice(i+1,end-i)
        }
        var previousData=_nodeData,nextData={}
        for(i=0;i<visibleRows.length;i++) {
            r=visibleRows[i];var found=nodeOrder[i]===r.hash ? i : nodeOrder.indexOf(r.hash,i+1)
            if(found>=0 && found!==i){nodeModel.move(found,i,1);nodeOrder.splice(i,0,nodeOrder.splice(found,1)[0])}
            var data={blockHash:r.hash,blockHeight:r.height,blockRank:r.rank,gridColumn:pointMode ? r.admission_index-_coordinateOrigin : dagMode ? r.grid_column===undefined ? i : r.grid_column : 0,
                      transactionCount:r.transaction_count===null ? -1 : r.transaction_count,
                      proposerIndex:r.proposer_index,producerSequence:r.producer_sequence,genesis:r.genesis,
                      signatureChecked:r.signature_verified,verified:r.certificate_verified}
            if(found<0){nodeModel.insert(i,data);nodeOrder.splice(i,0,r.hash)}
            else {
                // Header identity and signed proposal fields are immutable.
                // Do not notify all Qt roles for an unchanged retained block.
                // Real later changes (for example verified certificates) are
                // compared as well and still update their individual roles.
                var before=previousData[r.hash],changes={},changed=false
                for(var role in data)if(!before || before[role]!==data[role]){changes[role]=data[role];changed=true}
                if(changed)nodeModel.set(i,changes)
            }
            nextData[r.hash]=data
        }
        _nodeData=nextData;_nodeOrder=nodeOrder
        if(work)work.nodes=Date.now()
        // Retain each real parent-child path by identity. Shifting a chain's
        // window must not overwrite/rebuild every surviving edge every frame.
        var wantedEdges={}
        for(i=0;i<edges.length;i++)wantedEdges[edges[i].from+edges[i].to]=true
        var edgeOrder=_edgeOrder.slice()
        for(i=edgeOrder.length-1;i>=0;){
            if(wantedEdges[edgeOrder[i]]){i--;continue}
            end=i
            while(i>=0 && !wantedEdges[edgeOrder[i]])i--
            edgeModel.remove(i+1,end-i)
            edgeOrder.splice(i+1,end-i)
        }
        for(i=0;i<edges.length;i++) {
            var link={fromHash:edges[i].from,toHash:edges[i].to}
            var edgeKey=link.fromHash+link.toHash
            var edgeIndex=edgeOrder[i]===edgeKey ? i : edgeOrder.indexOf(edgeKey,i+1)
            if(edgeIndex<0){edgeModel.insert(i,link);edgeOrder.splice(i,0,edgeKey)}
            else if(edgeIndex!==i){edgeModel.move(edgeIndex,i,1);edgeOrder.splice(i,0,edgeOrder.splice(edgeIndex,1)[0])}
        }
        _edgeOrder=edgeOrder
        if(work)work.edges=Date.now()
        var selectionUpdated=false
        if(followTip || !byHash.hasOwnProperty(selectedHash)) {
            followTip=true
            var nextSelection=liveSelection()
            if(selectedHash!==nextSelection){selectedHash=nextSelection;selectionUpdated=true}
        }
        // selectedHash's change handler already traversed the new adjacency.
        // Repeating it doubles every dependent path-color update.
        if(!selectionUpdated)rebuildSelection()
        Qt.callLater(refreshNodes)
        if(work)refreshLastStages={parse:work.parsed-work.started,layout:work.layout-work.parsed,
            nodes:work.nodes-work.layout,edges:work.edges-work.nodes,selection:Date.now()-work.edges}
    }
    function validParent(parent,child) {
        return dagMode ? child.parent_hashes.indexOf(parent.hash)>=0 && parent.rank<child.rank : child.parent_hash===parent.hash && child.height===parent.height+1
    }
    function dagWindow(rows) {
        if(pointMode) {
            // Admission index is local receipt/layout metadata, never a
            // consensus ordering. Every eligible real retained record gets
            // a dot; ranks are sparse axis labels rather than a filter.
            var points=rows.slice(-displayLimit),groups=[],labels=Math.min(8,points.length)
            for(var label=0;label<labels;label++) {
                var at=labels<2 ? 0 : Math.round(label*(points.length-1)/(labels-1))
                groups.push({rank:points[at].rank,column:points[at].admission_index-_coordinateOrigin,columns:1,count:1})
            }
            if(JSON.stringify(groups)!==JSON.stringify(_rankGroups))_rankGroups=groups
            _columnCount=Math.max(1,displayLimit);return points
        }
        // Keep real ranks together. Several proposals from the SAME producer
        // may share a rank: each gets its own subcolumn, never a false chain.
        var ranks=[]
        for(var i=0;i<rows.length;i++)if(ranks.indexOf(rows[i].rank)<0)ranks.push(rows[i].rank)
        ranks=ranks.slice(pointMode ? -32 : -3)
        var budget=pointMode ? Math.max(2,Math.min(64,Math.floor((width-32)/10))) : Math.max(2,Math.min(16,Math.floor((width-32)/44)))
        while(ranks.length>1 && budget<ranks.length*2-1)ranks.shift()
        var perProducer=Math.max(1,Math.floor((budget-Math.max(0,ranks.length-1))/Math.max(1,ranks.length)))
        var groups=[],result=[],column=0
        for(i=0;i<ranks.length;i++) {
            var selected=[],maxCount=1
            for(var producer=-1;producer<producerCount;producer++) {
                var candidates=rows.filter(function(row){return row.rank===ranks[i] && row.proposer_index===producer}).slice(-perProducer)
                maxCount=Math.max(maxCount,candidates.length)
                for(var j=0;j<candidates.length;j++) {
                    var copy=Object.assign({},candidates[j]);copy.grid_column=column+j;selected.push(copy)
                }
            }
            selected.sort(function(a,b){return a.grid_column-b.grid_column || a.proposer_index-b.proposer_index})
            groups.push({rank:ranks[i],column:column,columns:maxCount,count:selected.length})
            result=result.concat(selected);column+=maxCount+1
        }
        if(JSON.stringify(groups)!==JSON.stringify(_rankGroups))_rankGroups=groups
        _columnCount=Math.max(1,column-1)
        return result.slice(-128)
    }
    function liveSelection() {return _rows.length ? _rows[dagMode ? 0 : Math.max(0,_rows.length-8)].hash : ""}
    function refreshNodes() {
        if(!root || !root._ready)return
        var items={}
        for(var i=0;i<nodes.count;i++){var item=nodes.itemAt(i);if(item)items[item.blockHash]=item}
        _nodeItems=items;_nodeGeneration++
    }
    function rebuildSelection() {
        var marked={}, frontier=[selectedHash], successors=_successorsByHash
        if(selectedHash)marked[selectedHash]=true
        for(var depth=0;depth<7 && frontier.length;depth++) {
            var next=[]
            for(var i=0;i<frontier.length;i++) {
                // Only the already validated real parent edges populate
                // this bounded adjacency; there is no all-edge scan per hop.
                var children=successors[frontier[i]] || []
                for(var j=0;j<children.length;j++)if(!marked[children[j]]){
                    marked[children[j]]=true;next.push(children[j])
                }
            }
            frontier=next
        }
        _reachable=marked
    }
    function selectBlock(value) {
        value=hash(value)
        if(lookup(value)){followTip=false;selectedHash=value;rebuildSelection();var item=nodeItem(value);if(item)item.forceActiveFocus()}
    }
    function resumeLive() {followTip=true;selectedHash=liveSelection();rebuildSelection()}
    function nodeItem(value) {
        var item=_nodeItems[value]
        return item && item.blockHash===value ? item : null
    }
    function nodeX(index,column) {return pointMode ? 30+(Number.isFinite(column) ? column : 0)*pointPitch : dagMode ? gridX(Number.isInteger(column) ? column : 0) : _rows.length<2 ? plot.width/2 : 30+index*Math.max(0,plot.width-58)/(_rows.length-1)}
    function gridX(column) {return pointMode ? 30+column*pointPitch : _columnCount<2 ? plot.width/2 : 32+column*Math.max(0,plot.width-60)/(_columnCount-1)}
    function nodeY(lane,index,heightArg,sequenceArg) {
        if(pointMode && !dagMode) {
            // A retained block keeps its own vertical layout while the
            // fetched window slides. _rows changes before delegate indices.
            var phase=heightArg
            if(typeof phase!=="number"){var row=_rows[typeof index==="number"?index:0];phase=row?row.height:0}
            return plot.height/2+Math.sin(phase*.53)*Math.max(1,(plot.height-18)*.26)+Math.sin(phase*.17)*Math.max(1,(plot.height-18)*.12)
        }
        var baseline=dagMode ? lane<0 ? 12+(plot.height-14)/2 : 12+(lane+.5)*Math.max(0,plot.height-14)/producerCount : compactGraph ? plot.height/2 : 8+(_lanes.indexOf(lane)+.5)*Math.max(0,plot.height-16)/_lanes.length
        var phase=typeof sequenceArg==="number" && sequenceArg>=0 ? sequenceArg : index
        return pointMode && dagMode && typeof phase==="number" ? baseline+Math.sin(phase*1.7)*Math.min(5,plot.height/32) : baseline
    }
    function proposerColor(lane) {return RuntimeTheme.GGColorContext.colorFor("ui.graph.block.producer."+Math.max(0,lane),lane<0 ? RuntimeTheme.GGTheme.blue : RuntimeTheme.GGTheme.color([0,2,1,4,5,3,6,7,8,9,10,11,12,13,14,15][lane%16]))}
    function entranceOffset(identifier,vertical) {
        // Hash-seeded layout motion belongs to an already known block. It
        // changes no traffic, identity, timestamp, parent or production rate.
        var seed=parseInt(String(identifier).slice(vertical?8:0,vertical?16:8),16)/4294967295
        return (seed*2-1)*(vertical ? Math.min(24,plot.height*.35) : Math.min(12,2*pointPitch))
    }
    function horizontalMotionMs(index) {
        // Every retained point uses the same flow cadence. Different clocks
        // on adjacent blocks create empty bridges, even with smooth durations.
        // New points retain a small bounded 420 ms entrance below instead.
        return pointMode && isFinite(pointStreamRate) && pointStreamRate>=20 ? 32 : 420
    }
    function runningAnimations() {
        var generation=_nodeGeneration
        if(flowAnimation.running)return true
        for(var i=0;i<nodes.count;i++){var item=nodes.itemAt(i);if(item && item.moving)return true}
        return false
    }
    function finishMotion() {
        flowAnimation.stop();_flowOffset=0
        for(var i=0;i<nodes.count;i++){var item=nodes.itemAt(i);if(item)item.finishMotion()}
    }
    function invalidGeometry() {
        if(width<=0 || height<=0)return false
        var generation=_nodeGeneration
        for(var i=0;i<nodes.count;i++) {
            var item=nodes.itemAt(i)
            var physicalX=item ? item.x+flowLayer.x : 0
            if(item && (physicalX<0 || item.y<0 || physicalX+item.width>plot.width+.5 || item.y+item.height>plot.height+.5))return true
        }
        return false
    }
    function mapMeasurements() {
        var source=tail(measurements,32), result=[]
        for(var i=0;i<source.length;i++) {
            var m=source[i], h=hash(m.block_hash), block=h ? lookup(h) : null
            if(!h && typeof m.block_height==="number")block=uniqueHeight(m.block_height)
            if(block && typeof m.block_height==="number" && block.height!==m.block_height)block=null
            result.push({measurement_index:i,known:!!block,block_hash:block ? block.hash : "",block_height:block ? block.height : null})
        }
        return result
    }
    function uniqueHeight(height) {
        var found=null
        for(var i=0;i<_allRows.length;i++)if(_allRows[i].height===height){if(found)return null;found=_allRows[i]}
        return found
    }
    function selectMeasurement(measurement) {
        var h=hash(measurement.block_hash),block=h ? lookup(h) : null
        if(!h && typeof measurement.block_height==="number")block=uniqueHeight(measurement.block_height)
        if(!block || typeof measurement.block_height==="number" && block.height!==measurement.block_height)return false
        selectBlock(block.hash);return true
    }
    function copySelected() {
        if(!selectedBlock)return
        if(surfaceHost && surfaceHost.tmogCopy)surfaceHost.tmogCopy(selectedBlock.hash)
        copyRequested(selectedBlock.hash)
    }
    onGraphChanged: if(_ready)Qt.callLater(refresh)
    onDagModeChanged: if(_ready)Qt.callLater(refresh)
    onWidthChanged: if(_ready)Qt.callLater(refresh)
    onDisplayLimitChanged: if(_ready)Qt.callLater(refresh)
    onSelectedHashChanged: rebuildSelection()
    onMotionActiveChanged: if(!motionActive)finishMotion()
    Component.onCompleted: {_ready=true;refresh()}
    Component.onDestruction: _ready=false

    ListModel {id:nodeModel}
    ListModel {id:edgeModel}
    NumberAnimation {id:flowAnimation;target:root;property:"_flowOffset";to:0;duration:32;easing.type:Easing.OutCubic}
    GGText { colorKey: "ui.BlockRelationsGraph.1";
        anchors.left:parent.left;anchors.right:countCaption.left;anchors.rightMargin:8;height:18
        text:!root.supportedTopology ? "OKÄND BLOCKTOPOLOGI" : root.stale ? "BLOCKRELATIONER · ÄLDRE DATA" : root.dagMode ? "PARALLELL DAG · EJ FINALISERAD" : "BLOCKRELATIONER · BLOCK / TX"
        color:root.stale ? RuntimeTheme.GGTheme.warning : RuntimeTheme.GGTheme.muted;font.family:"monospace";font.pixelSize:9
        elide:Text.ElideRight;textFormat:Text.PlainText
    }
    GGText { colorKey: "ui.BlockRelationsGraph.2";
        id:countCaption;anchors.right:parent.right;height:18
        text:(root.width>=650 ? root.speedCaption+" · " : "")+root.shownCount+" / "+root.retainedCount+" hämtade"+(typeof root.graph.tip_height==="number" ? " · "+(root.dagMode?"R":"H")+root.graph.tip_height:"")+" · "+(root.graph.partial_history || root.shownCount<root.retainedCount ? "DELVY · " : "")+(root.dagMode ? "DAG" : "KEDJA")
        color:RuntimeTheme.GGTheme.dim;font.family:"monospace";font.pixelSize:9;textFormat:Text.PlainText
        HoverHandler {id:metricsHover}
        ToolTip.visible:metricsHover.hovered
        ToolTip.text:root.speedCaption+"\nObservationsfönster: "+root.metric(root.metrics.window_seconds)+" s\n"+(root.dagMode ? "Signerade lokala förslag och validerade testposter. Ingen global ordning eller finalitet." : "TX/s: inkluderade transaktioner, inte garanterat lyckad exekvering.\nAPI-tid: "+String(root.metrics.ttf_basis || "ej uppmätt"))
    }
    Item {
        id:plot;x:0;y:20;width:parent.width;height:Math.max(22,parent.height-44);clip:true
        Repeater {
            model:root.pointMode ? [] : root.dagMode ? root.producerIndices : root.compactGraph ? [-1] : root._lanes
            delegate:Item {
                required property int modelData
                y:root.nodeY(modelData);width:plot.width;height:1
                Rectangle {x:18;width:Math.max(0,parent.width-18);height:1;color:RuntimeTheme.GGTheme.line;opacity:.6}
                GGText { colorKey: "ui.BlockRelationsGraph.3";
                    x:0;y:-5;width:20;text:root.dagMode ? "P"+(parent.modelData+1) : root.compactGraph ? "" : parent.modelData<0 ? "—" : "V"+(parent.modelData+1)
                    color:RuntimeTheme.GGTheme.dim;font.family:"monospace";font.pixelSize:8;textFormat:Text.PlainText
                }
            }
        }
        Repeater {
            model:root.dagMode ? root._rankGroups.length : 0
            delegate:Item {
                required property int index
                readonly property var modelData:root._rankGroups[index] || ({column:0,columns:0,count:0,rank:0})
                x:root.gridX(modelData.column)-20+(root.pointMode ? flowLayer.x : 0);y:0
                width:Math.max(40,root.gridX(modelData.column+modelData.columns-1)-root.gridX(modelData.column)+40);height:10
                Rectangle {x:0;y:9;width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
                GGText { colorKey: "ui.BlockRelationsGraph.4";anchors.fill:parent;text:root.pointMode ? "R"+parent.modelData.rank : "R"+parent.modelData.rank+" · "+parent.modelData.count+" parallella";font.family:"monospace";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignHCenter;textFormat:Text.PlainText;elide:Text.ElideRight}
            }
        }
        Item {
        id:flowLayer;objectName:"blockFlowLayer";width:plot.width;height:plot.height
        x:root.pointMode ? plot.width-28-(30+root._coordinateTip*root.pointPitch)+root._flowOffset : 0
        // One retained scene transform moves the existing paths and points.
        // It must not retessellate every real parent curve each frame.
        Repeater {
            model:edgeModel
            delegate:Shape {
                id:edgeShape
                required property string fromHash
                required property string toHash
                property var fromNode:root.nodeItem(fromHash)
                property var toNode:root.nodeItem(toHash)
                anchors.fill:parent;visible:!!fromNode && !!toNode;z:0
                preferredRendererType:root.edgeRendererType
                ShapePath {
                    strokeColor:root._reachable[edgeShape.fromHash] && root._reachable[edgeShape.toHash] ? RuntimeTheme.GGTheme.cyan : root.pointMode ? Qt.rgba(RuntimeTheme.GGTheme.muted.r,RuntimeTheme.GGTheme.muted.g,RuntimeTheme.GGTheme.muted.b,root.dagMode?.28:.55) : RuntimeTheme.GGTheme.edge
                    strokeWidth:root.pointMode ? root._reachable[edgeShape.toHash] ? 1 : .65 : root._reachable[edgeShape.toHash] ? 1.5 : 1
                    fillColor:"transparent";capStyle:ShapePath.RoundCap
                    startX:edgeShape.fromNode ? edgeShape.fromNode.x+edgeShape.fromNode.width*(root.pointMode?.5:1) : 0
                    startY:edgeShape.fromNode ? edgeShape.fromNode.y+edgeShape.fromNode.height/2 : 0
                    PathCubic {
                        x:edgeShape.toNode ? edgeShape.toNode.x+(root.pointMode?edgeShape.toNode.width/2:0) : 0
                        y:edgeShape.toNode ? edgeShape.toNode.y+edgeShape.toNode.height/2 : 0
                        control1X:edgeShape.fromNode && edgeShape.toNode ? (edgeShape.fromNode.x+edgeShape.fromNode.width+edgeShape.toNode.x)/2 : 0
                        control1Y:edgeShape.fromNode ? edgeShape.fromNode.y+edgeShape.fromNode.height/2 : 0
                        control2X:control1X
                        control2Y:edgeShape.toNode ? edgeShape.toNode.y+edgeShape.toNode.height/2 : 0
                    }
                    PathMove {x:edgeShape.toNode ? edgeShape.toNode.x+(root.pointMode?edgeShape.toNode.width/2:-4) : 0;y:edgeShape.toNode ? edgeShape.toNode.y+edgeShape.toNode.height/2-(root.pointMode?0:2.5) : 0}
                    PathLine {x:edgeShape.toNode ? edgeShape.toNode.x+(root.pointMode?edgeShape.toNode.width/2:0) : 0;y:edgeShape.toNode ? edgeShape.toNode.y+edgeShape.toNode.height/2 : 0}
                    PathLine {x:edgeShape.toNode ? edgeShape.toNode.x+(root.pointMode?edgeShape.toNode.width/2:-4) : 0;y:edgeShape.toNode ? edgeShape.toNode.y+edgeShape.toNode.height/2+(root.pointMode?0:2.5) : 0}
                }
            }
        }
        Repeater {
            id:nodes;model:nodeModel
            onItemAdded:Qt.callLater(root.refreshNodes)
            onItemRemoved:Qt.callLater(root.refreshNodes)
            delegate:Item {
                id:node
                required property int index
                required property string blockHash
                required property int blockHeight
                required property int blockRank
                required property int gridColumn
                required property int transactionCount
                required property int proposerIndex
                required property int producerSequence
                required property bool genesis
                required property bool signatureChecked
                required property bool verified
                readonly property bool moving:moveX.running || moveY.running || appear.running || birth.running || enterX.running || enterY.running
                readonly property int horizontalDuration:root.horizontalMotionMs(index)
                onHorizontalDurationChanged:if(horizontalDuration===0)moveX.complete()
                property real birthPulse:0
                property real arrivalOffset:0
                property real arrivalYOffset:0
                readonly property bool isTip:root.dagMode ? blockRank===root._maxRank : index===root._rows.length-1
                objectName:"relationBlock";width:root.pointMode ? 10 : root.dagMode ? Math.min(48,Math.max(24,(plot.width-60)/Math.max(1,root._columnCount-1)-10)) : Math.min(50,Math.max(40,(plot.width-40)/Math.max(1,root.shownCount)-10));height:root.pointMode ? 10 : root.dagMode ? Math.min(28,Math.max(root.producerCount>4?6:12,(plot.height-14)/root.producerCount-4)) : root.compactGraph ? Math.min(36,Math.max(30,plot.height-14)) : Math.min(28,Math.max(18,(plot.height-8)/Math.max(1,root._lanes.length)-2))
                // The fixed right margin exceeds the shared slide (<=8px)
                // plus the new block entrance (<=12px). No all-node clamp
                // may depend on the moving parent: that dirties every path.
                x:root.nodeX(index,gridColumn)-width/2+arrivalOffset
                y:Math.max(0,Math.min(plot.height-height,root.nodeY(proposerIndex,index,blockHeight,producerSequence)-height/2+arrivalYOffset))
                // Live-follow highlights data without moving keyboard focus
                // away from a transfer field. selectBlock() focuses only an
                // explicit user-selected point for keyboard navigation.
                opacity:1;activeFocusOnTab:true;z:1
                Accessible.role:Accessible.Button
                Accessible.name:root.dagMode ? genesis ? "Publikt genesisankare" : "Ofinaliserat signerat förslag, rank "+blockRank+", producent "+(proposerIndex+1)+", sekvens "+producerSequence : "Block "+blockHeight+", "+(transactionCount<0 ? "okänt antal" : transactionCount)+" transaktioner"
                function finishMotion(){moveX.complete();moveY.complete();appear.complete();birth.complete();enterX.complete();enterY.complete()}
                onIndexChanged:if(index<root.shownCount-24){enterX.complete();enterY.complete()}
                Behavior on x {enabled:root.motionActive && !root.pointMode;NumberAnimation {id:moveX;duration:node.horizontalDuration;easing.type:Easing.OutCubic}}
                Behavior on y {enabled:root.motionActive && (root.dagMode || !root.compactGraph);NumberAnimation {id:moveY;duration:420;easing.type:Easing.OutCubic}}
                NumberAnimation {id:appear;target:node;property:"opacity";from:root.coherentFlow?.55:0;to:1;duration:420}
                NumberAnimation {id:birth;target:node;property:"birthPulse";from:1;to:0;duration:620}
                NumberAnimation {id:enterX;target:node;property:"arrivalOffset";from:root.entranceOffset(node.blockHash,false);to:0;duration:420;easing.type:Easing.OutCubic}
                NumberAnimation {id:enterY;target:node;property:"arrivalYOffset";from:root.entranceOffset(node.blockHash,true);to:0;duration:420;easing.type:Easing.OutCubic}
                Component.onCompleted:if(root.motionActive){appear.start();birth.start();if(root.pointMode && index>=root.shownCount-24){enterX.start();enterY.start()}}
                Rectangle {
                    id:nodePaint
                    anchors.centerIn:parent
                    width:root.pointMode ? root.selectedHash===node.blockHash?8:5+2*node.birthPulse : parent.width
                    height:root.pointMode ? width : parent.height
                    radius:root.pointMode?width/2:1
                    color:root.pointMode ? root.proposerColor(node.proposerIndex) : root.dagMode ? Qt.darker(root.proposerColor(node.proposerIndex),root.selectedHash===node.blockHash ? 3.5 : 5.5-node.birthPulse) : Qt.rgba(root.proposerColor(node.proposerIndex).r,root.proposerColor(node.proposerIndex).g,root.proposerColor(node.proposerIndex).b,root.selectedHash===node.blockHash ? .24 : node.isTip ? .16+.25*node.birthPulse : .04+.18*node.birthPulse)
                    border.width:1;border.color:root.selectedHash===node.blockHash ? RuntimeTheme.GGTheme.bright : node.verified || node.isTip || root.dagMode && node.signatureChecked ? root.proposerColor(node.proposerIndex) : root._reachable[node.blockHash] ? RuntimeTheme.GGTheme.cyan : RuntimeTheme.GGTheme.edge
                    GGColorTarget {colorKey:"ui.graph.block.producer."+Math.max(0,node.proposerIndex)}
                }
                // Points have no caption. Do not allocate and shape a hidden
                // GGText/selection-handler tree for every real incoming block.
                Loader {
                    objectName:"relationBlockLabelLoader"
                    anchors.fill:parent;active:!root.pointMode
                    sourceComponent:GGText { colorKey: "ui.BlockRelationsGraph.5";
                        anchors.fill:parent;leftPadding:2;rightPadding:2
                        text:root.dagMode ? node.genesis ? "GEN" : "P"+(node.proposerIndex+1)+"·"+(node.producerSequence<0 ? "?" : node.producerSequence)+(node.height>=20 ? "\nR"+node.blockRank+" · "+(node.transactionCount<0 ? "?" : node.transactionCount) : "") : "H "+String(node.blockHeight)+"\n"+(node.transactionCount<0 ? "?" : node.transactionCount)+" tx"
                        horizontalAlignment:Text.AlignHCenter;verticalAlignment:Text.AlignVCenter
                        color:node.isTip || root.selectedHash===node.blockHash ? RuntimeTheme.GGTheme.bright : RuntimeTheme.GGTheme.text
                        font.family:"monospace";font.pixelSize:root.dagMode ? 8 : 9;textFormat:Text.PlainText;elide:Text.ElideRight
                    }
                }
                MouseArea {id:hit;anchors.fill:parent;hoverEnabled:true;cursorShape:Qt.PointingHandCursor;onClicked:root.selectBlock(node.blockHash)}
                Keys.onReturnPressed:details.open()
                Keys.onEnterPressed:details.open()
                Keys.onSpacePressed:root.selectBlock(blockHash)
                Keys.onLeftPressed:if(index>0)root.selectBlock(root._rows[index-1].hash)
                Keys.onRightPressed:if(index+1<root._rows.length)root.selectBlock(root._rows[index+1].hash)
                Keys.onPressed:function(event){if(event.key===Qt.Key_C){root.copySelected();event.accepted=true}}
                ToolTip.visible:hit.containsMouse
                ToolTip.text:root.dagMode ? genesis ? "Publikt genesisankare, ingen finalitetsstämpel" : "Rank "+blockRank+" · producent "+(proposerIndex+1)+" · sekvens "+producerSequence+"\n"+(transactionCount<0 ? "Okänt antal" : transactionCount)+" lokala testposter\nSignatur kontrollerad · EJ FINALISERAT" : "Block "+blockHeight+" · "+(transactionCount<0 ? "okänt" : transactionCount)+" tx\n"+(proposerIndex>=0 ? "Validator "+(proposerIndex+1)+"\n" : "Lokal nod\n")+(verified ? "SDK-verifierat certifikat" : "Observerad noddata")
            }
        }
        }
        GGText { colorKey: "ui.BlockRelationsGraph.6";
            visible:root.shownCount===0;anchors.centerIn:parent;width:Math.max(0,parent.width-20)
            text:root.stale ? "Blockdata saknas eller kunde inte läsas." : root.dagMode ? "Inga lokalt signerade förslag ännu." : "Inga observerade block ännu."
            horizontalAlignment:Text.AlignHCenter;wrapMode:Text.WordWrap;textFormat:Text.PlainText
            color:RuntimeTheme.GGTheme.dim;font.family:"monospace";font.pixelSize:10
        }
    }
    GGText { colorKey: "ui.BlockRelationsGraph.7";
        x:0;anchors.bottom:parent.bottom;width:Math.max(0,parent.width-detailButton.width-liveButton.width-12);height:20
        text:root.width<650 ? root.speedCaption : root.selectedBlock ? (root.dagMode ? "R" : "H")+root.selectedBlock.height+" · "+root.selectedHash.slice(0,8)+"… · "+Math.max(0,root.highlightedCount-1)+" efterföljare" : root.dagMode ? "Verkliga föräldrar · högst 7 efterföljarled · ej finalitet" : "Verkliga länkar · högst 7 efterföljare"
        color:RuntimeTheme.GGTheme.muted;font.family:"monospace";font.pixelSize:9;elide:Text.ElideRight;textFormat:Text.PlainText
    }
    CryptoButton { property string uiColorScope: "ui.control.BlockRelationsGraph.1";
        id:liveButton;objectName:"blockRelationsLive";anchors.right:detailButton.left;anchors.rightMargin:4;anchors.bottom:parent.bottom
        width:46;height:20;implicitHeight:20;font.pixelSize:9;text:root.followTip ? "LIVE" : "Följ"
        enabled:!root.followTip && root.shownCount>0;onClicked:root.resumeLive()
        leftPadding:4;rightPadding:4;topPadding:0;bottomPadding:0
    }
    CryptoButton { property string uiColorScope: "ui.control.BlockRelationsGraph.2";
        id:detailButton;objectName:"blockRelationsDetails";anchors.right:parent.right;anchors.bottom:parent.bottom
        width:70;height:20;implicitHeight:20;font.pixelSize:9;text:"Detaljer"
        enabled:!!root.selectedBlock;onClicked:details.open()
        leftPadding:4;rightPadding:4;topPadding:0;bottomPadding:0
    }
    Popup {
        id:details;objectName:"blockRelationsPopup"
        parent:Overlay.overlay
        width:Math.min(480,Math.max(240,root.width-12));height:Math.min(300,implicitHeight)
        x:parent ? Math.max(4,(parent.width-width)/2) : 0
        y:parent ? Math.max(4,(parent.height-height)/2) : 0
        padding:12;modal:true;focus:true;closePolicy:Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background:Rectangle {color:RuntimeTheme.GGTheme.panel;border.color:RuntimeTheme.GGTheme.edge;border.width:1;radius:2}
        contentItem:Loader {
            objectName:"blockRelationsDetailsContent"
            active:details.visible
            sourceComponent:Column {
            width:details.availableWidth;spacing:7
            GGText { colorKey: "ui.BlockRelationsGraph.8";text:root.selectedBlock ? (root.dagMode ? "FÖRSLAG R" : "BLOCK ")+root.selectedBlock.height+(root.dagMode ? " · EJ FINALISERAT" : "") : "BLOCK";color:RuntimeTheme.GGTheme.bright;font.family:"monospace";font.pixelSize:12;textFormat:Text.PlainText}
            TextArea {
                objectName:"blockRelationsFullHash";width:parent.width;height:52;readOnly:true;selectByMouse:true
                text:root.selectedHash;wrapMode:TextEdit.WrapAnywhere;color:RuntimeTheme.GGTheme.text;font.family:"monospace";font.pixelSize:10
                background:Rectangle {color:RuntimeTheme.GGTheme.canvas;border.color:RuntimeTheme.GGTheme.line}
            }
            GGText { colorKey: "ui.BlockRelationsGraph.9";
                width:parent.width;text:root.selectedBlock ? root.dagMode ? (root.selectedBlock.transaction_count===null ? "Okänt antal" : root.selectedBlock.transaction_count)+" lokalt validerade testposter\n"+(root.selectedBlock.genesis ? "Publikt genesisankare" : "Signatur kontrollerad, ingen global finalitet")+"\n"+root.selectedBlock.parent_hashes.length+" verkliga föräldrareferenser" : (root.selectedBlock.transaction_count===null ? "Okänt antal" : root.selectedBlock.transaction_count)+" inkluderade transaktioner\n"+(root.selectedBlock.certificate_verified ? "SDK-verifierat certifikat" : "Observerad noddata, separat från SDK-bevis") : ""
                color:RuntimeTheme.GGTheme.muted;font.family:"monospace";font.pixelSize:10;wrapMode:Text.WordWrap;textFormat:Text.PlainText
            }
            Row {spacing:8
                CryptoButton { property string uiColorScope: "ui.control.BlockRelationsGraph.3";objectName:"blockRelationsCopy";text:"Kopiera hash";height:26;font.pixelSize:10;onClicked:root.copySelected()}
                CryptoButton { property string uiColorScope: "ui.control.BlockRelationsGraph.4";text:"Stäng";height:26;font.pixelSize:10;onClicked:details.close()}
            }
            }
        }
    }
}
