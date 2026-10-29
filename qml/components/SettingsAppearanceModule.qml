pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import "GGPalette.js" as BasePalette
import "." as RuntimeTheme

Item {
    id: root
    objectName: "settingsAppearanceModule"
    property color accentColor: RuntimeTheme.GGTheme.accent
    property color frameBorder: BasePalette.edge
    property int frameRadius: 4
    property var paletteRoles: ({})
    readonly property string selectedRole: RuntimeTheme.GGTheme.roleKeys[Math.max(0,roleSelector.currentIndex)]
    readonly property string selectedColor: String(paletteRoles[selectedRole] || RuntimeTheme.GGTheme.defaultRole(selectedRole)).toLowerCase()
    signal accentColorChangedByUser(color value)
    signal frameBorderChangedByUser(color value)
    signal frameRadiusChangedByUser(int value)
    signal paletteRolesChangedByUser(var value)
    implicitHeight: contentColumn.y + contentColumn.implicitHeight + 16
    function grayToken(value) {var n=Math.max(40,Math.min(160,Math.round(value))),h=n.toString(16);return "#"+h+h+h}
    function borderChannel(){var n=parseInt(String(frameBorder).substring(1,3),16);return isNaN(n)?106:n}
    function chooseColor(value) {
        var clean=RuntimeTheme.GGTheme.normalizeOverrides(paletteRoles)
        if(RuntimeTheme.GGTheme.swatches(64).indexOf(value)<0)return
        clean[selectedRole]=value;paletteRolesChangedByUser(clean)
    }
    function resetRole() {
        var clean=RuntimeTheme.GGTheme.normalizeOverrides(paletteRoles);delete clean[selectedRole]
        if(selectedRole==="accent")accentColorChangedByUser(BasePalette.accent)
        paletteRolesChangedByUser(clean)
    }
    function colorForRole(index) {
        var key=RuntimeTheme.GGTheme.roleKeys[index]
        return String(paletteRoles[key] || RuntimeTheme.GGTheme.defaultRole(key)).toLowerCase()
    }
    function swatchInk(value) {
        var hex=String(value).substring(1)
        var light=(parseInt(hex.substring(0,2),16)*299+parseInt(hex.substring(2,4),16)*587+parseInt(hex.substring(4,6),16)*114)/1000
        return light>148 ? "#000000" : "#ffffff"
    }
    component Copy: GGText {font.family:"monospace";font.pixelSize:11;color:RuntimeTheme.GGTheme.text;textFormat:Text.PlainText;elide:Text.ElideRight}
    GgFrame {anchors.fill:parent;leftLegend:"UTSEENDE";rightLegend:"GEMENSAM PALETT";backgroundColor:RuntimeTheme.GGTheme.panel;borderColor:root.frameBorder;radius:root.frameRadius}
    Column {id:contentColumn;x:14;y:24;width:Math.max(0,root.width-28);spacing:8
        Copy { colorKey: "ui.SettingsAppearanceModule.1";width:parent.width;text:"RAMAR";color:RuntimeTheme.GGTheme.muted}
        Row {width:parent.width;spacing:8;height:26
            Copy { colorKey: "ui.SettingsAppearanceModule.2";width:68;height:26;verticalAlignment:Text.AlignVCenter;text:"Gråton"}
            GgSlider {id:borderSlider;width:Math.max(60,parent.width-244);height:26;from:64;to:154;stepSize:2;value:root.borderChannel();onMoved:root.frameBorderChangedByUser(root.grayToken(value))}
            Copy { colorKey: "ui.SettingsAppearanceModule.3";width:48;height:26;verticalAlignment:Text.AlignVCenter;text:"Radie"}
            GgSlider {id:radiusSlider;width:100;height:26;from:0;to:8;stepSize:1;value:root.frameRadius;onMoved:root.frameRadiusChangedByUser(Math.round(value))}
        }
        Rectangle {width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
        Copy { colorKey: "ui.SettingsAppearanceModule.4";width:parent.width;text:"FÄRG PER FUNKTION";font.bold:true;color:RuntimeTheme.GGTheme.bright}
        Copy { colorKey: "ui.SettingsAppearanceModule.5";width:parent.width;text:"Välj en roll och klicka på en av 64 färger.";color:RuntimeTheme.GGTheme.muted}
        ComboBox {id:roleSelector;objectName:"appearanceRoleSelector";width:parent.width;height:30;model:RuntimeTheme.GGTheme.roleLabels;currentIndex:2;font.family:"monospace";font.pixelSize:11
            contentItem:Copy { colorKey: "ui.SettingsAppearanceModule.6";text:roleSelector.displayText;verticalAlignment:Text.AlignVCenter;leftPadding:26;rightPadding:24
                Rectangle {objectName:"appearanceRoleCurrentSwatch";x:8;anchors.verticalCenter:parent.verticalCenter;width:11;height:11;color:root.selectedColor;border.color:RuntimeTheme.GGTheme.dim;border.width:1}
            }
            background:Rectangle {color:RuntimeTheme.GGTheme.raised;border.color:RuntimeTheme.GGTheme.edge}
            delegate:ItemDelegate {id:roleOption;required property int index;required property var modelData;objectName:"appearanceRoleOption";width:roleSelector.width;height:29
                highlighted:roleSelector.highlightedIndex===index
                contentItem:Copy { colorKey: "ui.SettingsAppearanceModule.7";leftPadding:26;rightPadding:8;text:String(roleOption.modelData);verticalAlignment:Text.AlignVCenter;color:roleOption.highlighted?RuntimeTheme.GGTheme.bright:RuntimeTheme.GGTheme.text
                    Rectangle {objectName:"appearanceRoleOptionSwatch";x:8;anchors.verticalCenter:parent.verticalCenter;width:11;height:11;color:root.colorForRole(roleOption.index);border.width:1;border.color:RuntimeTheme.GGTheme.dim}
                }
                background:Rectangle {color:roleOption.highlighted?RuntimeTheme.GGTheme.selected:RuntimeTheme.GGTheme.panel}
            }
        }
        Grid {id:swatches;objectName:"appearanceSwatches";width:parent.width;columns:width>=300?8:4;columnSpacing:4;rowSpacing:4
            Repeater {model:RuntimeTheme.GGTheme.swatches(64)
                delegate:Item {id:cell;required property int index;required property string modelData;objectName:"appearanceRoleSwatch";property bool chosen:root.selectedColor===modelData
                    width:(swatches.width-(swatches.columns-1)*4)/swatches.columns;height:23;activeFocusOnTab:true
                    Rectangle {anchors.fill:parent;color:cell.modelData;border.width:cell.chosen||cell.activeFocus?2:1;border.color:cell.activeFocus?RuntimeTheme.GGTheme.bright:cell.chosen?RuntimeTheme.GGTheme.text:RuntimeTheme.GGTheme.line}
                    Copy { colorKey: "ui.SettingsAppearanceModule.8";colorCustomizable:false;anchors.centerIn:parent;text:cell.chosen?"✓":"";color:root.swatchInk(cell.modelData);font.bold:true}
                    TapHandler {onTapped:{cell.forceActiveFocus();root.chooseColor(cell.modelData)}}
                    HoverHandler {id:swatchHover}
                    ToolTip.visible:swatchHover.hovered;ToolTip.delay:350;ToolTip.text:root.selectedRole+" · "+cell.modelData
                    Accessible.role:Accessible.RadioButton;Accessible.name:RuntimeTheme.GGTheme.roleLabels[roleSelector.currentIndex]+" "+modelData;Accessible.checked:chosen
                    Keys.onPressed:function(event){
                        if(event.key===Qt.Key_Return||event.key===Qt.Key_Enter||event.key===Qt.Key_Space){root.chooseColor(cell.modelData);event.accepted=true}
                        else if([Qt.Key_Right,Qt.Key_Left,Qt.Key_Down,Qt.Key_Up].indexOf(event.key)>=0){
                            var step=event.key===Qt.Key_Right?1:event.key===Qt.Key_Left?-1:event.key===Qt.Key_Down?swatches.columns:-swatches.columns
                            var next=swatchRepeater.itemAt((cell.index+step+64)%64);if(next)next.forceActiveFocus();event.accepted=true
                        }
                    }
                }
                id:swatchRepeater
            }
        }
        Row {width:parent.width;spacing:6
            GgButton {objectName:"appearanceResetRole";width:(parent.width-6)/2;height:28;text:"Återställ rollen";onClicked:root.resetRole()}
            GgButton {objectName:"appearanceResetRoles";width:(parent.width-6)/2;height:28;text:"Återställ färger";onClicked:{root.accentColorChangedByUser(BasePalette.accent);root.paletteRolesChangedByUser({})}}
        }
        Rectangle {width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
        Flow {width:parent.width;spacing:12
            Copy { colorKey: "ui.SettingsAppearanceModule.9";text:"● Klar";color:RuntimeTheme.GGTheme.positive}
            Copy { colorKey: "ui.SettingsAppearanceModule.10";text:"● Väntar";color:RuntimeTheme.GGTheme.warning}
            Copy { colorKey: "ui.SettingsAppearanceModule.11";text:"● Fel";color:RuntimeTheme.GGTheme.negative}
            Copy { colorKey: "ui.SettingsAppearanceModule.12";text:"● Info";color:RuntimeTheme.GGTheme.info}
            Copy { colorKey: "ui.SettingsAppearanceModule.13";text:"● AI";color:RuntimeTheme.GGTheme.purple}
        }
        Copy { colorKey: "ui.SettingsAppearanceModule.14";width:parent.width;text:"Samma roller används i hela GG. Tokenfärger väljs separat.";color:RuntimeTheme.GGTheme.dim;wrapMode:Text.WordWrap;elide:Text.ElideNone}
    }
}
