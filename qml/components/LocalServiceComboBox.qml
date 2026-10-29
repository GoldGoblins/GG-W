import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

ComboBox { property string uiColorScope: "ui.control.LocalServiceComboBox.1";
    id: picker
    // A fresh service snapshot replaces these rows, not the retained choice.
    // Keep the native model assignment inside one guarded reconciliation.
    property var entries: []
    property var selectedId: null
    property bool hasSelection: false
    // Optional owner memory for a picker inside a recreated list delegate.
    // The owner bounds and retires keys with the real records it displays.
    property var selectionMemory: null
    property string selectionKey: ""
    readonly property var selectedRow: currentIndex >= 0 && currentIndex < entries.length ? entries[currentIndex] : null
    property bool _refreshing: false
    property bool _ready: false
    valueRole: "id"
    currentIndex: -1

    function remember(index) {
        if (_refreshing || !_ready) return
        var row = index >= 0 && index < entries.length ? entries[index] : null
        hasSelection = !!row && row[valueRole] !== undefined && row[valueRole] !== null
        selectedId = hasSelection ? row[valueRole] : null
        saveChoice()
    }
    function saveChoice() {
        if (!_ready || !selectionMemory || !selectionKey) return
        if (hasSelection) selectionMemory[selectionKey] = selectedId
        else delete selectionMemory[selectionKey]
    }
    function refresh() {
        _refreshing = true
        var found = -1
        var rows = entries || []
        if (hasSelection) {
            for (var index = 0; index < rows.length; index++) {
                if (rows[index][valueRole] === selectedId) {
                    // A duplicate identity cannot represent a unique choice.
                    if (found >= 0) { found = -1; break }
                    found = index
                }
            }
        }
        model = rows
        currentIndex = found
        if (found < 0) { hasSelection = false; selectedId = null }
        saveChoice()
        _refreshing = false
    }
    onEntriesChanged: refresh()
    onCurrentIndexChanged: remember(currentIndex)
    onActivated: function(index) { remember(index) }
    Component.onCompleted: {
        if (selectionMemory && selectionKey && Object.prototype.hasOwnProperty.call(selectionMemory, selectionKey)) {
            selectedId = selectionMemory[selectionKey]
            hasSelection = true
        }
        _ready = true
        refresh()
    }

        contentItem: GGControlCaption { horizontalAlignment:Text.AlignLeft }
}
