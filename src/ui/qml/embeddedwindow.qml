import QtQuick 2.12

// The single-screen prototype shares the production round-based interface.
// Its role switch replaces the connection badge in the header.
EmbeddedDualWindow {
    id: singleScreen
    width: 800
    height: 480
    staff: Qt.application.arguments.indexOf('--patient') < 0
    TouchButton {
        x: singleScreen.width - 150 * singleScreen.scale
        y: 7 * singleScreen.scale
        width: 138 * singleScreen.scale
        height: 34 * singleScreen.scale
        z: 20
        text: singleScreen.staff ? '切换到患者端' : '切换到工作人员'
        font.pixelSize: 14 * singleScreen.scale
        enabled: !backend.departmentSelectionVisible
        onClicked: singleScreen.staff = !singleScreen.staff
    }
}