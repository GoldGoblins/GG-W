
import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import QtQuick.Dialogs

Item {
    id: root
    objectName: "workspaceGameWorkflowsPane"
    property var surfaceHost: null
    property int stage: 0
    property string sourcePath: ""
    property string gameLabel: ""
    property string query: ""
    property string exportPath: ""
    property string targetPath: ""
    property string functionQuery: ""
    property string contextPath: ""
    property string candidatePath: ""
    property string flowPath: ""
    property string jobId: ""
    property string jobState: ""
    property string activeOperation: ""
    property string resultJson: "{}"
    property string notice: "Choose a local asset directory. Game labels describe the source; file formats choose the adapter."
    property var selectedKeys: []
    property string browseTarget: "sourcePath"
    property bool showDetails: false
    property bool nativeReader: false
    property string indexCursor: ""
    property bool collectionRecursive: true
    property int collectionPartition: 0
    property int collectionPartitions: 1
    property string animationPath: ""
    property string rigFps: ""
    property string rigBasis: ""
    property string profileLodPath: ""
    property string profilePlan: ""
    onTargetPathChanged: root.profilePlan = ""
    onProfileLodPathChanged: root.profilePlan = ""
    readonly property bool busy: jobState === "QUEUED" || jobState === "RUNNING" || jobState === "CANCELLING"
    readonly property var result: { try { return JSON.parse(root.resultJson) } catch (e) { return {} } }
    readonly property var contextFunction: (root.result.context || {}).function || ({})
    signal analysisRequested(string path)

    function request(op, payload) {
        if (!root.surfaceHost || !root.surfaceHost.researchCommand) return {status:"ERROR", reason:"Research Desk is connecting."}
        try {
            var result = JSON.parse(String(root.surfaceHost.researchCommand(JSON.stringify({op:op, payload:payload || {}}))))
            if (!result || typeof result !== "object") throw new Error("Missing result")
            return result
        }
        catch (e) { return {status:"ERROR", reason:"Desktop bridge unavailable"} }
    }
    function run(operation, parameters) {
        if (root.busy) return false
        var response = root.request("game_start", {operation:operation, arguments:parameters})
        root.activeOperation = operation
        root.jobState = String(response.status || "ERROR")
        root.notice = String(response.detail || response.reason || response.error || response.status || "No job returned")
        root.jobId = String(response.job_id || "")
        if (root.busy && !root.jobId) {
            root.jobState = "ERROR"
            root.notice = "The workflow service did not return a job. Your inputs are retained."
            return false
        }
        if (root.busy) root.resultJson = "{}"
        return root.busy
    }
    function poll() {
        if (!root.jobId) return
        var response = root.request("game_status", {job_id:root.jobId})
        root.jobState = String(response.status || "ERROR")
        if (response.result) {
            root.resultJson = JSON.stringify(response.result)
            root.notice = String(response.result.summary || response.result.reason || response.result.status || "")
            if (response.result.packet_path && root.activeOperation.indexOf("context_") === 0)
                root.contextPath = String(response.result.packet_path)
            if (response.result.packet_path && (root.activeOperation === "flow_import" || root.activeOperation === "flow_check"))
                root.flowPath = String(response.result.packet_path)
            if (root.activeOperation === "scout_search") root.selectedKeys = []
            if (root.activeOperation === "scout_batch") root.indexCursor = String(response.result.cursor || "")
            if (root.activeOperation === "scout_batch_cancel") root.indexCursor = ""
            if (root.activeOperation === "asset_profile" && response.result.packet_path) root.profilePlan = response.result.packet_path
        } else root.notice = String(response.detail || response.reason || response.error || response.phase || response.status || "No job status returned")
    }
    function cancelWorkflow() {
        if (!root.busy || !root.jobId) return false
        var response = root.request("game_cancel", {job_id:root.jobId})
        if (response.status === "COMPLETE") root.poll()
        else {
            root.jobState = String(response.status || "ERROR")
            root.notice = response.status === "CANCELLED" ? "Workflow cancelled." : String(response.detail || response.reason || response.error || response.status || "Cancellation failed")
            if (root.jobState === "RUNNING" || root.jobState === "QUEUED") {
                root.jobState = "CANCELLING"
                root.notice = "Cancelling workflow…"
            }
        }
        return root.jobState === "CANCELLED" || root.jobState === "CANCELLING"
    }
    function useLastAnalysis() {
        var history = root.request("lab_history", {}).jobs || []
        for (var i = 0; i < history.length; i++) {
            var item = history[i]
            if (item.status === "COMPLETE" && ["function", "decompile", "xrefs"].indexOf(item.operation) >= 0) {
                root.run("context_job", {job_id:item.job_id})
                return
            }
        }
        root.notice = "Run a function or decompile analysis in REVERSE first, or select an offline Ghidra export."
    }
    function toggleKey(key, checked) {
        var values = root.selectedKeys.slice()
        var index = values.indexOf(key)
        if (checked && index < 0 && values.length < 24) values.push(key)
        if (!checked && index >= 0) values.splice(index, 1)
        root.selectedKeys = values
    }
    function browseFile(target) { root.browseTarget = target; fileDialog.open() }
    function browseFolder(target) { root.browseTarget = target; folderDialog.open() }
    function indexCollection() {
        root.run("scout_batch", {path:root.sourcePath, game:root.gameLabel, cursor:root.indexCursor,
                  recursive:root.collectionRecursive, partition:root.collectionPartition, partitions:root.collectionPartitions})
    }
    Timer { interval:500; repeat:true; running:root.busy; onTriggered:root.poll() }
    FileDialog { id:fileDialog; title:"SELECT LOCAL WORKFLOW INPUT"; fileMode:FileDialog.OpenFile
        onAccepted: {
            root[root.browseTarget] = String(selectedFile)
            if (root.stage === 0 && root.browseTarget === "targetPath")
                root.run("scout_inspect", {path:String(selectedFile), native:root.nativeReader})
        } }
    FolderDialog { id:folderDialog; title:"SELECT LOCAL WORKFLOW DIRECTORY"
        onAccepted: {
            root[root.browseTarget] = String(selectedFolder)
            if (root.browseTarget === "sourcePath") {
                root.collectionRecursive = true; root.collectionPartition = 0; root.collectionPartitions = 1
            }
        } }

    Rectangle { anchors.fill:parent; color:RuntimeTheme.GGTheme.panel }
    ColumnLayout {
        anchors.fill: parent
        spacing: 8
        RowLayout {
            Layout.fillWidth: true
            GGText { colorKey: "ui.ResearchGamesSurface.1"; text:"GAME WORKFLOWS"; color:RuntimeTheme.GGTheme.text; font.family:"monospace"; font.bold:true; font.pixelSize:14 }
            ComboBox { property string uiColorScope: "ui.control.ResearchGamesSurface.1"; id:stagePicker; objectName:"gameWorkflowStage"; model:["Scout assets", "Function context", "Review candidate", "Author routes", "Rig trial", "Scene profile"]
                currentIndex:root.stage; onActivated:root.stage = currentIndex; Layout.fillWidth:true; Layout.minimumWidth:0 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignLeft }
}
            GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.2"; objectName:"gameCancelWorkflow"; text:"CANCEL"; enabled:root.busy && root.jobState !== "CANCELLING"; onClicked:root.cancelWorkflow() }
        }
        GGText { colorKey: "ui.ResearchGamesSurface.2"; Layout.fillWidth:true; text:root.stage === 0 ? "Discover → search → inspect → collect evidence. Use the same steps for any game."
                : root.stage === 1 ? "Collect pseudocode, references, types and available IR around one function. Keep missing evidence explicit."
                : root.stage === 2 ? "Preserve a candidate separately. Check structure and optional C syntax; behavior needs an independent test."
                : root.stage === 3 ? "Edit explicit route identities and connections. NPC, patrol, flight and vehicle routes share the graph workflow."
                : root.stage === 4 ? "Check aliases, parent hierarchy, bind matrices and preserved attributes. Review source poses before mapping a GG rig."
                : "Compare source material groups, visibility and an existing LOD. Measured Qt counters remain separate from model counts."
            color:RuntimeTheme.GGTheme.positive; font.family:"monospace"; font.pixelSize:11; wrapMode:Text.WordWrap }

        StackLayout {
            currentIndex:root.stage
            Layout.fillWidth:true
            Layout.fillHeight:false
            Layout.preferredHeight: root.stage === 1 || root.stage === 4 ? 154 : 118
            Layout.maximumHeight: Layout.preferredHeight
            ColumnLayout {
                RowLayout { Layout.fillWidth:true
                    GgField { property string uiColorScope: "ui.widget.ResearchGamesSurface.GgField.2"; objectName:"gameScoutPath"; Layout.fillWidth:true; text:root.sourcePath; readOnly:root.busy || root.indexCursor.length > 0;
                        placeholderText:"Local directory of extracted assets"; onTextEdited:{root.sourcePath = text;root.collectionRecursive = true;root.collectionPartition = 0;root.collectionPartitions = 1} }
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.3"; text:"FOLDER"; enabled:!root.busy && root.indexCursor.length === 0; onClicked:root.browseFolder("sourcePath") }
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.4"; text:root.indexCursor.length > 0 ? "NEXT BATCH" : "INDEX"; objectName:"gameScoutIndex"; enabled:!root.busy && root.sourcePath.length > 0;
                        onClicked:root.indexCollection() }
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.5"; text:"COLLECTIONS"; objectName:"gameScoutCollections"; enabled:!root.busy && root.sourcePath.length > 0;
                        onClicked:root.run("scout_collections", {path:root.sourcePath}) }
                }
                RowLayout { Layout.fillWidth:true
                    GgField { property string uiColorScope: "ui.widget.ResearchGamesSurface.GgField.6"; objectName:"gameScoutLabel"; Layout.preferredWidth:155; text:root.gameLabel; readOnly:root.busy || root.indexCursor.length > 0;
                        placeholderText:"Game label / filter"; onTextEdited:root.gameLabel = text }
                    GgField { property string uiColorScope: "ui.widget.ResearchGamesSurface.GgField.7"; objectName:"gameScoutQuery"; Layout.fillWidth:true; text:root.query; placeholderText:"Name, material, category or annotation"; onTextEdited:root.query = text }
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.6"; text:"SEARCH"; objectName:"gameScoutSearch"; enabled:!root.busy; onClicked:root.run("scout_search", {query:root.query, game:root.gameLabel}) }
                }
                RowLayout { Layout.fillWidth:true
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.7"; text:"OPEN ASSET"; enabled:!root.busy; onClicked:root.browseFile("targetPath") }
                    CheckBox { property string uiColorScope: "ui.control.ResearchGamesSurface.8"; text:"WoW reader"; checked:root.nativeReader; enabled:!root.busy; onToggled:root.nativeReader = checked 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignLeft;withIndicator:true }
}
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.9"; text:"CONTACT SHEET"; enabled:!root.busy && root.selectedKeys.length > 0;
                        onClicked:root.run("scout_visual", {keys:root.selectedKeys}) }
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.10"; text:"DISCARD BATCHES"; visible:root.indexCursor.length > 0; enabled:!root.busy;
                        onClicked:root.run("scout_batch_cancel", {cursor:root.indexCursor}) }
                    GGText { colorKey: "ui.ResearchGamesSurface.3"; Layout.fillWidth:true; Layout.minimumWidth:0; text:"Select up to 24 matches. Exact-byte duplicates retain their original locations."; color:"#89939d"; font.family:"monospace"; font.pixelSize:10; wrapMode:Text.WordWrap }
                }
            }
            ColumnLayout {
                RowLayout { Layout.fillWidth:true
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.11"; text:"USE LAST FUNCTION ANALYSIS"; objectName:"gameContextLast"; enabled:!root.busy; onClicked:root.useLastAnalysis() }
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.12"; text:"OPEN REVERSE"; objectName:"gameOpenReverse"; onClicked:root.analysisRequested(root.targetPath) }
                }
                RowLayout { Layout.fillWidth:true
                    GgField { property string uiColorScope: "ui.widget.ResearchGamesSurface.GgField.14"; Layout.fillWidth:true; text:root.exportPath; placeholderText:"Offline function JSON or export directory"; onTextEdited:root.exportPath = text }
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.13"; text:"FILE"; onClicked:root.browseFile("exportPath") }
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.14"; text:"FOLDER"; onClicked:root.browseFolder("exportPath") }
                }
                RowLayout { Layout.fillWidth:true
                    GgField { property string uiColorScope: "ui.widget.ResearchGamesSurface.GgField.17"; Layout.fillWidth:true; text:root.targetPath; placeholderText:"Original binary / artifact for this export"; onTextEdited:root.targetPath = text }
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.15"; text:"FILE"; onClicked:root.browseFile("targetPath") }
                }
                RowLayout { Layout.fillWidth:true
                    GgField { property string uiColorScope: "ui.widget.ResearchGamesSurface.GgField.19"; Layout.fillWidth:true; text:root.functionQuery; placeholderText:"Exact function name or address with address space"; onTextEdited:root.functionQuery = text }
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.16"; text:"CONTEXT"; enabled:!root.busy && root.exportPath.length > 0 && root.targetPath.length > 0 && root.functionQuery.length > 0;
                        onClicked:root.run("context_export", {path:root.exportPath, target:root.targetPath, query:root.functionQuery}) }
                }
            }
            ColumnLayout {
                RowLayout { Layout.fillWidth:true
                    GgField { property string uiColorScope: "ui.widget.ResearchGamesSurface.GgField.21"; objectName:"gameCandidateContext"; Layout.fillWidth:true; text:root.contextPath; placeholderText:"Saved function context packet"; onTextEdited:root.contextPath = text }
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.17"; text:"CONTEXT FILE"; onClicked:root.browseFile("contextPath") }
                }
                RowLayout { Layout.fillWidth:true
                    GgField { property string uiColorScope: "ui.widget.ResearchGamesSurface.GgField.23"; objectName:"gameCandidateSource"; Layout.fillWidth:true; text:root.candidatePath; placeholderText:"One proposed C/C++ function"; onTextEdited:root.candidatePath = text }
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.18"; text:"SOURCE FILE"; onClicked:root.browseFile("candidatePath") }
                }
                RowLayout { Layout.fillWidth:true
                    CheckBox { property string uiColorScope: "ui.control.ResearchGamesSurface.19"; id:syntaxCheck; text:"Isolated C11 syntax check" 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignLeft;withIndicator:true }
}
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.20"; text:"REVIEW"; objectName:"gameCandidateReview"; enabled:!root.busy && root.contextPath.length > 0 && root.candidatePath.length > 0;
                        onClicked:root.run("verify_candidate", {context:root.contextPath, candidate:root.candidatePath, syntax:syntaxCheck.checked}) }
                }
            }
            ColumnLayout {
                RowLayout { Layout.fillWidth:true
                    GgField { property string uiColorScope: "ui.widget.ResearchGamesSurface.GgField.26"; objectName:"gameFlowPath"; Layout.fillWidth:true; text:root.flowPath; placeholderText:"Generic route graph or GG world/settlement JSON"; onTextEdited:root.flowPath = text }
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.21"; text:"FILE"; onClicked:root.browseFile("flowPath") }
                }
                Flow { Layout.fillWidth:true; spacing:6
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.22"; text:"IMPORT"; objectName:"gameFlowImport"; enabled:!root.busy && root.flowPath.length > 0; onClicked:root.run("flow_import", {path:root.flowPath, game:root.gameLabel}) }
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.23"; text:"CHECK / COMPILE"; objectName:"gameFlowCheck"; enabled:!root.busy && root.flowPath.length > 0; onClicked:root.run("flow_check", {path:root.flowPath}) }
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.24"; text:"EXPORT GG MAP CANDIDATE"; objectName:"gameFlowExport"; enabled:!root.busy && root.flowPath.length > 0; onClicked:root.run("flow_export", {path:root.flowPath}) }
                }
                GGText { colorKey: "ui.ResearchGamesSurface.4"; Layout.fillWidth:true; text:"Blender: tools/blender/gg_game_workflow_routes.py imports tagged editable curves and previews exports.";
                    color:"#89939d"; font.family:"monospace"; font.pixelSize:10; wrapMode:Text.WordWrap }
            }
            ColumnLayout {
                RowLayout { Layout.fillWidth:true
                    GgField { property string uiColorScope: "ui.widget.ResearchGamesSurface.GgField.31"; objectName:"gameRigSource"; Layout.fillWidth:true; text:root.targetPath; placeholderText:"Skinned DAE source"; onTextEdited:root.targetPath = text }
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.25"; text:"DAE"; onClicked:root.browseFile("targetPath") }
                }
                RowLayout { Layout.fillWidth:true
                    GgField { property string uiColorScope: "ui.widget.ResearchGamesSurface.GgField.33"; objectName:"gameRigAnimation"; Layout.fillWidth:true; text:root.animationPath; placeholderText:"Matching SMD animation"; onTextEdited:root.animationPath = text }
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.26"; text:"SMD"; onClicked:root.browseFile("animationPath") }
                }
                RowLayout { Layout.fillWidth:true
                    GgField { property string uiColorScope: "ui.widget.ResearchGamesSurface.GgField.35"; objectName:"gameRigFps"; Layout.preferredWidth:100; text:root.rigFps; placeholderText:"Explicit FPS"; onTextEdited:root.rigFps = text }
                    ComboBox { property string uiColorScope: "ui.control.ResearchGamesSurface.27"; objectName:"gameRigBasis"; Layout.fillWidth:true; model:["Choose SMD basis", "Source local", "Root +90° X trial"]
                        currentIndex:root.rigBasis === "SMD_LOCAL" ? 1 : root.rigBasis === "SMD_ROOT_X90" ? 2 : 0
                        onActivated:root.rigBasis = currentIndex === 1 ? "SMD_LOCAL" : currentIndex === 2 ? "SMD_ROOT_X90" : "" 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignLeft }
}
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.28"; objectName:"gameRigTrial"; text:"CREATE TRIAL"; enabled:!root.busy && root.targetPath.length > 0 && root.animationPath.length > 0 && Number(root.rigFps) > 0 && root.rigBasis.length > 0;
                        onClicked:root.run("rig_trial", {path:root.targetPath, animation:root.animationPath, fps:Number(root.rigFps), basis:root.rigBasis}) }
                }
                GGText { colorKey: "ui.ResearchGamesSurface.5"; Layout.fillWidth:true; text:"FPS is caller supplied. Bind/first/middle/last poses and material layers need Blender review; semantic retarget stays pending.";
                    color:RuntimeTheme.GGTheme.accent; font.family:"monospace"; font.pixelSize:10; wrapMode:Text.WordWrap }
            }
            ColumnLayout {
                RowLayout { Layout.fillWidth:true
                    GgField { property string uiColorScope: "ui.widget.ResearchGamesSurface.GgField.37"; Layout.fillWidth:true; text:root.targetPath; placeholderText:"Packaged GLB / glTF full model"; onTextEdited:root.targetPath = text }
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.29"; text:"MODEL"; onClicked:root.browseFile("targetPath") }
                }
                RowLayout { Layout.fillWidth:true
                    GgField { property string uiColorScope: "ui.widget.ResearchGamesSurface.GgField.39"; Layout.fillWidth:true; text:root.profileLodPath; placeholderText:"Optional existing LOD model"; onTextEdited:root.profileLodPath = text }
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.30"; text:"LOD"; onClicked:root.browseFile("profileLodPath") }
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.31"; objectName:"gameAssetProfile"; text:"PREPARE MEASUREMENT"; enabled:!root.busy && root.targetPath.length > 0;
                        onClicked:root.run("asset_profile", {assets:[{path:root.targetPath, lod_path:root.profileLodPath}]}) }
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.32"; objectName:"gameSceneMeasure"; text:"MEASURE QT"; enabled:!root.busy && root.profilePlan.length > 0;
                        onClicked:root.run("scene_measure", {path:root.profilePlan}) }
                }
                GGText { colorKey: "ui.ResearchGamesSurface.6"; Layout.fillWidth:true; text:"The scene profiler measures full / visibility / LOD in a separate Qt window. A prepared plan has no measured GPU result yet.";
                    color:RuntimeTheme.GGTheme.accent; font.family:"monospace"; font.pixelSize:10; wrapMode:Text.WordWrap }
            }
        }

        GGText { colorKey: "ui.ResearchGamesSurface.7"; Layout.fillWidth:true; text:root.notice; textFormat:Text.PlainText; color:root.result.status === "ERROR" || root.result.status === "FAIL" ? "#d69292" : RuntimeTheme.GGTheme.text;
            font.family:"monospace"; font.pixelSize:11; wrapMode:Text.WordWrap }
        ResearchFrame { property string uiColorScope: "ui.widget.ResearchGamesSurface.ResearchFrame.43";
            Layout.fillWidth:true
            Layout.fillHeight:true
            leftLegend:"RESULTS / SOURCE EVIDENCE"
            ScrollView {
                id:resultScroll
                anchors.fill:parent; anchors.margins:10; contentWidth:availableWidth; clip:true
                Column {
                    width:resultScroll.availableWidth
                    spacing:8
                    Repeater {
                        model:root.result.collections || []
                        delegate:RowLayout {
                            required property var modelData
                            width:parent.width
                            GGText { colorKey: "ui.ResearchGamesSurface.8"; Layout.fillWidth:true; text:modelData.relative + " · " + modelData.files + " files"; textFormat:Text.PlainText; color:RuntimeTheme.GGTheme.text; font.family:"monospace"; elide:Text.ElideMiddle }
                            GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.33"; text:"INDEX COLLECTION"; enabled:!root.busy && root.indexCursor.length === 0; onClicked:{
                                root.sourcePath = modelData.path; root.collectionRecursive = modelData.recursive !== false
                                root.collectionPartition = Number(modelData.partition || 0); root.collectionPartitions = Number(modelData.partitions || 1)
                                root.indexCollection()
                            } }
                        }
                    }
                    Repeater {
                        model:root.result.hits || []
                        delegate:Rectangle {
                            required property var modelData
                            width:parent.width; height:72; color:RuntimeTheme.GGTheme.raised; border.color:RuntimeTheme.GGTheme.edge
                            RowLayout { anchors.fill:parent; anchors.margins:6
                                CheckBox { property string uiColorScope: "ui.control.ResearchGamesSurface.34"; checked:root.selectedKeys.indexOf(modelData.key) >= 0; onToggled:root.toggleKey(modelData.key, checked) 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignLeft;withIndicator:true }
}
                                ColumnLayout { Layout.fillWidth:true; Layout.minimumWidth:0; spacing:3
                                    GGText { colorKey: "ui.ResearchGamesSurface.9"; Layout.fillWidth:true; text:modelData.relative; textFormat:Text.PlainText; color:RuntimeTheme.GGTheme.text; font.family:"monospace"; font.pixelSize:11; elide:Text.ElideMiddle }
                                    GGText { colorKey: "ui.ResearchGamesSurface.10"; Layout.fillWidth:true; text:modelData.game + " · " + modelData.format + " · " + modelData.coverage + " · " + modelData.duplicates + " locations";
                                        color:RuntimeTheme.GGTheme.positive; font.family:"monospace"; font.pixelSize:10; elide:Text.ElideRight }
                                }
                                GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.35"; text:"INSPECT"; enabled:!root.busy; onClicked:{ root.targetPath = modelData.path; root.run("scout_inspect", {path:modelData.path, native:root.nativeReader}) } }
                                GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.36"; text:"LINKS"; enabled:!root.busy; onClicked:root.run("scout_relations", {key:modelData.key}) }
                                GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.37"; text:"ANALYZE"; onClicked:root.analysisRequested(modelData.path) }
                            }
                        }
                    }
                    Image { visible:String(root.result.image || "").length > 0; width:parent.width; height:visible ? 340 : 0;
                        source:root.result.image || ""; fillMode:Image.PreserveAspectFit; asynchronous:true }
                    Basic.TextArea { visible:!!root.result.packet_path; width:parent.width; text:String(root.result.packet_path || ""); textFormat:TextEdit.PlainText; readOnly:true; selectByMouse:true;
                        color:RuntimeTheme.GGTheme.positive; font.family:"monospace"; font.pixelSize:11; wrapMode:TextArea.WrapAnywhere; background:Rectangle { color:RuntimeTheme.GGTheme.canvas } }
                    GGText { colorKey: "ui.ResearchGamesSurface.11"; visible:!!root.result.context; width:parent.width; text:root.result.context ? String(root.result.context.provenance || "") + "\n" + String(root.contextFunction.name || root.contextFunction.address || "No function available") : "";
                        color:RuntimeTheme.GGTheme.accent; font.family:"monospace"; font.pixelSize:12; textFormat:Text.PlainText; wrapMode:Text.WordWrap }
                    Basic.TextArea { visible:!!root.result.context; width:parent.width; text:root.result.context ? String(root.contextFunction.pseudocode || "No pseudocode available in this evidence.") : ""; textFormat:TextEdit.PlainText;
                        readOnly:true; selectByMouse:true; color:RuntimeTheme.GGTheme.text; font.family:"monospace"; font.pixelSize:12; wrapMode:TextArea.Wrap; background:Rectangle { color:RuntimeTheme.GGTheme.canvas } }
                    GGText { colorKey: "ui.ResearchGamesSurface.12"; visible:!!root.result.gates; width:parent.width; text:root.result.gates ? Object.keys(root.result.gates).map(function(key) { return key + ": " + String((root.result.gates[key] || {}).state || "UNKNOWN") }).join("\n") : "";
                        color:RuntimeTheme.GGTheme.accent; font.family:"monospace"; font.pixelSize:11; textFormat:Text.PlainText; wrapMode:Text.WordWrap }
                    GGText { colorKey: "ui.ResearchGamesSurface.13"; visible:!!root.result.oracle; width:parent.width; text:root.result.oracle ? (root.result.oracle.valid ? "Independent graph check passed. " : "Graph check failed. ") + (root.result.oracle.warnings || []).join("\n") + "\nEngine behavior has not been tested." : "";
                        color:RuntimeTheme.GGTheme.positive; font.family:"monospace"; font.pixelSize:11; textFormat:Text.PlainText; wrapMode:Text.WordWrap }
                    GGText { colorKey: "ui.ResearchGamesSurface.14"; width:parent.width; text:(root.result.limits || []).join("\n"); color:RuntimeTheme.GGTheme.accent; font.family:"monospace"; font.pixelSize:10; wrapMode:Text.WordWrap; textFormat:Text.PlainText }
                    GgButton { property string uiColorScope: "ui.control.ResearchGamesSurface.38"; text:root.showDetails ? "HIDE DETAILS" : "SHOW DETAILS"; onClicked:root.showDetails = !root.showDetails }
                    Basic.TextArea { visible:root.showDetails; width:parent.width; text:root.showDetails ? JSON.stringify(root.result, null, 2).slice(0, 65536) : ""; textFormat:TextEdit.PlainText; readOnly:true; selectByMouse:true;
                        color:RuntimeTheme.GGTheme.muted; font.family:"monospace"; font.pixelSize:10; wrapMode:TextArea.WrapAnywhere; background:Rectangle { color:RuntimeTheme.GGTheme.canvas } }
                }
            }
        }
    }
}
