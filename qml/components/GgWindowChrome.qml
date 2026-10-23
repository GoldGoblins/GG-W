pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Window

// Window controls share the frame's legend line, outside its clipped content.
Item {
    id: root

    required property Window targetWindow
    required property Item titleFrame
    property color backgroundColor: "#161616"
    property color foregroundColor: "#e6edf3"
    property bool desktopShell: false
    property bool fullscreen: false
    readonly property bool maximized: root.targetWindow.visibility === Window.Maximized
    readonly property bool resizable: !root.desktopShell && !root.fullscreen
                                     && root.targetWindow.visibility === Window.Windowed
    readonly property int resizeMargin: 6

    signal windowModeChangeRequested()
    signal maximizeRequested()

    MouseArea {
        id: titleDrag
        objectName: "windowTitleDragArea"
        x: root.titleFrame.x
        y: Math.max(0, root.titleFrame.y - 10)
        width: Math.max(0, controlsPlate.x - x)
        height: 24
        acceptedButtons: Qt.LeftButton
        onDoubleClicked: root.maximizeRequested()

        DragHandler {
            target: null
            acceptedButtons: Qt.LeftButton
            enabled: !root.desktopShell && !root.fullscreen
            onActiveChanged: {
                if (active) {
                    root.windowModeChangeRequested()
                    root.targetWindow.startSystemMove()
                }
            }
        }
    }

    Rectangle {
        id: controlsPlate
        objectName: "windowControlsPlate"
        x: root.titleFrame.x + root.titleFrame.width - width - 12
        y: Math.max(0, root.titleFrame.y - 10)
        width: controls.implicitWidth + 12
        height: 24
        color: root.backgroundColor
        radius: 2

        Row {
            id: controls
            anchors.centerIn: parent
            spacing: 2

            WindowButton {
                objectName: "windowMinimizeButton"
                text: "−"
                Accessible.name: "Minimera"
                onClicked: {
                    root.windowModeChangeRequested()
                    root.targetWindow.showMinimized()
                }
            }

            WindowButton {
                objectName: "windowMaximizeButton"
                text: root.maximized || root.fullscreen ? "❐" : "□"
                Accessible.name: root.fullscreen ? "Lämna helskärm"
                                 : (root.maximized ? "Återställ" : "Maximera")
                onClicked: root.maximizeRequested()
            }

            WindowButton {
                objectName: "windowCloseButton"
                text: "×"
                closeButton: true
                Accessible.name: "Stäng"
                onClicked: root.targetWindow.close()
            }
        }
    }

    component WindowButton: Button {
        id: control
        property bool closeButton: false
        width: 32
        height: 22
        padding: 0
        hoverEnabled: true
        activeFocusOnTab: true
        background: Rectangle {
            color: control.down ? (control.closeButton ? "#a63232" : "#383838")
                                : (control.hovered ? (control.closeButton ? "#823030" : "#292929")
                                                   : root.backgroundColor)
            border.width: control.visualFocus ? 1 : 0
            border.color: root.foregroundColor
            radius: 2
        }
        contentItem: Text {
            text: control.text
            color: root.foregroundColor
            font.family: "monospace"
            font.pixelSize: 14
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        ToolTip.visible: hovered
        ToolTip.delay: 650
        ToolTip.text: Accessible.name
    }

    // Ask the OS to resize: it keeps minimum sizes, screen scaling and snapping.
    Repeater {
        model: [
            {edges: Qt.TopEdge | Qt.LeftEdge, cursor: Qt.SizeFDiagCursor},
            {edges: Qt.TopEdge | Qt.RightEdge, cursor: Qt.SizeBDiagCursor},
            {edges: Qt.BottomEdge | Qt.LeftEdge, cursor: Qt.SizeBDiagCursor},
            {edges: Qt.BottomEdge | Qt.RightEdge, cursor: Qt.SizeFDiagCursor},
            {edges: Qt.TopEdge, cursor: Qt.SizeVerCursor},
            {edges: Qt.BottomEdge, cursor: Qt.SizeVerCursor},
            {edges: Qt.LeftEdge, cursor: Qt.SizeHorCursor},
            {edges: Qt.RightEdge, cursor: Qt.SizeHorCursor}
        ]
        delegate: MouseArea {
            required property var modelData
            readonly property bool leftEdge: Boolean(modelData.edges & Qt.LeftEdge)
            readonly property bool rightEdge: Boolean(modelData.edges & Qt.RightEdge)
            readonly property bool topEdge: Boolean(modelData.edges & Qt.TopEdge)
            readonly property bool bottomEdge: Boolean(modelData.edges & Qt.BottomEdge)
            objectName: "windowResize_" + modelData.edges
            enabled: root.resizable
            x: rightEdge ? root.width - width : (leftEdge ? 0 : root.resizeMargin)
            y: bottomEdge ? root.height - height : (topEdge ? 0 : root.resizeMargin)
            width: leftEdge || rightEdge ? root.resizeMargin
                                        : root.width - 2 * root.resizeMargin
            height: topEdge || bottomEdge ? root.resizeMargin
                                         : root.height - 2 * root.resizeMargin
            cursorShape: modelData.cursor
            acceptedButtons: Qt.LeftButton
            onPressed: {
                root.windowModeChangeRequested()
                root.targetWindow.startSystemResize(modelData.edges)
            }
        }
    }
}
