import QtQuick 2.12
import QtQuick.Controls 2.5
import QtQuick.Layouts 1.12

ApplicationWindow {
    id: root
    width: 1500
    height: 820
    minimumWidth: 1100
    minimumHeight: 680
    title: "医手相通 · 双屏开发预览"
    color: "#EAF0F4"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            Text {
                text: "双屏开发预览"
                color: "#14364B"
                font.pixelSize: 24
                font.bold: true
            }
            Item { Layout.fillWidth: true }
            StatusPill {
                label: backend.systemState === "READY" ? "系统正常"
                     : backend.systemState === "STARTING" ? "系统启动中"
                     : backend.systemState === "ERROR" ? "系统异常"
                     : "系统状态未知"
                active: backend.systemState === "READY"
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 12

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 1
                radius: 14
                color: "white"
                border.color: "#C9D7E0"
                StaffPanel { anchors.fill: parent; previewControls: true }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 1
                radius: 14
                color: "white"
                border.color: "#C9D7E0"
                PatientPanel { anchors.fill: parent; previewControls: true }
            }
        }
    }
}
