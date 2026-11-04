import QtQuick 2.12
import QtQuick.Window 2.12

QtObject {
    id: root
    property bool previewMode: Qt.application.arguments.indexOf("--preview") >= 0
                               || Qt.application.screens.length < 2

    property var previewWindow: PreviewWindow {
        visible: root.previewMode
    }

    property var staffWindow: StaffWindow {
        visibility: root.previewMode ? Window.Hidden : Window.FullScreen
        screen: Qt.application.screens.length > 0 ? Qt.application.screens[0] : null
    }

    property var patientWindow: PatientWindow {
        visibility: root.previewMode ? Window.Hidden : Window.FullScreen
        screen: Qt.application.screens.length > 1 ? Qt.application.screens[1]
                                                   : (Qt.application.screens.length > 0 ? Qt.application.screens[0] : null)
    }
}
