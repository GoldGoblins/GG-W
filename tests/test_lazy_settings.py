"""Closed settings have no content tree; first-open content keeps its drafts."""
import json
import os
import re
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression, qmlContext
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QSignalSpy, QTest


PROJECT = Path(__file__).resolve().parents[1]
POPUP_LOADERS = (
    "settingsPopupSurfaceLoader", "settingsProfilesLoader",
    "settingsSurfacesLoader", "settingsVisualEditorLoader", "settingsSearchLoader",
)


class Host(QObject):
    chatTerminalOutput = Signal(str, str)

    @Slot(result=str)
    def listSiteFiles(self):
        return "[]"

    @Slot(str, result=str)
    def startChatTerminal(self, _identity):
        return ""


class LazySettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.host = Host()
        self.engine = QQmlEngine()
        self.warnings = []
        self.engine.warnings.connect(
            lambda rows: self.warnings.extend(row.toString() for row in rows))
        self.engine.rootContext().setContextProperty("fixtureHost", self.host)
        self.component = QQmlComponent(self.engine)
        source = '''import QtQuick
import COMPONENTS
Window {
    width:1100; height:760; visible:true
    property var surfaceHost:fixtureHost
    WorkspaceSurface { objectName:'workspace'; anchors.fill:parent; hostKind:'CODE' }
    SettingsPopup {
        objectName:'popup'; visible:false; width:800; height:700
        frameRadius:7; frameBorder:'#ab12cd'; chatWidthRatio:0.42
        visualEditorMode:'SOURCE'; visualSourceText:'initial fixture source'
    }
}'''.replace("COMPONENTS", json.dumps((PROJECT / "qml/components").as_uri()))
        self.component.setData(source.encode(), QUrl())
        self.assertTrue(self.component.isReady(), [e.toString() for e in self.component.errors()])
        self.window = self.component.create()
        self.assertIsNotNone(self.window, [e.toString() for e in self.component.errors()])
        self.popup = self.window.findChild(QQuickItem, "popup")
        self.workspace = self.window.findChild(QQuickItem, "workspace")
        self.app.processEvents()

    def tearDown(self):
        self.window.setVisible(False)
        self.window.deleteLater()
        self.engine.deleteLater()
        self.app.processEvents()

    def loader(self, parent, name):
        loader = parent.findChild(QQuickItem, name)
        self.assertIsNotNone(loader, name)
        return loader

    def invoke(self, item, expression):
        call = QQmlExpression(qmlContext(item), item, expression)
        call.evaluate()
        self.assertFalse(call.hasError(), call.error().toString())
        self.app.processEvents()

    def test_closed_panels_create_no_content_and_popup_keeps_editor_draft(self):
        loaders = [self.loader(self.popup, name) for name in POPUP_LOADERS]
        for loader in loaders:
            self.assertIsNone(loader.property("item"), loader.objectName())
        self.assertIsNone(self.loader(self.workspace, "workspaceSettingsLoader").property("item"))
        self.assertIsNone(self.loader(self.workspace, "workspaceExternalPane").property("item"))

        # Inputs can change while no child exists. Loader.setSource applies
        # their bindings at construction (the completion ordering is tested in
        # test_deferred_surface), and those same bindings remain live afterwards.
        self.popup.setProperty("frameRadius", 9)
        self.popup.setProperty("page", "EDITOR")
        self.popup.setVisible(True)
        QTest.qWait(30)
        items = [loader.property("item") for loader in loaders]
        self.assertTrue(all(item is not None for item in items), self.warnings)
        settings, profiles, surfaces, editor, search = items
        self.assertEqual(settings.property("frameRadius"), 9)
        self.assertEqual(settings.property("frameBorder").name(), "#ab12cd")
        self.assertEqual(settings.property("chatWidthRatio"), 0.42)
        self.assertEqual(settings.property("section"), "EDITOR")
        self.assertTrue(settings.property("embedded"))
        self.assertEqual(editor.property("sourceText"), "initial fixture source")
        self.assertEqual(editor.property("editorMode"), "SOURCE")
        textareas = [child for child in editor.findChildren(QQuickItem)
                     if child.metaObject().indexOfProperty("selectByMouse") >= 0
                     and child.property("text") == "initial fixture source"]
        self.assertEqual(len(textareas), 1)
        draft = textareas[0]
        draft.setProperty("text", "unsaved visual editor fixture")

        radius = QSignalSpy(self.popup.frameRadiusChangedByUser)
        settings.frameRadiusChangedByUser.emit(13)
        self.assertEqual(radius.count(), 1)
        self.assertEqual(radius.at(0), [13])
        save = QSignalSpy(self.popup.visualSourceSaveRequested)
        editor.sourceSaveRequested.emit(draft.property("text"))
        self.assertEqual(save.at(0), ["unsaved visual editor fixture"])
        self.popup.setVisible(False)
        self.popup.setProperty("frameRadius", 11)
        self.popup.setProperty("visualThemeId", "another-theme")
        self.popup.setProperty("page", "APPEARANCE")
        self.popup.setVisible(True)
        self.app.processEvents()
        for loader, item in zip(loaders, items):
            self.assertIs(loader.property("item"), item)
        self.assertEqual(settings.property("frameRadius"), 11)
        self.assertEqual(settings.property("section"), "APPEARANCE")
        self.assertEqual(profiles.property("themeId"), "another-theme")
        self.assertEqual(draft.property("text"), "unsaved visual editor fixture")
        self.assertFalse(self.warnings, self.warnings)

    def test_reset_standard_before_first_open_is_delivered_once(self):
        self.assertIsNone(self.loader(self.popup, POPUP_LOADERS[0]).property("item"))
        radius = QSignalSpy(self.popup.frameRadiusChangedByUser)
        visual = QSignalSpy(self.popup.resetVisualRequested)
        self.invoke(self.popup, "resetStandard()")
        self.assertEqual(radius.count(), 1)
        self.assertEqual(radius.at(0), [4])
        self.assertEqual(visual.count(), 1)
        self.assertFalse(self.popup.property("_resetStandardPending"))
        self.popup.setVisible(True)
        self.popup.setVisible(False)
        self.popup.setVisible(True)
        self.app.processEvents()
        self.assertEqual(radius.count(), 1)
        self.assertEqual(visual.count(), 1)
        self.assertFalse(self.warnings, self.warnings)

    def test_workspace_settings_and_external_keep_first_instance(self):
        settings_loader = self.loader(self.workspace, "workspaceSettingsLoader")
        external_loader = self.loader(self.workspace, "workspaceExternalPane")
        self.workspace.setProperty("frameRadius", 6)
        self.workspace.setProperty("settingsOpen", True)
        self.app.processEvents()
        settings = settings_loader.property("item")
        self.assertIsNotNone(settings, self.warnings)
        self.assertFalse(self.warnings, self.warnings)
        self.assertEqual(settings.property("frameRadius"), 6)
        radius = QSignalSpy(self.workspace.frameRadiusRequested)
        settings.frameRadiusChangedByUser.emit(8)
        self.assertEqual(radius.at(0), [8])
        # A local in-progress control value must not disappear on close.
        settings.setProperty("section", "WORKSPACE")
        self.workspace.setProperty("settingsOpen", False)
        self.workspace.setProperty("frameRadius", 10)
        self.workspace.setProperty("settingsOpen", True)
        self.app.processEvents()
        self.assertIs(settings_loader.property("item"), settings)
        self.assertEqual(settings.property("section"), "WORKSPACE")
        self.assertEqual(settings.property("frameRadius"), 10)
        self.workspace.setProperty("settingsOpen", False)
        self.workspace.setProperty("hostKind", "EXTERNAL")
        self.app.processEvents()
        external = external_loader.property("item")
        self.assertIsNotNone(external, self.warnings)
        self.assertTrue(self.workspace.property("keepExternal"))
        self.workspace.setProperty("hostKind", "CODE")
        self.app.processEvents()
        self.assertIs(external_loader.property("item"), external)
        self.workspace.setProperty("hostKind", "EXTERNAL")
        self.app.processEvents()
        self.assertIs(external_loader.property("item"), external)
        self.assertFalse(self.warnings, self.warnings)

    def test_redundant_intro_height_binding_caused_warning_without_layout_benefit(self):
        source = (PROJECT / "qml/components/SettingsSurface.qml").read_text(encoding="utf-8")
        match = re.search(r'(?m)^ {12}(?:GGText|Text) \{[^\n]*\n {16}width: parent.width\n {16}visible: root.section === "ALL"', source)
        self.assertIsNotNone(match, "The settings introduction must remain in the geometry probe")
        marker = match.group(0)
        layouts = {}
        with tempfile.TemporaryDirectory(prefix="gg-settings-layout-") as temporary:
            directory = Path(temporary)
            for legacy in (True, False):
                variant = "LegacySettings" if legacy else "CurrentSettings"
                text = source.replace("import QtQuick\n", "import QtQuick\nimport "
                                      + json.dumps((PROJECT / "qml/components").as_uri()) + "\n", 1)
                text = text.replace('import "GGPalette.js" as', 'import '
                    + json.dumps((PROJECT / "qml/components/GGPalette.js").as_uri()) + ' as')
                text = text.replace('import "." as RuntimeTheme', 'import '
                    + json.dumps((PROJECT / "qml/components").as_uri()) + ' as RuntimeTheme')
                text = text.replace("    function sectionVisible(name) {",
                    "    function probeGeometry() { return JSON.stringify({contentHeight:"
                    "modulesColumn.implicitHeight, firstModuleY:modulesColumn.children[1].y}) }\n"
                    "    function sectionVisible(name) {", 1)
                if legacy:
                    # Reproduce the original native-Text bug; the current UI
                    # now uses GGText, while both versions must keep geometry.
                    native_marker = re.sub(r'GGText \{[^\n]*', 'Text {', marker, count=1)
                    text = text.replace(marker, native_marker.replace("                visible:",
                        "                height: visible ? implicitHeight : 0\n                visible:"), 1)
                (directory / (variant + ".qml")).write_text(text, encoding="utf-8")
                fixture = directory / (variant + "Fixture.qml")
                fixture.write_text("import QtQuick\nWindow {width:1100;height:760;visible:true;"
                    + variant + '{objectName:"surface";anchors.fill:parent;visible:false}}', encoding="utf-8")
                engine = QQmlEngine()
                warnings = []
                engine.warnings.connect(lambda rows: warnings.extend(row.toString() for row in rows))
                component = QQmlComponent(engine, QUrl.fromLocalFile(str(fixture)))
                self.assertTrue(component.isReady(), [e.toString() for e in component.errors()])
                window = component.create()
                surface = window.findChild(QQuickItem, "surface")
                self.app.processEvents()
                self.assertFalse(warnings, warnings)
                surface.setVisible(True)
                self.app.processEvents()
                if legacy:
                    self.assertEqual(len(warnings), 1, warnings)
                    self.assertIn('Binding loop detected for property "height"', warnings[0])
                else:
                    self.assertFalse(warnings, warnings)
                geometry = []
                for section in ("ALL", "APPEARANCE", "WORKSPACE"):
                    surface.setProperty("section", section)
                    # Column positions are assigned during polish, after the
                    # visibility bindings change. A single processEvents can
                    # still expose its previous page's geometry on native Qt.
                    previous = None
                    stable = 0
                    for attempt in range(50):
                        for child in surface.findChildren(QQuickItem):
                            child.ensurePolished()
                        surface.ensurePolished()
                        QTest.qWait(20)
                        expression = QQmlExpression(qmlContext(surface), surface, "probeGeometry()")
                        value = expression.evaluate()
                        self.assertFalse(expression.hasError(), expression.error().toString())
                        current = json.loads(value[0] if isinstance(value, tuple) else value)
                        stable = stable + 1 if current == previous else 0
                        previous = current
                        if stable >= 2:
                            break
                    else:
                        self.fail((variant, section, "layout did not settle", previous))
                    geometry.append(current)
                layouts[legacy] = geometry
                window.setVisible(False)
                window.deleteLater()
                engine.deleteLater()
                self.app.processEvents()
        self.assertEqual(layouts[True], layouts[False])


if __name__ == "__main__":
    unittest.main()
