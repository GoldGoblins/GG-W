import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

Rectangle {
    id: bar
    objectName: "gameActionBar"
    required property var surface
    property bool paletteOpen: false
    readonly property int page: Number(surface.actionState.page || 0)
    readonly property real cellWidth: (width - 64 - 11 * 4) / 12
    width: Math.min(parent.width - 24, 940)
    height: 78
    color: "#e1192424"
    border.color: "#928664"
    radius: 4
    Component.onCompleted: surface.actionBarWidget = bar

    function dropIndex(x,y) {
        var p=bar.mapFromItem(surface,x,y)
        if (p.y<4 || p.y>height-4 || p.x<6 || p.x>width-56) return -1
        var col=Math.floor((p.x-6)/(cellWidth+4))
        return col>=0 && col<12 ? page*12+col : -1
    }
    function iconFor(row) {
        var ref=String(row.ref || "")
        var names={"ATTACK":"attack","INTERACT":"pet","TOGGLE_FLIGHT":"flight","TOGGLE_HOVERBOARD":"board","MOUNT_BOAT":"skiff",
                   "ability.surge":"surge","ability.undertow":"undertow","ability.sky_leap":"leap",
                   "item.nature.tool_shears":"shear","item.nature.tool_bucket":"milk","item.nature.tool_brush":"brush",
                   "item.nature.tool_net":"catch","item.nature.tool_rod":"fish","item.nature.tool_knife":"skin"}
        return names[ref] ? "../assets/authored/ui/"+names[ref]+".svg" : row.kind==='ITEM'
            ? String(row.texture || "../assets/authored/items/icons/unknown.png") : ""
    }
    Row {
        x:6;y:6;spacing:4
        Repeater {
            model:12
            delegate: Rectangle {
                id: slot
                required property int index
                readonly property int slotIndex: bar.page*12+index
                readonly property var entry: (bar.surface.actionState.slots || [])[slotIndex] || ({})
                width:bar.cellWidth;height:64
                color: entry.current ? "#405c32" : "#202e32"
                border.width: entry.current ? 2 : 1
                border.color: !entry.in_range ? "#c86854" : entry.not_enough_resource ? "#699dcc" : "#817c65"
                radius:3
                Image {
                    id:icon;anchors.horizontalCenter:parent.horizontalCenter;y:16;width:32;height:32
                    source:bar.iconFor(slot.entry);fillMode:Image.PreserveAspectFit
                    opacity:slot.entry.usable ? 1 : .4
                    Image {
                        anchors.fill:parent;visible:icon.status===Image.Error
                        source:"../assets/authored/items/icons/unknown.png"
                    }
                }
                Rectangle {
                    anchors.bottom:parent.bottom;width:parent.width
                    height:parent.height*Math.min(1,Number(slot.entry.cooldown_s || 0)/Math.max(.1,Number(slot.entry.cooldown_duration_s || 2)))
                    color:"#9906080a";visible:Number(slot.entry.cooldown_s || 0)>0
                }
                GGText { colorKey: "ui.GameActionBar.1";
                    x:4;y:2;text:String(slot.entry.key || "");color:"#e5dbc1";font.pixelSize:10
                }
                GGText { colorKey: "ui.GameActionBar.2";
                    anchors.centerIn:parent;visible:Number(slot.entry.cooldown_s || 0)>0
                    text:Number(slot.entry.cooldown_s || 0).toFixed(1);color:"white";font.pixelSize:16
                }
                GGText { colorKey: "ui.GameActionBar.3";
                    anchors.right:parent.right;anchors.bottom:parent.bottom;anchors.margins:3
                    text:slot.entry.kind==='ITEM' ? String(slot.entry.count || 0) : ""
                    color:"#f1d594";font.pixelSize:11
                }
                MouseArea {
                    id:hit;anchors.fill:parent;acceptedButtons:Qt.LeftButton|Qt.RightButton;hoverEnabled:true;preventStealing:true
                    cursorShape:Qt.PointingHandCursor
                    property real startX:0;property real startY:0;property bool draggingAction:false
                    onPressed:function(mouse) { startX=mouse.x;startY=mouse.y;draggingAction=false }
                    onPositionChanged:function(mouse) {
                        if (!pressed || !slot.entry.kind || bar.surface.actionState.locked) return
                        if (!draggingAction && Math.hypot(mouse.x-startX,mouse.y-startY)>5) draggingAction=true
                        if (draggingAction) {
                            var p=slot.mapToItem(bar.surface,mouse.x,mouse.y)
                            bar.surface.moveActionDrag(slot.entry.kind,slot.entry.ref,slot.slotIndex,p.x,p.y)
                        }
                    }
                    onReleased:function(mouse) {
                        if (draggingAction) bar.surface.finishActionDrag()
                        else if (mouse.button===Qt.RightButton) bar.surface.editActionBar({index:slot.slotIndex,kind:"EMPTY"})
                        else bar.surface.useActionSlot(slot.slotIndex)
                        draggingAction=false;bar.surface.forceActiveFocus()
                    }
                    onCanceled:bar.surface.cancelActionDrag()
                }
                ToolTip.visible:hit.containsMouse && !hit.draggingAction && !!slot.entry.kind
                ToolTip.text:String(slot.entry.name || "")+(slot.entry.reason ? "\n"+slot.entry.reason : "")+"\nDrag to move · Right click to clear"
            }
        }
    }
    Column {
        anchors.right:parent.right;anchors.rightMargin:4;y:5;spacing:2
        Button { property string uiColorScope: "ui.control.GameActionBar.1"; width:46;height:21;padding:0;font.pixelSize:10;text:String(bar.page+1)+" / "+String(bar.surface.actionState.pages || 10);onClicked:bar.surface.editActionBar({verb:"PAGE",page:(bar.page+1)%Number(bar.surface.actionState.pages || 10)}) 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
        Button { property string uiColorScope: "ui.control.GameActionBar.2"; width:46;height:21;padding:0;font.pixelSize:10;text:bar.surface.actionState.locked ? "LOCK" : "EDIT";onClicked:bar.surface.editActionBar({verb:"LOCK",locked:!bar.surface.actionState.locked}) 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
        Button { property string uiColorScope: "ui.control.GameActionBar.3"; width:46;height:21;padding:0;font.pixelSize:10;text:"BOOK";onClicked:bar.paletteOpen=!bar.paletteOpen 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
    }
    Rectangle {
        visible:bar.paletteOpen;anchors.bottom:parent.top;anchors.bottomMargin:6;anchors.left:parent.left
        width:360;height:bookColumn.implicitHeight+20;color:"#ed172427";border.color:"#928664";radius:3
        Column {
            id:bookColumn;anchors.left:parent.left;anchors.right:parent.right;anchors.top:parent.top;anchors.margins:10;spacing:5
            GGText { colorKey: "ui.GameActionBar.4";text:"Abilities · drag onto the bar";color:"#e8c57b"}
            Repeater {
                model:bar.paletteOpen ? bar.surface.abilityCatalog : []
                delegate:Rectangle {
                    id:bookEntry;required property var modelData
                    width:bookColumn.width;height:38;color:"#2d3d40";radius:2
                    Image {x:5;y:4;width:30;height:30;source:bar.iconFor(bookEntry.modelData)}
                    GGText { colorKey: "ui.GameActionBar.5";x:44;anchors.verticalCenter:parent.verticalCenter;text:String(bookEntry.modelData.name);color:"#e0e7cf"}
                    MouseArea {
                        anchors.fill:parent;preventStealing:true;cursorShape:Qt.OpenHandCursor
                        property real startX:0;property real startY:0;property bool draggingAction:false
                        onPressed:function(mouse) {startX=mouse.x;startY=mouse.y;draggingAction=false}
                        onPositionChanged:function(mouse) {
                            if (!pressed) return
                            if (Math.hypot(mouse.x-startX,mouse.y-startY)>5) draggingAction=true
                            if (draggingAction) {var p=bookEntry.mapToItem(bar.surface,mouse.x,mouse.y);bar.surface.moveActionDrag('ABILITY',bookEntry.modelData.ref,-1,p.x,p.y)}
                        }
                        onReleased:function(mouse) {if (draggingAction) bar.surface.finishActionDrag();else bar.surface.useAbility(bookEntry.modelData.ref);draggingAction=false}
                        onCanceled:bar.surface.cancelActionDrag()
                    }
                }
            }
            GGText { colorKey: "ui.GameActionBar.6";text:"Items: drag from your bag to a slot.\nThe item stays in your bag.";color:"#c9d5c7";font.pixelSize:11}
        }
    }
}
