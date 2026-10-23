pragma ComponentBehavior: Bound

import QtQuick

Item {
    id: root

    property string themeId: "obsidian-ledger"
    property string profileId: "standard"
    property string themesJson: "[]"
    property string profilesJson: "[]"

    signal themeRequested(string themeId)
    signal saveThemeRequested(string themeId)
    signal profileRequested(string profileId)
    signal saveProfileRequested(string profileId)
    signal resetProfileRequested()

    implicitHeight: body.implicitHeight + 20

    function rows(raw) {
        try {
            var value = JSON.parse(raw || "[]")
            return value instanceof Array ? value : []
        } catch (err) {
            return []
        }
    }

    Column {
        id: body
        width: parent.width
        spacing: 10

        Text {
            text: "THEMES · PROFILES"
            color: "#e6edf3"
            font.family: "monospace"
            font.pixelSize: 13
            font.bold: true
        }

        Text {
            width: parent.width
            text: "A theme owns visual tokens. Each theme can contain several named profiles with independent surface geometry and source buffers."
            color: "#a8b0b8"
            wrapMode: Text.WordWrap
            font.family: "monospace"
            font.pixelSize: 11
        }

        Rectangle {
            width: parent.width
            height: 1
            color: "#343a40"
        }

        Text {
            text: "THEME · " + root.themeId
            color: "#c7a873"
            font.family: "monospace"
            font.pixelSize: 11
            font.bold: true
        }

        Flow {
            width: parent.width
            spacing: 6

            Repeater {
                model: root.rows(root.themesJson)
                delegate: GgButton {
                    required property var modelData
                    text: String(modelData.name || modelData.id || "THEME")
                    checkable: true
                    checked: root.themeId === String(modelData.id || "")
                    onClicked: root.themeRequested(String(modelData.id || ""))
                }
            }
        }

        Text {
            text: "PROFILE · " + root.profileId
            color: "#c7a873"
            font.family: "monospace"
            font.pixelSize: 11
            font.bold: true
        }

        Flow {
            width: parent.width
            spacing: 6

            Repeater {
                model: root.rows(root.profilesJson)
                delegate: GgButton {
                    required property var modelData
                    text: String(modelData.name || modelData.id || "PROFILE")
                    checkable: true
                    checked: root.profileId === String(modelData.id || "")
                    onClicked: root.profileRequested(String(modelData.id || ""))
                }
            }
        }

        Row {
            width: parent.width
            spacing: 8

            GgField {
                id: themeName
                width: Math.min(240, parent.width - saveTheme.implicitWidth - 8)
                placeholderText: "new theme id"
            }

            GgButton {
                id: saveTheme
                text: "SAVE AS THEME"
                onClicked: {
                    if (themeName.text.trim().length > 0)
                        root.saveThemeRequested(themeName.text.trim())
                }
            }
        }

        Row {
            width: parent.width
            spacing: 8

            GgField {
                id: profileName
                width: Math.min(260, parent.width - saveProfile.implicitWidth - 8)
                placeholderText: "new profile id"
            }

            GgButton {
                id: saveProfile
                text: "SAVE AS PROFILE"
                onClicked: {
                    if (profileName.text.trim().length > 0)
                        root.saveProfileRequested(profileName.text.trim())
                }
            }

            GgButton {
                text: "RESET PROFILE"
                onClicked: root.resetProfileRequested()
            }
        }

        Text {
            width: parent.width
            text: "The Standard profile is the reset baseline. Saving a profile copies the current presentation state; it does not change engine or workspace functions."
            color: "#77818b"
            wrapMode: Text.WordWrap
            font.family: "monospace"
            font.pixelSize: 10
        }
    }
}
