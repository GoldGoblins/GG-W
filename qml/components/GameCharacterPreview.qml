import QtQuick
import QtQuick3D
import QtQuick3D.AssetUtils

// The inventory views the same authored character and equipped item sources
// as the world renderer. No portrait image or second character mesh is used.
Item {
    id: preview
    property var game: null
    property var equipment: []
    property var renderedEquipment: []
    property string equipmentSignature: ""
    readonly property bool characterReady: heroLoader.status === RuntimeLoader.Success
    readonly property var characterAsset: game ? (game.selectedAsset || ({})) : ({})
    readonly property string characterSource: String(characterAsset.source || "")
    property int socketRevision: 0
    property real avatarYaw: 0

    function updateEquipment() {
        var signature=JSON.stringify(equipment || [])
        if (signature!==equipmentSignature) {
            equipmentSignature=signature
            renderedEquipment=equipment || []
        }
    }
    onEquipmentChanged:updateEquipment()
    Component.onCompleted:updateEquipment()

    function number(value, fallback) {
        var result = Number(value)
        return isFinite(result) ? result : fallback
    }

    function itemAssetFor(row) {
        var visual = row && row.visual || ({})
        var id = String(visual.asset_id || "")
        var catalog = game && game.assets && game.assets.static_items || ({})
        return catalog[id] || ({})
    }

    function socketNode(name) {
        if (!name || !game || !game.surfaceHost || !heroLoader)
            return null
        if (typeof game.surfaceHost.gameEngineFindNamedNode !== "function")
            return null
        return game.surfaceHost.gameEngineFindNamedNode(heroLoader, String(name))
    }

    Rectangle {
        anchors.fill: parent
        color: "#142329"
        gradient: Gradient {
            GradientStop { position: 0; color: "#34484a" }
            GradientStop { position: 0.54; color: "#223435" }
            GradientStop { position: 1; color: "#101a1e" }
        }
    }

    View3D {
        anchors.fill: parent
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Transparent
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
        }
        camera: PerspectiveCamera {
            position: Qt.vector3d(0, 0.13, 2.65)
            clipNear: 0.02
            clipFar: 100
            fieldOfView: 42
        }
        DirectionalLight {
            eulerRotation: Qt.vector3d(-37, -32, 0)
            color: "#ffe2b3"
            brightness: 2.4
        }
        DirectionalLight {
            eulerRotation: Qt.vector3d(-18, 145, 0)
            color: "#a8cddd"
            brightness: 1.3
        }
        Node {
            id: actorNode
            // The authored character faces the camera along its local +Z.
            eulerRotation.y: preview.avatarYaw
            RuntimeLoader {
                id: heroLoader
                source: preview.characterSource
                position: Qt.vector3d(
                    0,
                    preview.number(preview.characterAsset.root_offset_m, -0.65),
                    0
                )
                onStatusChanged: {
                    preview.socketRevision++
                    if(status===RuntimeLoader.Success && preview.game && preview.game.surfaceHost
                        && typeof preview.game.surfaceHost.gameEngineRuntimeClip === "function")
                        preview.game.surfaceHost.gameEngineRuntimeClip(this,"idle",0,"")
                }
                Component.onDestruction: {
                    if(preview.game && preview.game.surfaceHost
                        && typeof preview.game.surfaceHost.gameEngineReleaseRuntimeClip === "function")
                        preview.game.surfaceHost.gameEngineReleaseRuntimeClip(this)
                }
            }
            Repeater3D {
                model: preview.renderedEquipment
                delegate: Node {
                    id: worn
                    required property var modelData
                    readonly property var visual: modelData.visual || ({})
                    readonly property var attachment: modelData.attachment
                        || worn.visual.attachment || ({})
                    readonly property var itemAsset: preview.itemAssetFor(modelData)
                    readonly property var itemGeometry: {
                        if (modelData.definition_id==="item.guild_tabard") return null
                        if (preview.game && preview.game.surfaceHost
                            && typeof preview.game.surfaceHost.gameEnginePreviewItemGeometry === "function")
                            return preview.game.surfaceHost.gameEnginePreviewItemGeometry(
                                String(worn.itemAsset.geometry_key || worn.visual.asset_id || "item.unknown"),
                                String(worn.itemAsset.asset_class || modelData.kind || "ITEM"),preview)
                        if (!preview.game || !preview.game.surfaceHost
                            || typeof preview.game.surfaceHost.gameEngineItemGeometry
                                !== "function")
                            return null
                        return preview.game.surfaceHost.gameEngineItemGeometry(
                            String(worn.itemAsset.geometry_key
                                || worn.visual.asset_id || "item.unknown"),
                            String(worn.itemAsset.asset_class
                                || modelData.kind || "ITEM")
                        )
                    }
                    readonly property var rest: attachment.rest || []
                    readonly property string slot: String(modelData.equipped_slot || "")
                    readonly property string socketName: String(
                        attachment.node || (attachment.socket
                            ? "SOCKET_" + attachment.socket : "")
                    )
                    readonly property var socket: {
                        var revision = preview.socketRevision
                        return heroLoader.status === RuntimeLoader.Success
                            ? preview.socketNode(worn.socketName) : null
                    }
                    readonly property var tabardAlignment: socket && slot==="TABARD"
                        ? preview.game.surfaceHost.gameEngineAlignedAttachment(socket.sceneRotation,actorNode.sceneRotation,
                            Qt.vector3d(0,-.35,.34)) : null
                    parent: worn.socket || actorNode
                    position: tabardAlignment ? tabardAlignment.position : worn.socket ? Qt.vector3d(
                        preview.number((visual.grip_offset || [])[0],0),
                        preview.number((visual.grip_offset || [])[1],0),
                        preview.number((visual.grip_offset || [])[2],0)) : Qt.vector3d(
                        preview.number(rest[0], slot === "MAIN_HAND" ? 0.48
                            : (slot === "OFF_HAND" ? -0.48 : 0)) + (slot==="TABARD" ? preview.number((visual.grip_offset || [])[0],0) : 0),
                        preview.number(rest[1], slot === "HEAD" ? 0.83
                            : (slot === "BACK" ? 0.13 : (slot === "FEET" ? -0.61 : 0.07))) + (slot==="TABARD" ? preview.number((visual.grip_offset || [])[1],0) : 0),
                        preview.number(rest[2], slot === "BACK" ? 0.22 : -0.04) + (slot==="TABARD" ? preview.number((visual.grip_offset || [])[2],0) : 0)
                    )
                    eulerRotation: tabardAlignment ? tabardAlignment.rotation : Qt.vector3d(
                        preview.number(visual.rotation ? visual.rotation[0] : 0, 0),
                        preview.number(visual.rotation_y, 0),
                        preview.number(visual.rotation ? visual.rotation[2] : 0, 0)
                    )
                    Model {
                        visible: authoredLoader.status !== RuntimeLoader.Success
                        source: worn.itemGeometry ? "" : String(worn.visual.model || "#Cube")
                        geometry: worn.itemGeometry
                        scale: Qt.vector3d(
                            preview.number(visual.scale ? visual.scale[0] : 0.16, 0.16)
                                * (worn.itemGeometry ? 1 : 0.01),
                            preview.number(visual.scale ? visual.scale[1] : 0.16, 0.16)
                                * (worn.itemGeometry ? 1 : 0.01),
                            preview.number(visual.scale ? visual.scale[2] : 0.16, 0.16)
                                * (worn.itemGeometry ? 1 : 0.01)
                        )
                        materials: PrincipledMaterial {
                            baseColorMap: worn.visual.base_color_map ? tabardTexture : null
                            baseColor: String(worn.visual.base_color
                                || worn.modelData.rarity_color || "#d6d6d6")
                            roughness: preview.number(worn.visual.roughness, 0.42)
                            metalness: preview.number(worn.visual.metalness, 0.34)
                        }
                    }
                    Texture {
                        id:tabardTexture
                        textureData:preview.game && preview.game.surfaceHost && worn.visual.base_color_map
                            ? preview.game.surfaceHost.gameEngineEmblemTexture(String(worn.visual.base_color_map),preview) : null
                    }
                    RuntimeLoader {
                        id: authoredLoader
                        source: worn.itemAsset.status === "READY"
                            && worn.itemAsset.mode === "AUTHORED_STATIC"
                            ? String(worn.itemAsset.source || "") : ""
                        scale: Qt.vector3d(
                            preview.number(visual.scale ? visual.scale[0] : 0.16, 0.16)
                                * preview.number(worn.itemAsset.unit_scale
                                    ? worn.itemAsset.unit_scale[0] : 1, 1),
                            preview.number(visual.scale ? visual.scale[1] : 0.16, 0.16)
                                * preview.number(worn.itemAsset.unit_scale
                                    ? worn.itemAsset.unit_scale[1] : 1, 1),
                            preview.number(visual.scale ? visual.scale[2] : 0.16, 0.16)
                                * preview.number(worn.itemAsset.unit_scale
                                    ? worn.itemAsset.unit_scale[2] : 1, 1)
                        )
                    }
                }
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        color: "transparent"
        border.color: "#806e4e"
        border.width: 1
    }
    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.SizeHorCursor
        property real lastX: 0
        onPressed: function(mouse) { lastX = mouse.x }
        onPositionChanged: function(mouse) {
            if (pressed) {
                preview.avatarYaw += (mouse.x - lastX) * 0.8
                lastX = mouse.x
            }
        }
        onDoubleClicked: preview.avatarYaw = 0
    }
}
