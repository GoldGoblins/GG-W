import QtQuick

// A URL keeps an unopened surface out of the shell's QML type graph. Loader
// caches these creation properties while inactive; live inputs use Qt.binding
// so they are present before onCompleted and keep following their owners.
Loader {
    id: root
    property url surfaceUrl: ""
    property var surfaceProperties: ({})
    property bool _sourceReady: false

    function configureSurface() {
        if (root._sourceReady)
            root.setSource(root.surfaceUrl, root.surfaceProperties || {})
    }
    onSurfaceUrlChanged: configureSurface()
    Component.onCompleted: {
        root._sourceReady = true
        root.configureSurface()
    }
}
