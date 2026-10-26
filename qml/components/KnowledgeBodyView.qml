import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    objectName: "knowledgeBodyView"
    property var surfaceHost: null
    property var bundle: ({})
    property string loadStatus: ""
    property string ageGroup: ""
    property string selectedRegionId: ""
    property string selectedTopicId: ""
    property string selectedFigureId: ""
    property string selectedScenarioId: ""
    property string activeSection: "Ämnen"
    property string query: ""
    property var parameters: ({})
    property var injuries: []
    property var checkedSteps: ({})
    property string manualSeverity: "unassessed"
    property bool injuryMode: false
    property bool newsEnabled: false
    property bool mobileDetails: false
    property var evaluation: ({})
    property var enlargedIllustration: null
    readonly property bool stacked: width < 740
    readonly property color ink: "#e8edf1"
    readonly property color muted: "#8f9eaa"
    readonly property color gold: "#d7ba8b"
    readonly property var ages: bundle.age_groups || []
    readonly property var regions: bundle.regions || []
    readonly property var parameterDefinitions: {
        var rows = bundle.parameters || []
        var result = []
        for (var i = 0; i < rows.length; ++i) if (acceptsAge(rows[i])) result.push(rows[i])
        return result
    }
    readonly property var scenarios: bundle.scenarios || []
    readonly property var figures: {
        var result = []
        var rows = bundle.figures || []
        for (var i = 0; i < rows.length; ++i) {
            if (acceptsAge(rows[i])) result.push(rows[i])
        }
        return result
    }
    readonly property var currentFigure: {
        var rows = root.figures
        for (var i = 0; i < rows.length; ++i) if (String(rows[i].id) === selectedFigureId) return rows[i]
        for (var a = 0; a < ages.length; ++a) {
            if (String(ages[a].id) !== ageGroup || !ages[a].figure_id) continue
            for (var f = 0; f < rows.length; ++f) if (String(rows[f].id) === String(ages[a].figure_id)) return rows[f]
        }
        return rows.length ? rows[0] : ({})
    }
    readonly property var currentTopic: {
        var rows = bundle.topics || []
        for (var i = 0; i < rows.length; ++i) if (String(rows[i].id) === selectedTopicId && acceptsAge(rows[i])) return rows[i]
        return ({})
    }
    readonly property var topics: {
        var result = []
        var rows = bundle.topics || []
        var term = query.toLocaleLowerCase().trim()
        for (var i = 0; i < rows.length; ++i) {
            var row = rows[i]
            if (!acceptsAge(row)) continue
            var parts = row.regions || row.region_ids || []
            if (selectedRegionId && parts.length && parts.indexOf(selectedRegionId) < 0) continue
            var text = String(row.label || row.title || "") + " " + String(row.summary || "") + " " + (row.keywords || []).join(" ")
            if (term && text.toLocaleLowerCase().indexOf(term) < 0) continue
            result.push(row)
        }
        return result
    }
    readonly property var hotspots: {
        var rows = currentFigure.hotspots || regions
        var result = []
        for (var i = 0; i < rows.length; ++i) {
            var row = rows[i]
            if (!acceptsAge(row) || row.x === undefined || row.y === undefined) continue
            var copy = {}
            for (var k in row) copy[k] = row[k]
            copy.injury = hasInjury(copy.id)
            copy.label = String(copy.label || regionLabel(copy.id)) + (copy.injury ? " · markerad skada" : "")
            if (String(copy.id) === "back" && String(currentFigure.layer || "") !== "back")
                copy.label = "Rygg · schematisk hänvisning"
            result.push(copy)
        }
        return result
    }
    readonly property var severityChoices: [
        {id: "unassessed", label: "Ej bedömd"}, {id: "red", label: "Röd · vald i övningen"},
        {id: "orange", label: "Orange · vald i övningen"}, {id: "yellow", label: "Gul · vald i övningen"},
        {id: "green", label: "Grön · vald i övningen"}
    ]
    readonly property color stateColor: manualSeverity === "red" ? "#e78480" : manualSeverity === "orange" ? "#e6aa6b"
        : manualSeverity === "yellow" ? "#dacb8a" : manualSeverity === "green" ? "#93b9a3" : "#9cabb5"
    readonly property var enteredValues: {
        var result = []
        for (var i = 0; i < parameterDefinitions.length; ++i) {
            var p = parameterDefinitions[i]
            var value = parameters[p.id]
            if (value !== undefined && value !== null && String(value).length) {
                var displayed = String(value)
                var options = p.options || []
                for (var o = 0; o < options.length; ++o) {
                    if (typeof options[o] === "object" && String(options[o].value) === String(value)) {
                        displayed = String(options[o].label || value)
                        break
                    }
                }
                result.push({label: String(p.label || p.id), value: displayed, unit: String(p.unit || "")})
            }
        }
        return result
    }
    signal requestSourcePage(string sourceId, int page)

    function parse(raw) {
        try { return JSON.parse(String(raw || "{}")) } catch (err) { return {status: "ERROR"} }
    }
    function acceptsAge(row) {
        var groups = row.age_groups || []
        if (row.age_group) return String(row.age_group) === ageGroup || String(row.age_group) === "all"
        return !groups.length || groups.indexOf(ageGroup) >= 0 || groups.indexOf("all") >= 0
    }
    function regionLabel(id) {
        for (var i = 0; i < regions.length; ++i) if (String(regions[i].id) === String(id)) return String(regions[i].label || id)
        return String(id || "Hela kroppen")
    }
    function ageLabel() {
        for (var i = 0; i < ages.length; ++i) if (String(ages[i].id) === ageGroup) return String(ages[i].label || ageGroup)
        return "Välj åldersgrupp"
    }
    function reload() {
        if (!surfaceHost) return
        if (!surfaceHost.knowledgeBody) {
            loadStatus = "RESTART_REQUIRED"
            bundle = {notice: "Kroppsvyn är installerad. Starta om GG AI Desktop för att öppna den."}
            return
        }
        var result = parse(surfaceHost.knowledgeBody())
        loadStatus = String(result.status || "ERROR")
        bundle = result.bundle || result
        if (!ageGroup && ages.length) ageGroup = String(ages[0].id)
        evaluate()
    }
    function changeAge(id) {
        ageGroup = String(id)
        selectedFigureId = ""
        selectedTopicId = ""
        selectedScenarioId = ""
        selectedRegionId = ""
        checkedSteps = ({})
        parameters = ({})
        injuries = []
        manualSeverity = "unassessed"
        newsEnabled = false
        evaluate()
    }
    function selectRegion(id) {
        if (selectedRegionId !== String(id || "")) {
            selectedTopicId = ""
            checkedSteps = ({})
        }
        selectedRegionId = String(id || "")
        activeSection = "Ämnen"
        mobileDetails = true
        if (injuryMode && selectedRegionId) toggleInjury(selectedRegionId)
        evaluate()
    }
    function selectTopic(id) {
        selectedTopicId = String(id)
        checkedSteps = ({})
        activeSection = "Moment"
        mobileDetails = true
        evaluate()
    }
    function setParameter(id, value) {
        var next = {}
        for (var k in parameters) next[k] = parameters[k]
        next[String(id)] = value
        parameters = next
        evaluationDelay.restart()
    }
    function toggleInjury(id) {
        var next = injuries.slice()
        var i = -1
        for (var n = 0; n < next.length; ++n) {
            var key = typeof next[n] === "object" ? next[n].region_id : next[n]
            if (String(key) === String(id)) { i = n; break }
        }
        if (i >= 0) next.splice(i, 1)
        else next.push(String(id))
        injuries = next
        evaluate()
    }
    function hasInjury(id) {
        for (var i = 0; i < injuries.length; ++i) {
            var key = typeof injuries[i] === "object" ? injuries[i].region_id : injuries[i]
            if (String(key) === String(id)) return true
        }
        return false
    }
    function setStep(id, checked) {
        var next = {}
        for (var k in checkedSteps) next[k] = checkedSteps[k]
        next[String(id)] = checked
        checkedSteps = next
    }
    function applyScenario(id) {
        for (var i = 0; i < scenarios.length; ++i) {
            var row = scenarios[i]
            if (String(row.id) !== String(id)) continue
            if (row.age_group && String(row.age_group) !== ageGroup) changeAge(row.age_group)
            selectedScenarioId = String(row.id)
            selectedTopicId = String(row.topic_id || "")
            selectedRegionId = String(row.region_id || "")
            parameters = row.parameters || row.values || ({})
            injuries = row.injuries || []
            manualSeverity = String(row.severity || "unassessed")
            newsEnabled = false
            checkedSteps = ({})
            activeSection = "Parametrar"
            evaluate()
            return
        }
    }
    function resetCase() {
        parameters = ({})
        injuries = []
        checkedSteps = ({})
        selectedScenarioId = ""
        manualSeverity = "unassessed"
        injuryMode = false
        newsEnabled = false
        evaluate()
        bodyRaster.resetView()
    }
    function evaluate() {
        if (!surfaceHost || !surfaceHost.knowledgeBodyEvaluate) return
        var input = {age_group: ageGroup,
            topic_id: selectedTopicId, region_id: selectedRegionId, parameters: parameters,
            injuries: injuries, severity: manualSeverity, scenario_id: selectedScenarioId}
        if (newsEnabled && (ageGroup === "adult" || ageGroup === "older")) {
            input.educational_score = "news2_scale1"
            input.context = "adult_nonpregnant_scale1"
        }
        evaluation = parse(surfaceHost.knowledgeBodyEvaluate(JSON.stringify(input)))
    }
    function openCitation(citation) {
        if (citation && citation.source_id && Number(citation.page) > 0)
            requestSourcePage(String(citation.source_id), Number(citation.page))
    }
    function openIllustration(value) {
        if (!value || !value.image_url || /^(https?:|data:)/i.test(String(value.image_url))) return
        enlargedIllustration = value
        illustrationDialog.open()
    }

    Component.onCompleted: reload()
    onSurfaceHostChanged: if (surfaceHost) reload()
    onVisibleChanged: if (visible) reload()

    component BodyButton: Button {
        id: button
        property bool selected: false
        implicitHeight: 32
        implicitWidth: caption.implicitWidth + 24
        padding: 0
        hoverEnabled: true
        background: Rectangle {
            radius: 4
            color: button.selected ? "#2a383c" : button.hovered ? "#24303a" : "#17212b"
            border.color: button.selected ? "#9b9279" : "#35424b"
            opacity: button.enabled ? 1 : 0.45
        }
        contentItem: Text {
            id: caption
            text: button.text
            textFormat: Text.PlainText
            color: button.selected ? "#f0dfbd" : "#c4cdd4"
            font.pixelSize: 12
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
    }
    component BodyField: TextField {
        id: field
        implicitHeight: 34
        color: root.ink
        placeholderTextColor: "#82909b"
        selectByMouse: true
        font.pixelSize: 13
        background: Rectangle {
            color: "#111a22"; radius: 4
            border.color: field.activeFocus ? "#a89b79" : "#34414d"
        }
    }
    component BodyCombo: ComboBox {
        id: combo
        implicitHeight: 34
        font.pixelSize: 12
        padding: 8
        rightPadding: 24
        palette.text: root.ink
        palette.buttonText: root.ink
        palette.base: "#16222c"
        palette.highlight: "#3a4e55"
        palette.highlightedText: "#f2e4ca"
        background: Rectangle {
            color: "#111b24"; radius: 4
            border.color: combo.activeFocus ? "#aa9c7a" : "#3a4854"
        }
        contentItem: Text {
            text: combo.displayText
            textFormat: Text.PlainText
            color: root.ink
            font: combo.font
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        indicator: Text {
            x: combo.width - width - 9
            y: (combo.height - height) / 2
            text: "v"; color: root.gold; font.pixelSize: 11
        }
        delegate: ItemDelegate {
            required property int index
            width: combo.width
            implicitHeight: 36
            highlighted: combo.highlightedIndex === index
            contentItem: Text {
                text: combo.model && combo.model[index] ? String(combo.model[index][combo.textRole] || "") : ""
                textFormat: Text.PlainText
                color: "#e2e8eb"; font.pixelSize: 12; elide: Text.ElideRight
                verticalAlignment: Text.AlignVCenter
            }
            background: Rectangle { color: parent.highlighted ? "#35474d" : "#15212b" }
        }
        popup: Popup {
            y: combo.height + 3
            width: combo.width
            padding: 1
            implicitHeight: Math.min(contentItem.implicitHeight + 2, 260)
            contentItem: ListView {
                clip: true
                implicitHeight: contentHeight
                model: combo.popup.visible ? combo.delegateModel : null
                currentIndex: combo.highlightedIndex
                ScrollBar.vertical: GgScrollBar {}
            }
            background: Rectangle { color: "#15212b"; border.color: "#59626a"; radius: 4 }
        }
    }
    component BodyCheck: CheckBox {
        id: check
        padding: 0
        spacing: 9
        implicitHeight: Math.max(32, implicitContentHeight)
        indicator: Rectangle {
            width: 20; height: 20
            y: (check.height - height) / 2
            color: check.checked ? "#47665a" : "#111b24"
            border.color: check.activeFocus ? root.gold : "#71847b"
            radius: 3
            Text { anchors.centerIn: parent; text: check.checked ? "x" : ""; color: "#f1e3c9"; font.pixelSize: 16 }
        }
        contentItem: Text {
            text: check.text
            textFormat: Text.PlainText
            color: "#d9e1e5"; font.pixelSize: 13; wrapMode: Text.WordWrap
            leftPadding: check.indicator.width + check.spacing
            verticalAlignment: Text.AlignVCenter
        }
    }
    component SmallLabel: Text {
        color: root.muted
        font.pixelSize: 11
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
    }
    component CitationList: Column {
        id: citationsColumn
        property var citations: []
        spacing: 8
        Repeater {
            model: citationsColumn.citations
            delegate: Column {
                required property var modelData
                width: citationsColumn.width
                spacing: 4
                SmallLabel {
                    width: parent.width
                    color: "#abc6b4"
                    text: String(modelData.source_title || modelData.title || "WEST") + " · PDF-sida " + Number(modelData.page || 1)
                }
                SmallLabel {
                    width: parent.width
                    visible: !!(modelData.quote || modelData.text)
                    text: String(modelData.quote || modelData.text || "")
                }
                BodyButton {
                    objectName: "knowledgeBodySource" + String(modelData.page || 1)
                    text: "Öppna originalsidans tabell >"
                    width: Math.min(implicitWidth, parent.width)
                    enabled: !!modelData.source_id
                    onClicked: root.openCitation(modelData)
                }
            }
        }
    }

    Rectangle { anchors.fill: parent; color: "#10171e"; radius: 7 }

    ColumnLayout {
        anchors.fill: parent
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            spacing: 8
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 3
                Text { text: "MÄNNISKAN / WEST"; color: root.gold; font.pixelSize: 11; font.letterSpacing: 2 }
                SmallLabel { Layout.fillWidth: true; text: "Övning · ej kliniskt beslutsstöd"; color: "#c5b99c" }
            }
            BodyButton { objectName: "knowledgeBodyReset"; text: "Nollställ"; onClicked: root.resetCase() }
        }
        Flow {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredHeight: childrenRect.height
            spacing: 6
            Repeater {
                model: root.ages
                delegate: BodyButton {
                    required property var modelData
                    objectName: "knowledgeBodyAge_" + modelData.id
                    text: String(modelData.label || modelData.id)
                    selected: root.ageGroup === String(modelData.id)
                    onClicked: root.changeAge(modelData.id)
                }
            }
            BodyCombo {
                id: figureChoice
                objectName: "knowledgeBodyFigureChoice"
                width: Math.min(190, Math.max(130, root.width - 12))
                height: 32
                model: root.figures
                textRole: "label"
                displayText: String(root.currentFigure.label || "Välj illustration")
                currentIndex: {
                    for (var i = 0; i < root.figures.length; ++i)
                        if (String(root.figures[i].id) === String(root.currentFigure.id)) return i
                    return -1
                }
                onActivated: function(index) { root.selectedFigureId = String(root.figures[index].id) }
                Accessible.name: "Illustrationslager"
            }
        }
        SmallLabel {
            Layout.fillWidth: true
            text: "Åldersvalen styr illustration och källurval. Kliniska åldersgränser finns i originaltabellerna."
            font.pixelSize: 10
        }
        RowLayout {
            Layout.fillWidth: true
            visible: root.stacked
            BodyButton { objectName: "knowledgeBodyMobileBody"; text: "Kropp"; Layout.fillWidth: true; selected: !root.mobileDetails; onClicked: root.mobileDetails = false }
            BodyButton { objectName: "knowledgeBodyMobileDetails"; text: "Läs / parametrar"; Layout.fillWidth: true; selected: root.mobileDetails; onClicked: root.mobileDetails = true }
        }
        Text {
            Layout.fillWidth: true
            visible: !!root.bundle.stale || root.loadStatus === "ERROR" || !root.figures.length
            text: root.bundle.stale ? "Källunderlaget har ändrats. Kontrollera originalet och granskningsmarkeringarna."
                : (!root.figures.length ? String(root.bundle.notice || root.bundle.message || "Kroppsmaterialet är inte tillgängligt ännu.")
                    : String(root.bundle.notice || "Kroppsmaterialet kunde inte läsas."))
            color: "#ddba80"; font.pixelSize: 12; wrapMode: Text.WordWrap; textFormat: Text.PlainText
        }

        Item {
            id: workspace
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.fillHeight: true
            readonly property real detailWidth: root.stacked ? width : Math.min(390, Math.max(300, width * 0.38))
            readonly property real bodyHeight: height

            Rectangle {
                id: bodyStage
                objectName: "knowledgeBodyStage"
                width: root.stacked ? parent.width : Math.max(150, parent.width - workspace.detailWidth - 12)
                height: workspace.bodyHeight
                visible: !root.stacked || !root.mobileDetails
                color: "#0a1118"; radius: 7; border.color: "#34434b"
                clip: true

                KnowledgeRasterView {
                    id: bodyRaster
                    objectName: "knowledgeBodyRaster"
                    anchors.fill: parent
                    anchors.topMargin: 32
                    anchors.bottomMargin: 46
                    imageSource: String(root.currentFigure.image_url || "")
                    hotspots: root.hotspots
                    selectedHotspotId: root.selectedRegionId
                    onHotspotActivated: function(point) {
                        var id = String(point.region_id || point.id)
                        root.selectRegion(id)
                        if (id !== "back" && id !== "whole") bodyRaster.focusPoint(point.x, point.y, 2.4)
                    }
                }
                Row {
                    anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right
                    anchors.margins: 12; spacing: 7
                    Rectangle { width: 6; height: 6; radius: 3; color: root.stateColor; anchors.verticalCenter: parent.verticalCenter }
                    SmallLabel { text: root.ageLabel() + " · " + String(root.currentFigure.label || "Illustration"); color: "#d5dee3"; width: Math.max(20, parent.width - 20); elide: Text.ElideRight; maximumLineCount: 1 }
                }
                Flow {
                    anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                    anchors.leftMargin: 12; anchors.rightMargin: 12; anchors.bottomMargin: 48
                    height: childrenRect.height
                    spacing: 10
                    SmallLabel {
                        text: "Vald övningsnivå: " + (root.manualSeverity === "unassessed" ? "ej bedömd" : root.manualSeverity === "red" ? "röd" : root.manualSeverity === "orange" ? "orange" : root.manualSeverity === "yellow" ? "gul" : root.manualSeverity === "green" ? "grön" : root.manualSeverity)
                        color: root.stateColor
                    }
                    SmallLabel {
                        objectName: "knowledgeBodyInjuryLegend"
                        visible: root.injuries.length > 0
                        text: "× markerad skada"
                        color: "#f1a494"
                    }
                }
                Rectangle {
                    anchors.left: parent.left; anchors.top: parent.top; anchors.topMargin: 49; anchors.leftMargin: 12
                    width: Math.min(172, Math.max(110, parent.width * 0.38))
                    height: valueColumn.implicitHeight + 14
                    color: "#d9111b23"; radius: 5; border.color: "#34444e"
                    visible: root.enteredValues.length > 0
                    Column {
                        id: valueColumn
                        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 7
                        spacing: 4
                        SmallLabel { text: "ANGIVNA ÖVNINGSVÄRDEN"; color: root.gold; font.pixelSize: 9; width: parent.width }
                        Repeater {
                            model: root.enteredValues
                            delegate: Text {
                                required property var modelData
                                width: valueColumn.width
                                text: modelData.label + "  " + modelData.value + (modelData.unit ? " " + modelData.unit : "")
                                color: "#dee6e9"; font.pixelSize: 11; wrapMode: Text.WordWrap; textFormat: Text.PlainText
                            }
                        }
                    }
                }
                Row {
                    anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: 9
                    spacing: 4
                    BodyButton { objectName: "knowledgeBodyZoomOut"; text: "−"; implicitWidth: 32; onClicked: bodyRaster.zoomAt(0.8, bodyRaster.width / 2, bodyRaster.height / 2) }
                    BodyButton { objectName: "knowledgeBodyZoomReset"; text: bodyRaster.zoom > 1.05 ? "Visa hela" : "Helkropp"; onClicked: bodyRaster.resetView() }
                    BodyButton { objectName: "knowledgeBodyZoomIn"; text: "+"; implicitWidth: 32; onClicked: bodyRaster.zoomAt(1.25, bodyRaster.width / 2, bodyRaster.height / 2) }
                    BodyButton { objectName: "knowledgeBodyInjuryMode"; text: root.injuryMode ? "Markering på" : "Markera skada"; selected: root.injuryMode; onClicked: root.injuryMode = !root.injuryMode }
                }
            }

            Rectangle {
                id: detailPanel
                objectName: "knowledgeBodyDetailPanel"
                x: root.stacked ? 0 : bodyStage.width + 12
                y: 0
                width: workspace.detailWidth
                height: parent.height
                visible: !root.stacked || root.mobileDetails
                color: "#17212a"; radius: 7; border.color: "#34434b"

                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 12
                    spacing: 9
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            Layout.fillWidth: true
                            text: root.selectedRegionId ? root.regionLabel(root.selectedRegionId) : "Hela kroppen"
                            color: root.ink; font.pixelSize: 18; elide: Text.ElideRight; textFormat: Text.PlainText
                        }
                        BodyButton { objectName: "knowledgeBodyAllRegions"; text: "Alla"; visible: !!root.selectedRegionId; onClicked: root.selectRegion("") }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 5
                        Repeater {
                            model: ["Ämnen", "Parametrar", "Moment"]
                            delegate: BodyButton {
                                required property string modelData
                                objectName: "knowledgeBodyTab" + modelData
                                text: modelData
                                Layout.fillWidth: true; implicitWidth: 0
                                selected: root.activeSection === modelData
                                onClicked: root.activeSection = modelData
                            }
                        }
                    }

                    ScrollView {
                        id: detailsScroll
                        objectName: "knowledgeBodyScroll"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                        ScrollBar.vertical: GgScrollBar {}
                        Column {
                            id: detailContent
                            width: detailsScroll.availableWidth
                            spacing: 12

                            Column {
                                width: parent.width; spacing: 9
                                visible: root.activeSection === "Ämnen"
                                BodyField {
                                    objectName: "knowledgeBodySearch"
                                    width: parent.width; placeholderText: "Sök åkomma, skada eller sökorsak…"
                                    text: root.query
                                    onTextEdited: root.query = text
                                    Accessible.name: "Sök bland WEST-ämnen"
                                }
                                SmallLabel { width: parent.width; text: root.topics.length + " ämnen · " + root.ageLabel() }
                                Repeater {
                                    model: root.topics
                                    delegate: Button {
                                        id: topicButton
                                        required property var modelData
                                        objectName: "knowledgeBodyTopic_" + modelData.id
                                        width: detailContent.width
                                        implicitHeight: topicLabel.implicitHeight + 22
                                        padding: 10
                                        background: Rectangle {
                                            color: topicButton.hovered || root.selectedTopicId === String(topicButton.modelData.id) ? "#283842" : "#1b2933"
                                            radius: 4
                                            Rectangle { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 2; color: topicButton.modelData.stale || (topicButton.modelData.review_notes || []).length ? "#d5a765" : "#739b8c" }
                                        }
                                        contentItem: Text {
                                            id: topicLabel
                                            text: String(topicButton.modelData.label || topicButton.modelData.title || "Ämne") + (topicButton.modelData.stale ? " · granska källa" : (topicButton.modelData.review_notes || []).length ? " · granskningspunkt" : "")
                                            color: root.ink; font.pixelSize: 13; wrapMode: Text.WordWrap; textFormat: Text.PlainText
                                        }
                                        onClicked: root.selectTopic(modelData.id)
                                    }
                                }
                                SmallLabel { width: parent.width; visible: root.topics.length === 0; text: "Inga ämnen matchar. Välj Alla eller ändra sökningen." }
                            }

                            Column {
                                width: parent.width; spacing: 11
                                visible: root.activeSection === "Parametrar"
                                SmallLabel { width: parent.width; text: "Fiktivt övningsfall. Tomma fält betyder okänt. Värdena visas på bilden; de beskriver ingen simulerad fysiologi." }
                                BodyCombo {
                                    id: scenarioChoice
                                    objectName: "knowledgeBodyScenario"
                                    width: parent.width
                                    model: [{id: "", label: "Välj ett fiktivt fall…"}].concat(root.scenarios)
                                    textRole: "label"
                                    currentIndex: {
                                        for (var i = 0; i < count; ++i) if (String(model[i].id) === root.selectedScenarioId) return i
                                        return 0
                                    }
                                    onActivated: function(index) { if (index > 0) root.applyScenario(model[index].id) }
                                    Accessible.name: "Fiktivt övningsfall"
                                }
                                SmallLabel { width: parent.width; text: "Övningsnivå · väljs manuellt"; color: root.stateColor }
                                BodyCombo {
                                    objectName: "knowledgeBodySeverity"
                                    width: parent.width
                                    model: root.severityChoices
                                    textRole: "label"
                                    currentIndex: {
                                        for (var i = 0; i < root.severityChoices.length; ++i)
                                            if (root.severityChoices[i].id === root.manualSeverity) return i
                                        return 0
                                    }
                                    onActivated: function(index) { root.manualSeverity = root.severityChoices[index].id; root.evaluate() }
                                    Accessible.name: "Manuellt vald övningsnivå"
                                }
                                GridLayout {
                                    width: parent.width
                                    columns: width >= 300 ? 2 : 1
                                    columnSpacing: 10; rowSpacing: 10
                                    Repeater {
                                        model: root.parameterDefinitions
                                        delegate: ColumnLayout {
                                            id: parameterRow
                                            required property var modelData
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 0
                                            spacing: 4
                                            SmallLabel {
                                                Layout.fillWidth: true
                                                text: String(parameterRow.modelData.label || parameterRow.modelData.id) + (parameterRow.modelData.unit ? " · " + parameterRow.modelData.unit : "")
                                            }
                                            BodyField {
                                                objectName: "knowledgeBodyParameter_" + parameterRow.modelData.id
                                                Layout.fillWidth: true
                                                visible: (parameterRow.modelData.kind || parameterRow.modelData.type || "number") !== "enum"
                                                placeholderText: "Okänt"
                                                inputMethodHints: Qt.ImhFormattedNumbersOnly
                                                text: root.parameters[parameterRow.modelData.id] === undefined || root.parameters[parameterRow.modelData.id] === null
                                                    ? "" : String(root.parameters[parameterRow.modelData.id])
                                                onTextEdited: root.setParameter(parameterRow.modelData.id, text)
                                                Accessible.name: String(parameterRow.modelData.label || parameterRow.modelData.id)
                                            }
                                            BodyCombo {
                                                id: optionChoice
                                                objectName: "knowledgeBodyParameter_" + parameterRow.modelData.id
                                                Layout.fillWidth: true
                                                visible: (parameterRow.modelData.kind || parameterRow.modelData.type || "number") === "enum"
                                                readonly property var choices: [{value: "", label: "Okänt"}].concat((parameterRow.modelData.options || []).map(function(option) {
                                                    return typeof option === "object" ? option : {value: option, label: String(option)}
                                                }))
                                                model: choices
                                                textRole: "label"
                                                currentIndex: {
                                                    var value = root.parameters[parameterRow.modelData.id]
                                                    for (var i = 0; i < choices.length; ++i)
                                                        if (String(choices[i].value) === String(value === undefined || value === null ? "" : value)) return i
                                                    return 0
                                                }
                                                onActivated: function(index) { root.setParameter(parameterRow.modelData.id, choices[index].value) }
                                                Accessible.name: String(parameterRow.modelData.label || parameterRow.modelData.id)
                                            }
                                        }
                                    }
                                }
                                Repeater {
                                    model: root.evaluation.errors || []
                                    delegate: Text {
                                        required property var modelData
                                        width: detailContent.width
                                        text: String(modelData.message || modelData)
                                        color: "#f0ada0"; font.pixelSize: 12; wrapMode: Text.WordWrap; textFormat: Text.PlainText
                                        Accessible.role: Accessible.AlertMessage
                                    }
                                }
                                BodyCheck {
                                    id: newsChoice
                                    objectName: "knowledgeBodyNewsEnabled"
                                    width: parent.width
                                    visible: root.ageGroup === "adult" || root.ageGroup === "older"
                                    checked: root.newsEnabled
                                    text: "NEWS2 skala 1 · endast vuxenövning utan graviditet/postpartum eller skala 2"
                                    onToggled: { root.newsEnabled = checked; root.evaluate() }
                                }
                                Column {
                                    width: parent.width; spacing: 8
                                    visible: root.newsEnabled && !!root.evaluation.score
                                    Text {
                                        width: parent.width
                                        text: String((root.evaluation.score || {}).label || "NEWS2 skala 1 · övning") + ": "
                                            + ((root.evaluation.score || {}).complete && (root.evaluation.score || {}).total !== null
                                                ? String(root.evaluation.score.total) + " poäng" : "ofullständigt underlag")
                                        color: root.gold; font.pixelSize: 14; wrapMode: Text.WordWrap; textFormat: Text.PlainText
                                    }
                                    Text {
                                        width: parent.width
                                        visible: !!(root.evaluation.score || {}).reason
                                        text: String((root.evaluation.score || {}).reason || "")
                                        color: "#edc48b"; font.pixelSize: 12; wrapMode: Text.WordWrap; textFormat: Text.PlainText
                                    }
                                    Repeater {
                                        model: (root.evaluation.score || {}).components || []
                                        delegate: SmallLabel {
                                            required property var modelData
                                            width: detailContent.width
                                            text: String(modelData.label || modelData.id) + ": "
                                                + (modelData.points === null || modelData.points === undefined ? "okänt / behöver kontrolleras" : String(modelData.points) + " poäng")
                                        }
                                    }
                                    SmallLabel { width: parent.width; text: String((root.evaluation.score || {}).notice || "Övningspoängen är en del av bedömningsunderlaget; slutlig triage kräver hela rutinen.") }
                                    CitationList { width: parent.width; citations: (root.evaluation.score || {}).citations || [] }
                                }
                                SmallLabel { width: parent.width; text: "Skador · klicka på kroppen med Markera skada aktiverat"; color: root.gold }
                                Flow {
                                    width: parent.width; spacing: 5
                                    Repeater {
                                        model: root.injuries
                                        delegate: BodyButton {
                                            required property var modelData
                                            text: root.regionLabel(typeof modelData === "object" ? modelData.region_id : modelData) + " ×"
                                            selected: true
                                            width: Math.min(implicitWidth, detailContent.width)
                                            onClicked: root.toggleInjury(typeof modelData === "object" ? modelData.region_id : modelData)
                                        }
                                    }
                                }
                                SmallLabel { width: parent.width; visible: root.injuries.length === 0; text: "Ingen skada markerad i övningen." }
                                SmallLabel { width: parent.width; text: String(root.evaluation.notice || "") }
                            }

                            Column {
                                width: parent.width; spacing: 11
                                visible: root.activeSection === "Moment"
                                Text { width: parent.width; text: String(root.currentTopic.label || root.currentTopic.title || "Välj ett WEST-ämne"); color: root.ink; font.pixelSize: 20; wrapMode: Text.WordWrap; textFormat: Text.PlainText }
                                SmallLabel { width: parent.width; text: String(root.currentTopic.summary || "Välj en kroppsdel och ett ämne för att läsa källorna och öva momenten.") }
                                Repeater {
                                    model: root.currentTopic.review_notes || []
                                    delegate: Text {
                                        required property var modelData
                                        objectName: "knowledgeBodyReviewNote"
                                        width: detailContent.width
                                        text: String(modelData.text || modelData)
                                        textFormat: Text.PlainText
                                        color: "#efc98d"; font.pixelSize: 13; wrapMode: Text.WordWrap
                                    }
                                }
                                Text {
                                    width: parent.width; visible: !!root.currentTopic.stale
                                    text: "Granskningsmarkering: källan eller hänvisningen behöver kontrolleras."
                                    color: "#dfb67a"; font.pixelSize: 12; wrapMode: Text.WordWrap
                                }
                                SmallLabel { width: parent.width; visible: (root.currentTopic.steps || []).length > 0; text: "ÖVNINGSANTECKNINGAR · avprickning sparas bara i denna vy"; color: root.gold; font.pixelSize: 10 }
                                Repeater {
                                    model: root.currentTopic.steps || []
                                    delegate: Column {
                                        id: stepRow
                                        required property var modelData
                                        required property int index
                                        width: detailContent.width
                                        spacing: 7
                                        readonly property string stepId: String(modelData.id || root.selectedTopicId + ":" + index)
                                        BodyCheck {
                                            objectName: "knowledgeBodyStep" + stepRow.index
                                            width: parent.width
                                            checked: !!root.checkedSteps[stepRow.stepId]
                                            text: typeof stepRow.modelData === "string" ? stepRow.modelData : String(stepRow.modelData.text || stepRow.modelData.label || "")
                                            onToggled: root.setStep(stepRow.stepId, checked)
                                        }
                                        CitationList { width: parent.width; citations: stepRow.modelData.citations || [] }
                                        Rectangle { width: parent.width; height: 1; color: "#32414b" }
                                    }
                                }
                                SmallLabel { width: parent.width; text: "Originalets tabeller, varningssymtom och lokala rutiner behöver läsas tillsammans. Listan är ett övningsstöd och garanterar inte att alla kliniska åtgärder är täckta." }
                                CitationList { width: parent.width; citations: root.currentTopic.citations || [] }
                                Repeater {
                                    model: root.currentTopic.illustrations || []
                                    delegate: Column {
                                        id: procedureIllustration
                                        required property var modelData
                                        required property int index
                                        width: detailContent.width
                                        spacing: 6
                                        Text {
                                            width: parent.width
                                            text: String(procedureIllustration.modelData.label || "Momentillustration")
                                            textFormat: Text.PlainText
                                            color: root.gold; font.pixelSize: 13; wrapMode: Text.WordWrap
                                        }
                                        Button {
                                            objectName: "knowledgeBodyOpenIllustration" + procedureIllustration.index
                                            width: parent.width
                                            height: Math.min(240, width * 0.8)
                                            padding: 0
                                            background: Item {}
                                            contentItem: Image {
                                                objectName: "knowledgeBodyMomentIllustration"
                                                source: String(procedureIllustration.modelData.image_url || "")
                                                sourceSize.width: 900
                                                asynchronous: true; cache: true; smooth: true; mipmap: true
                                                fillMode: Image.PreserveAspectFit
                                            }
                                            Accessible.name: "Förstora " + String(procedureIllustration.modelData.label || "momentillustrationen")
                                            onClicked: root.openIllustration(procedureIllustration.modelData)
                                        }
                                        BodyButton {
                                            text: "Förstora illustration"
                                            onClicked: root.openIllustration(procedureIllustration.modelData)
                                        }
                                        SmallLabel {
                                            width: parent.width
                                            text: String(procedureIllustration.modelData.summary || "Förenklad pedagogisk illustration. Läs källan för fullständig rutin.")
                                        }
                                    }
                                }
                                BodyButton { text: "‹ Välj annat ämne"; onClicked: root.activeSection = "Ämnen" }
                            }
                        }
                    }
                }
            }
        }
        SmallLabel {
            Layout.fillWidth: true
            text: "Illustrativ kropp · scrolla för zoom, dra för att flytta · källsidor visar originalets innehåll"
            font.pixelSize: 10
        }
    }
    Dialog {
        id: illustrationDialog
        objectName: "knowledgeBodyIllustrationDialog"
        anchors.centerIn: parent
        width: Math.max(220, Math.min(root.width - 24, 1060))
        height: Math.max(230, Math.min(root.height - 24, 740))
        modal: true
        dim: true
        focus: true
        padding: 12
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onClosed: root.enlargedIllustration = null
        background: Rectangle { color: "#111b24"; border.color: "#69766f"; radius: 7 }
        header: Item {
            implicitHeight: 46
            Text {
                anchors.fill: parent; anchors.margins: 14
                text: String((root.enlargedIllustration || {}).label || "Momentillustration")
                textFormat: Text.PlainText
                color: root.gold; font.pixelSize: 16; elide: Text.ElideRight
                verticalAlignment: Text.AlignVCenter
            }
        }
        contentItem: ColumnLayout {
            spacing: 10
            KnowledgeRasterView {
                id: illustrationRaster
                objectName: "knowledgeBodyIllustrationRaster"
                Layout.fillWidth: true
                Layout.fillHeight: true
                imageSource: String((root.enlargedIllustration || {}).image_url || "")
                hotspots: []
            }
            SmallLabel {
                Layout.fillWidth: true
                maximumLineCount: 3
                elide: Text.ElideRight
                text: String((root.enlargedIllustration || {}).summary || "Pedagogisk illustration. Källans rutin ger det fullständiga innehållet.")
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 6
                BodyButton { objectName: "knowledgeBodyIllustrationZoomOut"; text: "−"; implicitWidth: 32; onClicked: illustrationRaster.zoomAt(0.8, illustrationRaster.width / 2, illustrationRaster.height / 2) }
                BodyButton { objectName: "knowledgeBodyIllustrationZoomReset"; text: "Visa hela"; onClicked: illustrationRaster.resetView() }
                BodyButton { objectName: "knowledgeBodyIllustrationZoomIn"; text: "+"; implicitWidth: 32; onClicked: illustrationRaster.zoomAt(1.25, illustrationRaster.width / 2, illustrationRaster.height / 2) }
                Item { Layout.fillWidth: true }
            }
        }
        footer: Item {
            implicitHeight: 48
            BodyButton {
                objectName: "knowledgeBodyIllustrationClose"
                anchors.right: parent.right; anchors.top: parent.top
                anchors.rightMargin: 12; anchors.topMargin: 5
                text: "Stäng"
                onClicked: illustrationDialog.close()
            }
        }
    }
    Timer { id: evaluationDelay; interval: 180; onTriggered: root.evaluate() }
}
