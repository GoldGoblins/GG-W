pragma ComponentBehavior: Bound

import QtQuick
import "webCursorPack.js" as Cursors

Item {
    id: root
    objectName: "webAgentCursorItem"

    property string shape: "default"
    readonly property string canon: Cursors.canon(shape)
    readonly property int hotX: Cursors.spec(shape).hotX
    readonly property int hotY: Cursors.spec(shape).hotY
    readonly property int frameCount: Cursors.spec(shape).frames
    readonly property int frameDelay: Cursors.spec(shape).delay
    readonly property string frameFile: Cursors.spec(shape).file
    readonly property url frameSource: Qt.resolvedUrl("web-cursors/" + root.frameFile)

    width: 24
    height: 24
    enabled: false

    Image {
        anchors.fill: parent
        visible: root.frameCount <= 1
        source: visible ? root.frameSource : ""
        smooth: true
        fillMode: Image.PreserveAspectFit
        asynchronous: false
    }

    AnimatedSprite {
        id: anim
        anchors.fill: parent
        visible: root.frameCount > 1
        running: visible
        source: visible ? root.frameSource : ""
        frameWidth: 24
        frameHeight: 24
        frameCount: Math.max(1, root.frameCount)
        frameDuration: root.frameDelay > 0 ? root.frameDelay : 30
        interpolate: false
        loops: AnimatedSprite.Infinite
    }

    onCanonChanged: {
        if (anim.visible)
            anim.restart()
    }
}
