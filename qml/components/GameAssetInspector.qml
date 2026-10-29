pragma ComponentBehavior: Bound

import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

Column {
    id: panel
    required property var controller
    readonly property var state: controller.assetEditorState || ({})
    readonly property var selected: state.selected || ({})
    readonly property var detail: selected.detail || ({})
    readonly property var ownEdit: selected.edit || ({})
    readonly property var material: (detail.materials || [])[materialPicker.currentIndex] || ({})
    readonly property int materialIndex: material.index !== undefined ? material.index : -1
    readonly property var materialEdit: (ownEdit.materials || ({}))[String(materialIndex)] || ({})
    property string browserTab: "SCENE"
    property bool browserOpen: true
    property string section: "INFO"
    property string brushColor: "#f4d9a4"
    property bool paintEnabled: false
    property bool showUv: true
    property bool showAllUv: true
    property var uvView: [0,0,1,1]
    property string imageRole: "baseColor"
    property var imageInfo: ({})
    property string imageError: ""
    property var stroke: []
    property bool imageUpdating: false
    property string imageStamp: String(selected.key || "")+":"+materialIndex+":"+imageRole+":"+String(state.revision || 0)
    readonly property var uvSet: (detail.uv_sets || [])[uvPicker.currentIndex] || ({})
    readonly property var uvJob: state.uv_job || ({})
    readonly property var sceneRows: state.scene || []
    readonly property var libraryRows: state.library || []
    readonly property var filteredRows: {
        var term = assetSearch.text.toLowerCase()
        var source = browserTab === "SCENE" ? sceneRows : libraryRows
        return source.filter(function(row) {
            return !term || String(row.name || "").toLowerCase().indexOf(term)>=0
                || String(row.path || row.kind || "").toLowerCase().indexOf(term)>=0
        })
    }
    spacing: 9
    objectName: "gameAssetInspector"

    function command(value) { return controller.assetEdit(value) }
    function chooseTextureUv() {
        var maps=material.maps || [],name="TEXCOORD_0"
        for(var i=0;i<maps.length;i++)if(maps[i].role===imageRole){name="TEXCOORD_"+maps[i].uv;break}
        var sets=detail.uv_sets || []
        for(var j=0;j<sets.length;j++)if(sets[j].name===name){uvPicker.currentIndex=j;break}
        uvCanvas.requestPaint()
    }
    function fitUv() {
        var edges=uvSet.edges || [],minU=Infinity,minV=Infinity,maxU=-Infinity,maxV=-Infinity
        for(var i=0;i<edges.length;i++){
            var e=edges[i];if(e[4]!==materialIndex)continue
            minU=Math.min(minU,e[0],e[2]);minV=Math.min(minV,e[1],e[3])
            maxU=Math.max(maxU,e[0],e[2]);maxV=Math.max(maxV,e[1],e[3])
        }
        if(isFinite(minU)){var span=Math.max(.01,maxU-minU,maxV-minV)*1.12
            uvView=[(minU+maxU-span)/2,(minV+maxV-span)/2,span,span]}
        else uvView=[0,0,1,1]
        uvCanvas.requestPaint()
    }
    function refreshImage() {
        if (materialIndex<0 || !selected.source) {imageInfo=({});imageError="";return}
        imageUpdating=true
        var response=command({op:"IMAGE",material:materialIndex,role:imageRole})
        imageInfo=response && response.selected ? response.selected.image || ({}) : ({})
        imageError=response && response.selected ? response.selected.image_error || "" : ""
        imageUpdating=false
        chooseTextureUv()
        uvCanvas.requestPaint()
    }
    onImageStampChanged: if (!imageUpdating) Qt.callLater(refreshImage)
    onUvSetChanged: uvCanvas.requestPaint()
    onShowUvChanged: uvCanvas.requestPaint()
    onShowAllUvChanged: uvCanvas.requestPaint()
    onUvViewChanged: uvCanvas.requestPaint()
    onSelectedChanged:if(selected.key)browserOpen=false
    Component.onCompleted: Qt.callLater(refreshImage)
    Timer {interval:500;repeat:true;running:!!panel.uvJob.busy;onTriggered:panel.command({op:"UV_STATUS"})}

    GGText { colorKey: "ui.GameAssetInspector.1";
        text: "ASSETREDIGERARE"+(panel.state.dirty ? "  • ej sparat" : "")
        color: panel.controller.ledgerGold; font.bold:true; font.pixelSize:13
    }
    GGText { colorKey: "ui.GameAssetInspector.2";
        visible:panel.browserOpen;width:parent.width; wrapMode:Text.WordWrap; color:panel.controller.muted; font.pixelSize:11
        text:"Klicka på ett objekt i världen. Dra med Flytta eller ändra värden nedan. Biblioteket innehåller modellfilerna."
    }
    Row {
        spacing:5
        GgButton { property string uiColorScope: "ui.control.GameAssetInspector.1";text:"SCEN";checked:panel.browserTab==="SCENE";onClicked:panel.browserTab="SCENE"}
        GgButton { property string uiColorScope: "ui.control.GameAssetInspector.2";text:"BIBLIOTEK";checked:panel.browserTab==="LIBRARY";onClicked:panel.browserTab="LIBRARY"}
        GgButton { property string uiColorScope: "ui.control.GameAssetInspector.3";text:"↻";implicitWidth:30;onClicked:panel.command({op:"REFRESH"})}
        GgButton { property string uiColorScope: "ui.control.GameAssetInspector.4";text:panel.browserOpen ? "DÖLJ LISTA" : "VÄLJ ASSET";onClicked:panel.browserOpen=!panel.browserOpen}
    }
    TextField {id:assetSearch;visible:panel.browserOpen;objectName:"gameAssetSearch";width:parent.width;placeholderText:"Sök assets…";font.pixelSize:12}
    ListView {
        id:assetList;visible:panel.browserOpen;objectName:"gameAssetLibrary";width:parent.width;height:160;clip:true
        model:panel.filteredRows
        ScrollBar.vertical:ScrollBar {}
        delegate:Rectangle {
            id:assetRow;required property var modelData;required property int index
            width:assetList.width; height:35
            color: (panel.selected.identity && panel.selected.identity===modelData.identity)
                || (!panel.selected.identity && panel.selected.source===modelData.source)
                ? panel.controller.selectedPanel : index%2 ? "#202729" : "#192022"
            GGText { colorKey: "ui.GameAssetInspector.3";anchors.left:parent.left;anchors.right:parent.right;anchors.margins:6;anchors.verticalCenter:parent.verticalCenter
                elide:Text.ElideRight;font.pixelSize:11;color:panel.controller.text
                text:String(assetRow.modelData.name || "Asset")+"\n"+String(assetRow.modelData.path || assetRow.modelData.kind || "")}
            MouseArea {anchors.fill:parent;cursorShape:Qt.PointingHandCursor
                onClicked:{panel.paintEnabled=false;materialPicker.currentIndex=0
                    panel.command(panel.browserTab==="SCENE" ? {op:"SELECT",identity:assetRow.modelData.identity}
                                  : {op:"SELECT_ASSET",source:assetRow.modelData.source})}}
        }
    }
    Row {
        spacing:5
        GgButton { property string uiColorScope: "ui.control.GameAssetInspector.5";text:"SPARA";objectName:"gameAssetSave";enabled:panel.state.dirty;onClicked:panel.command({op:"SAVE"})}
        GgButton { property string uiColorScope: "ui.control.GameAssetInspector.6";text:"ÅNGRA";objectName:"gameAssetUndo";enabled:panel.state.undo>0;onClicked:panel.command({op:"UNDO"})}
        GgButton { property string uiColorScope: "ui.control.GameAssetInspector.7";text:"GÖR OM";enabled:panel.state.redo>0;onClicked:panel.command({op:"REDO"})}
        GgButton { property string uiColorScope: "ui.control.GameAssetInspector.8";text:"ÖPPNA";onClicked:panel.command({op:"LOAD"})}
    }
    GGText { colorKey: "ui.GameAssetInspector.4";width:parent.width;wrapMode:Text.WordWrap;font.pixelSize:11
        color:panel.controller.assetEditorError ? panel.controller.signalRed : panel.controller.ledgerGreen
        text:panel.controller.assetEditorError || panel.state.notice || ""}
    Rectangle {width:parent.width;height:1;color:panel.controller.frameBorder}
    GGText { colorKey: "ui.GameAssetInspector.5";visible:!panel.selected.key;width:parent.width;wrapMode:Text.WordWrap;color:panel.controller.muted;font.pixelSize:12
        text:"Välj en asset för information, UV, material och redigering."}

    Column {
        width:parent.width;spacing:8;visible:!!panel.selected.key
        GGText { colorKey: "ui.GameAssetInspector.6";width:parent.width;wrapMode:Text.Wrap;color:panel.controller.ledgerGold;font.bold:true;font.pixelSize:13
            text:panel.selected.name || "Asset"}
        GGText { colorKey: "ui.GameAssetInspector.7";width:parent.width;wrapMode:Text.Wrap;color:panel.controller.muted;font.pixelSize:11
            text:(panel.selected.scope==="INSTANCE" ? "Detta objekt" : "Asset i biblioteket — alla objekt som använder den")
                +"\n"+String(panel.detail.format || "")+" · "+String(panel.detail.vertices || "–")+" vertices · "
                +String(panel.detail.triangles || "–")+" trianglar"
                +"\n"+String(panel.detail.joints || 0)+" ben · "+String((panel.detail.clips || []).length)+" animationer"
                +(panel.detail.message ? "\n"+panel.detail.message : "")}
        Row {
            spacing:4
            GgButton { property string uiColorScope: "ui.control.GameAssetInspector.9";text:"INFO";checked:panel.section==="INFO";onClicked:panel.section="INFO"}
            GgButton { property string uiColorScope: "ui.control.GameAssetInspector.10";text:"FLYTTA";visible:panel.selected.scope==="INSTANCE";checked:panel.section==="TRANSFORM";onClicked:panel.section="TRANSFORM"}
            GgButton { property string uiColorScope: "ui.control.GameAssetInspector.11";text:"UV / MÅLA";checked:panel.section==="UV";onClicked:panel.section="UV"}
            GgButton { property string uiColorScope: "ui.control.GameAssetInspector.12";text:"GEAR";visible:panel.detail.joints>0 || ["PLAYER","NPC","ACTOR"].indexOf(String((panel.selected.entity || {}).kind))>=0
                checked:panel.section==="GEAR";onClicked:panel.section="GEAR"}
        }
        GgButton { property string uiColorScope: "ui.control.GameAssetInspector.13";text:"PLACERA I SCENEN";visible:panel.selected.scope==="ASSET" && panel.detail.format!=="GGMESH";onClicked:panel.command({op:"PLACE"})}

        Column {
            width:parent.width;spacing:6;visible:panel.section==="TRANSFORM" && panel.selected.scope==="INSTANCE"
            GGText { colorKey: "ui.GameAssetInspector.8";text:"TRANSFORM";color:panel.controller.ledgerGold;font.bold:true;font.pixelSize:11}
            Row {
                spacing:5
                GgButton { property string uiColorScope: "ui.control.GameAssetInspector.14";text:"VÄLJ";checked:panel.controller.assetTool==="SELECT";onClicked:panel.controller.assetTool="SELECT"}
                GgButton { property string uiColorScope: "ui.control.GameAssetInspector.15";text:"FLYTTA";checked:panel.controller.assetTool==="MOVE";onClicked:panel.controller.assetTool="MOVE"}
                GgButton { property string uiColorScope: "ui.control.GameAssetInspector.16";text:"DUPLICERA";onClicked:panel.command({op:"DUPLICATE"})}
            }
            GGText { colorKey: "ui.GameAssetInspector.9";width:parent.width;wrapMode:Text.WordWrap;color:panel.controller.muted;font.pixelSize:11
                text:"Flytta: dra objektet på markplanet. Position anges i meter och rotation i grader."}
            Repeater {
                model:[{label:"POSITION",keys:["x","y","z"],defaults:[0,0,0]},
                       {label:"ROTATION",keys:["pitch","yaw","roll"],defaults:[0,0,0]},
                       {label:"SKALA",keys:["sx","sy","sz"],defaults:[1,1,1]}]
                delegate:Column {
                    id:transformGroup;required property var modelData;width:panel.width;spacing:3
                    GGText { colorKey: "ui.GameAssetInspector.10";text:transformGroup.modelData.label;color:panel.controller.muted;font.pixelSize:10}
                    Row {
                        spacing:4;width:parent.width
                        Repeater {
                            model:transformGroup.modelData.keys
                            delegate:TextField {
                                id:valueField;required property string modelData;required property int index
                                width:(panel.width-8)/3;implicitHeight:30;font.pixelSize:11;selectByMouse:true
                                property bool userModified: false
                                onTextEdited: userModified=true
                                readonly property var values:panel.ownEdit.transform || ({})
                                readonly property real savedValue:values[modelData]!==undefined ? Number(values[modelData])
                                    : panel.selected.entity && panel.selected.entity[modelData]!==undefined
                                      ? Number(panel.selected.entity[modelData])*(modelData==="yaw" && panel.selected.entity.kind!=="FLORA" && panel.selected.entity.kind!=="NATURE" ? 57.295779513 : 1)
                                      : transformGroup.modelData.defaults[index]
                                placeholderText:modelData.toUpperCase()
                                text:savedValue.toFixed(3)
                                onEditingFinished:if(userModified){var v=({});v[modelData]=Number(text);panel.command({op:"TRANSFORM",values:v});userModified=false}
                            }
                        }
                    }
                }
            }
            Row {
                spacing:5
                GgButton { property string uiColorScope: "ui.control.GameAssetInspector.17";text:"DÖLJ";onClicked:panel.command({op:"VISIBILITY",hidden:!panel.ownEdit.hidden})}
                GgButton { property string uiColorScope: "ui.control.GameAssetInspector.18";text:"ÅTERSTÄLL";onClicked:panel.command({op:"RESET_SELECTED"})}
            }
        }

        Column {
            width:parent.width;spacing:7;visible:panel.section==="UV"
            GGText { colorKey: "ui.GameAssetInspector.11";text:"MATERIAL / FÄRG";color:panel.controller.ledgerGold;font.bold:true;font.pixelSize:11}
            ComboBox { property string uiColorScope: "ui.control.GameAssetInspector.19";id:materialPicker;objectName:"gameAssetMaterial";width:parent.width;textRole:"name";model:panel.detail.materials || []
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignLeft }
}
            Row {
                spacing:5;width:parent.width
                TextField {id:tintInput;width:parent.width-86;placeholderText:RuntimeTheme.GGTheme.bright;text:panel.materialEdit.color || panel.ownEdit.color || panel.material.color || RuntimeTheme.GGTheme.bright}
                GgButton { property string uiColorScope: "ui.control.GameAssetInspector.20";text:"FÄRG";implicitWidth:80;onClicked:panel.command({op:"MATERIAL",material:panel.materialIndex,color:tintInput.text})}
            }
            Row {
                width:parent.width;spacing:5;visible:panel.materialIndex>=0
                GGText { colorKey: "ui.GameAssetInspector.12";width:72;text:"Roughness";color:panel.controller.text;font.pixelSize:11;anchors.verticalCenter:parent.verticalCenter}
                Slider {width:parent.width-110;from:0;to:1;value:panel.materialEdit.roughness!==undefined ? panel.materialEdit.roughness : panel.material.roughness || 0
                    onPressedChanged:if(!pressed)panel.command({op:"MATERIAL",material:panel.materialIndex,roughness:value})}
            }
            Row {
                width:parent.width;spacing:5;visible:panel.materialIndex>=0
                GGText { colorKey: "ui.GameAssetInspector.13";width:72;text:"Metalness";color:panel.controller.text;font.pixelSize:11;anchors.verticalCenter:parent.verticalCenter}
                Slider {width:parent.width-110;from:0;to:1;value:panel.materialEdit.metalness!==undefined ? panel.materialEdit.metalness : panel.material.metalness || 0
                    onPressedChanged:if(!pressed)panel.command({op:"MATERIAL",material:panel.materialIndex,metalness:value})}
            }
        }

        Column {
            width:parent.width;spacing:5;visible:panel.section==="UV" && (panel.detail.format==="GLB" || panel.detail.format==="GLTF")
            GgButton { property string uiColorScope: "ui.control.GameAssetInspector.21";text:"FÖRBERED UV FÖR MÅLNING";objectName:"gameAssetPrepareUv"
                visible:!panel.detail.joints && !(panel.detail.clips || []).length
                enabled:!panel.uvJob.busy
                onClicked:{panel.paintEnabled=false;panel.uvView=[0,0,1,1];panel.command({op:"PREPARE_UV"})}}
            GGText { colorKey: "ui.GameAssetInspector.14";width:parent.width;wrapMode:Text.WordWrap;color:panel.controller.muted;font.pixelSize:11
                text:panel.uvJob.stage || "Packar separata UV-öar och överför befintliga färger. Modellens ytor behålls."}
            ProgressBar {
                id:uvProgress;objectName:"gameAssetUvProgress";width:parent.width;visible:!!panel.uvJob.busy;from:0;to:100;value:panel.uvJob.percent || 0
                contentItem:Item {
                    implicitHeight:6
                    Rectangle {
                        id:uvProgressFill;objectName:"gameAssetUvProgressFill";width:parent.width*uvProgress.visualPosition;height:parent.height;color:RuntimeTheme.GGTheme.accent
                    }
                    GGColorTarget {
                        target:uvProgressFill;colorKey:"ui.progress.asset.uv";percentageCapable:true
                        fraction:typeof panel.uvJob.percent==="number"&&isFinite(panel.uvJob.percent)&&uvProgress.to>uvProgress.from?(uvProgress.value-uvProgress.from)/(uvProgress.to-uvProgress.from):NaN
                    }
                }
            }
            GGText { colorKey: "ui.GameAssetInspector.15";visible:!!panel.uvJob.error;width:parent.width;wrapMode:Text.WordWrap;color:panel.controller.signalRed;font.pixelSize:11;text:panel.uvJob.error || ""}
        }

        Column {
            width:parent.width;spacing:7;visible:panel.section==="UV" && panel.materialIndex>=0 && (panel.detail.uv_sets || []).length>0
            GGText { colorKey: "ui.GameAssetInspector.16";text:"UV / TEXTUR";color:panel.controller.ledgerGold;font.bold:true;font.pixelSize:11}
            Row {
                width:parent.width;spacing:5
                ComboBox { property string uiColorScope: "ui.control.GameAssetInspector.22";id:uvPicker;width:parent.width*.48;textRole:"name";model:panel.detail.uv_sets || []
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignLeft }
}
                ComboBox { property string uiColorScope: "ui.control.GameAssetInspector.23";width:parent.width*.50;model:["baseColor","normal","ORM","occlusion","emissive"]
                    onActivated:panel.imageRole=currentText
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignLeft }
}
            }
            Row {
                spacing:5
                GgButton { property string uiColorScope: "ui.control.GameAssetInspector.24";text:"UV";checked:panel.showUv;onClicked:panel.showUv=!panel.showUv}
                GgButton { property string uiColorScope: "ui.control.GameAssetInspector.25";text:"MÅLA";objectName:"gameAssetPaintToggle";checked:panel.paintEnabled
                    enabled:panel.imageRole==="baseColor" && !!panel.imageInfo.url;onClicked:panel.paintEnabled=!panel.paintEnabled}
                GGText { colorKey: "ui.GameAssetInspector.17";text:panel.imageInfo.width ? panel.imageInfo.width+" × "+panel.imageInfo.height : ""
                    color:panel.controller.muted;font.pixelSize:10;anchors.verticalCenter:parent.verticalCenter}
            }
            Row {
                spacing:4
                GgButton { property string uiColorScope: "ui.control.GameAssetInspector.26";text:"PASSA UV";onClicked:panel.fitUv()}
                GgButton { property string uiColorScope: "ui.control.GameAssetInspector.27";text:"HELA KARTAN";onClicked:panel.uvView=[0,0,1,1]}
                GgButton { property string uiColorScope: "ui.control.GameAssetInspector.28";text:"ALLA";checked:panel.showAllUv;onClicked:panel.showAllUv=!panel.showAllUv}
            }
            GGText { colorKey: "ui.GameAssetInspector.18";width:parent.width;wrapMode:Text.WordWrap;color:panel.controller.muted;font.pixelSize:11
                text:"Gult: valt material. Blått: övriga ytor."
                    +(panel.uvSet.outside ? "\nUV går utanför kartan. Förbered UV för separata målningsytor." : "")
                    +(panel.uvSet.collapsed ? "\n"+panel.uvSet.collapsed+" trianglar saknar UV-yta." : "")}
            Rectangle {
                id:textureStage;width:parent.width;height:Math.max(90,Math.min(330,width*(panel.imageInfo.height || 1)/(panel.imageInfo.width || 1)))
                color:"#101517";border.color:panel.controller.frameBorder;clip:true
                Item {
                    id:textureArea;anchors.centerIn:parent
                    width:Math.min(textureStage.width,textureStage.height*(panel.imageInfo.width || 1)/(panel.imageInfo.height || 1))
                    height:width*(panel.imageInfo.height || 1)/(panel.imageInfo.width || 1)
                    Image {id:textureImage;x:-panel.uvView[0]*parent.width/panel.uvView[2];y:-panel.uvView[1]*parent.height/panel.uvView[3]
                        width:parent.width/panel.uvView[2];height:parent.height/panel.uvView[3]
                        source:panel.imageInfo.url || "";cache:false;fillMode:Image.Stretch;asynchronous:false}
                    Canvas {
                        id:uvCanvas;objectName:"gameAssetUvCanvas";anchors.fill:parent
                        onWidthChanged:requestPaint()
                        onHeightChanged:requestPaint()
                        onPaint:{var c=getContext("2d");c.clearRect(0,0,width,height)
                            function x(u){return (u-panel.uvView[0])*width/panel.uvView[2]}
                            function y(v){return (v-panel.uvView[1])*height/panel.uvView[3]}
                            if(panel.showUv){var edges=panel.uvSet.edges || []
                                for(var pass=0;pass<2;pass++){
                                    if(pass===0 && !panel.showAllUv)continue
                                    c.strokeStyle=pass===0 ? "#54b9de" : "#ffe060";c.lineWidth=pass===0 ? .8 : 1.5;c.globalAlpha=pass===0 ? .55 : 1;c.beginPath()
                                    for(var i=0;i<edges.length;i++){var e=edges[i];if((e[4]===panel.materialIndex)!==(pass===1))continue
                                        c.moveTo(x(e[0]),y(e[1]));c.lineTo(x(e[2]),y(e[3]))}c.stroke()}}
                            if(panel.stroke.length){c.globalAlpha=brushOpacity.value;c.strokeStyle=panel.brushColor;c.lineWidth=brushSize.value*width/panel.uvView[2]
                                c.lineCap="round";c.lineJoin="round";c.beginPath()
                                c.moveTo(x(panel.stroke[0][0]),y(panel.stroke[0][1]))
                                for(var p=1;p<panel.stroke.length;p++)c.lineTo(x(panel.stroke[p][0]),y(panel.stroke[p][1]))
                                if(panel.stroke.length===1)c.lineTo(x(panel.stroke[0][0])+.01,y(panel.stroke[0][1]));c.stroke()}
                            c.globalAlpha=1}
                    }
                    MouseArea {
                        id:paintMouse;anchors.fill:parent;enabled:panel.paintEnabled && !!panel.imageInfo.url
                        cursorShape:Qt.CrossCursor;preventStealing:true
                        function point(mouse){return [Math.max(0,Math.min(1,panel.uvView[0]+mouse.x/width*panel.uvView[2])),Math.max(0,Math.min(1,panel.uvView[1]+mouse.y/height*panel.uvView[3]))]}
                        onPressed:function(mouse){panel.stroke=[point(mouse)];uvCanvas.requestPaint()}
                        onPositionChanged:function(mouse){if(pressed && panel.stroke.length<2048){var next=point(mouse),last=panel.stroke[panel.stroke.length-1]
                            if(Math.hypot(next[0]-last[0],next[1]-last[1])>.001){panel.stroke=panel.stroke.concat([next]);uvCanvas.requestPaint()}}}
                        onReleased:{var points=panel.stroke;panel.stroke=[]
                            if(points.length)panel.command({op:"PAINT",material:panel.materialIndex,points:points,color:panel.brushColor,size:brushSize.value,opacity:brushOpacity.value})
                            uvCanvas.requestPaint()}
                        onCanceled:{panel.stroke=[];uvCanvas.requestPaint()}
                    }
                }
            }
            GGText { colorKey: "ui.GameAssetInspector.19";width:parent.width;wrapMode:Text.WordWrap;text:panel.imageError;color:panel.controller.muted;font.pixelSize:11;visible:text.length>0}
            Row {
                spacing:4;width:parent.width
                Repeater {
                    model:["positionU","positionV","scaleU","scaleV"]
                    delegate:TextField {
                        id:uvValue;required property string modelData;width:(panel.width-12)/4;implicitHeight:28;font.pixelSize:10
                        placeholderText:modelData;property bool userModified:false
                        text:String(panel.materialEdit[modelData]!==undefined ? panel.materialEdit[modelData] : modelData.indexOf("scale")===0 ? 1 : 0)
                        onTextEdited:userModified=true
                        onEditingFinished:if(userModified){var request={op:"MATERIAL",material:panel.materialIndex};request[modelData]=Number(text);panel.command(request);userModified=false}
                        ToolTip.visible:hovered;ToolTip.text:modelData
                    }
                }
            }
            Column {
                width:parent.width;spacing:4;visible:panel.paintEnabled
                TextField {width:parent.width;text:panel.brushColor;placeholderText:"Penselfärg #rrggbb";onEditingFinished:panel.brushColor=text}
                Row {
                    spacing:4
                    Repeater {model:["#f4d9a4","#c57626","#6d361d",RuntimeTheme.GGTheme.bright,"#151719","#75945b","#487dad"]
                        delegate:Rectangle {id:swatch;required property string modelData;width:26;height:24;color:modelData;border.color:"#b7b4a8"
                            MouseArea {anchors.fill:parent;onClicked:panel.brushColor=swatch.modelData}}}
                }
                GGText { colorKey: "ui.GameAssetInspector.20";text:"Penselstorlek";color:panel.controller.muted;font.pixelSize:10}
                Slider {id:brushSize;width:parent.width;from:.001;to:.12;value:.025}
                GGText { colorKey: "ui.GameAssetInspector.21";text:"Opacitet";color:panel.controller.muted;font.pixelSize:10}
                Slider {id:brushOpacity;width:parent.width;from:.05;to:1;value:1}
                GGText { colorKey: "ui.GameAssetInspector.22";width:parent.width;wrapMode:Text.WordWrap;text:"Måla på texturbilden. UV-linjerna visar vilka delar av modellen som påverkas.";color:panel.controller.muted;font.pixelSize:11}
            }
        }

        Column {
            width:parent.width;spacing:6;visible:panel.section==="INFO" && (panel.detail.clips || []).length>0
            GGText { colorKey: "ui.GameAssetInspector.23";text:"ANIMATIONER";color:panel.controller.ledgerGold;font.bold:true;font.pixelSize:11}
            Repeater {model:panel.detail.clips || []
                delegate:GGText { colorKey: "ui.GameAssetInspector.24";required property string modelData;width:panel.width;elide:Text.ElideRight;text:modelData;color:panel.controller.text;font.pixelSize:11}}
        }
        Column {
            width:parent.width;spacing:6;visible:panel.section==="GEAR"
            GGText { colorKey: "ui.GameAssetInspector.25";text:"GEAR / SOCKETS";color:panel.controller.ledgerGold;font.bold:true;font.pixelSize:11}
            GGText { colorKey: "ui.GameAssetInspector.26";width:parent.width;wrapMode:Text.WordWrap;text:"Visuell utrustning på den valda karaktären. Spelinventariet hanteras separat.";color:panel.controller.muted;font.pixelSize:11}
            ComboBox { property string uiColorScope: "ui.control.GameAssetInspector.29";id:gearSlot;width:parent.width;model:["MAIN_HAND","OFF_HAND","HEAD","CHEST","BACK","FEET"]
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignLeft }
}
            ComboBox { property string uiColorScope: "ui.control.GameAssetInspector.30";id:gearChoice;width:parent.width;textRole:"name"
                model:(panel.state.gear || []).filter(function(row){return row.slots.indexOf(gearSlot.currentText)>=0})
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignLeft }
}
            Row {
                spacing:5
                GgButton { property string uiColorScope: "ui.control.GameAssetInspector.31";text:"UTRUSTA";enabled:gearChoice.count>0
                    onClicked:panel.command({op:"GEAR",slot:gearSlot.currentText,definition:gearChoice.model[gearChoice.currentIndex].id})}
                GgButton { property string uiColorScope: "ui.control.GameAssetInspector.32";text:"TA AV";onClicked:panel.command({op:"GEAR",slot:gearSlot.currentText,definition:""})}
            }
        }
    }
}
