import QtQuick

// Sits on a TextEdit/TextArea/TextField and keeps drag-select from being
// stolen by a parent Flickable or ScrollView. Keyboard cut/copy/paste and
// replace-on-type stay on the editor once it has focus.
MouseArea {
    id: root

    property Item editor: parent
    property int anchor: 0
    property int clickCount: 0
    property real lastClickAt: 0

    anchors.fill: parent
    cursorShape: Qt.IBeamCursor
    acceptedButtons: Qt.LeftButton
    preventStealing: true
    hoverEnabled: true

    onWheel: function(wheel) {
        wheel.accepted = false
    }

    function positionAt(x, y) {
        if (!root.editor || !root.editor.positionAt)
            return 0
        return root.editor.positionAt(x, y)
    }

    function selectRange(from, to) {
        if (!root.editor || !root.editor.select)
            return
        root.editor.select(from, to)
    }

    function selectLine(pos) {
        var text = String(root.editor.text || "")
        var start = text.lastIndexOf("\n", Math.max(0, pos - 1)) + 1
        var end = text.indexOf("\n", pos)
        if (end < 0)
            end = text.length
        root.selectRange(start, end)
        root.anchor = start
    }

    onPressed: function(mouse) {
        if (!root.editor)
            return
        root.editor.forceActiveFocus()
        var pos = root.positionAt(mouse.x, mouse.y)
        var now = Date.now()
        if (now - root.lastClickAt < 400)
            root.clickCount += 1
        else
            root.clickCount = 1
        root.lastClickAt = now
        if (root.clickCount >= 3) {
            root.selectLine(pos)
            return
        }
        if (root.clickCount === 2 && root.editor.selectWord) {
            root.editor.cursorPosition = pos
            root.editor.selectWord()
            root.anchor = root.editor.selectionStart
            return
        }
        if ((mouse.modifiers & Qt.ShiftModifier) && root.editor.selectedText !== undefined)
            root.selectRange(root.anchor, pos)
        else {
            root.anchor = pos
            root.editor.cursorPosition = pos
            if (root.editor.deselect)
                root.editor.deselect()
        }
    }

    onPositionChanged: function(mouse) {
        if (!pressed || !root.editor || root.clickCount > 1)
            return
        root.selectRange(root.anchor, root.positionAt(mouse.x, mouse.y))
    }
}
