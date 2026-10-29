import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

Column {
    id:root;objectName:"marketReceiptTree"
    property var nodes:[]
    property bool busy:false
    property var collapsed:({technical:true})
    readonly property var visibleNodes:flatten(nodes,0,"")
    signal objectRequested(string id)
    function flatten(nodes,depth,path){var result=[];nodes.forEach(function(node,index){var key=node.key || path+"/"+index;result.push({node:node,key:key,depth:depth});if(node.children && !root.collapsed[key])result=result.concat(flatten(node.children,depth+1,key))});return result}
    function toggle(entry){if(busy)return;if(entry.node.children){var next=Object.assign({},collapsed);next[entry.key]=!collapsed[entry.key];collapsed=next}else if(entry.node.objectId)objectRequested(entry.node.objectId)}
    spacing:0
    Repeater {model:root.visibleNodes
        Item {
            id:entry;required property var modelData
            objectName:modelData.node.heading ? "marketTreeHeading" : "marketTreeNode"
            width:root.width;height:label.implicitHeight+(modelData.node.heading ? 18 : 5)
            readonly property bool branch:!!modelData.node.children
            GGText { colorKey: "ui.MarketplaceReceiptTree.1";x:Math.max(0,entry.modelData.depth-1)*14;y:entry.modelData.node.heading ? 8 : 2;width:18;text:entry.modelData.node.heading ? String(entry.modelData.node.icon || "◇") : entry.branch ? (root.collapsed[entry.modelData.key] ? "▸" : "▾") : "└";color:entry.modelData.node.heading ? RuntimeTheme.GGTheme.text : RuntimeTheme.GGTheme.dim;font.family:"monospace";font.pixelSize:entry.modelData.node.heading ? 16 : 12}
            GGText { colorKey: "ui.MarketplaceReceiptTree.2";id:label;x:entry.modelData.depth*12+18;y:entry.modelData.node.heading ? 8 : 2;width:parent.width-x-4;text:String(entry.modelData.node.label || "");textFormat:Text.PlainText;wrapMode:Text.Wrap;color:entry.modelData.node.accent ? RuntimeTheme.GGTheme.accent : entry.modelData.node.heading ? RuntimeTheme.GGTheme.text : entry.modelData.node.muted ? RuntimeTheme.GGTheme.dim : RuntimeTheme.GGTheme.muted;font.family:"monospace";font.pixelSize:root.width>=320 ? (entry.modelData.node.heading ? 13 : 12) : (entry.modelData.node.heading ? 11 : 10);font.letterSpacing:entry.modelData.node.heading ? .8 : 0}
            Rectangle {x:22;y:parent.height-2;width:parent.width-22;height:1;visible:!!entry.modelData.node.heading;color:RuntimeTheme.GGTheme.line}
            MouseArea {id:hover;anchors.fill:parent;enabled:!root.busy && (entry.branch || !!entry.modelData.node.objectId);hoverEnabled:true;cursorShape:Qt.PointingHandCursor;onClicked:root.toggle(entry.modelData)}
            activeFocusOnTab:branch || !!modelData.node.objectId;Accessible.role:branch || !!modelData.node.objectId ? Accessible.Button : Accessible.StaticText;Accessible.name:String(modelData.node.label || "")
            Keys.onReturnPressed:root.toggle(modelData)
            Keys.onSpacePressed:root.toggle(modelData)
            ToolTip.visible:hover.containsMouse && !!entry.modelData.node.objectId;ToolTip.text:"Öppna det länkade objektets pass";ToolTip.delay:600
        }
    }
}
