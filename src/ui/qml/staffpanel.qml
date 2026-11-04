import QtQuick 2.12
import QtQuick.Controls 2.5
import QtQuick.Layouts 1.12

Item {
    id: root
    property bool previewControls: false

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 22
        spacing: 16

        RowLayout {
            Layout.fillWidth: true
            Column {
                spacing: 3
                Text {
                    text: "工作人员端"
                    color: "#17394F"
                    font.pixelSize: 27
                    font.bold: true
                }
                Text {
                    text: "第 " + backend.roundNumber + " 回合 · "
                          + (backend.conversationTurn === 'patient' ? "等待患者表达并确认" : "请工作人员回复并确认")
                    color: "#66808F"
                    font.pixelSize: 15
                }
            }
            Item { Layout.fillWidth: true }
            StatusPill {
                label: backend.cameraStatus === "READY" ? "OV5640 已连接" : "摄像头等待中"
                active: backend.cameraStatus === "READY"
            }
        }

        Item {
            id: cameraSlot
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(280, Math.max(180, root.height * 0.30))

            Rectangle {
                anchors.centerIn: parent
                width: Math.min(cameraSlot.width, cameraSlot.height * 4 / 3)
                height: width * 3 / 4
                radius: 12
                color: "#132F3F"
                clip: true

                Column {
                    anchors.centerIn: parent
                    spacing: 12
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "OV5640"
                        color: "#A9D4E5"
                        font.pixelSize: 34
                        font.bold: true
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "实时摄像画面接入区"
                        color: "white"
                        font.pixelSize: 20
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "DVP → FPGA预处理 → 手语识别"
                        color: "#9DB3BF"
                        font.pixelSize: 14
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.max(150, root.height * 0.23)
            Layout.minimumHeight: 150
            radius: 14
            color: "#EAF6F4"
            border.color: "#A7D4CA"

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 24
                spacing: 12
                Text {
                    text: "患者已发送"
                    color: "#317466"
                    font.pixelSize: 16
                    font.bold: true
                }
                Text {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    text: backend.staffText
                    color: "#102F2A"
                    font.pixelSize: 30
                    font.bold: true
                    wrapMode: Text.WordWrap
                    verticalAlignment: Text.AlignVCenter
                    horizontalAlignment: Text.AlignHCenter
                }
                Text {
                    Layout.fillWidth: true
                    visible: backend.selectedDepartment.length > 0
                    text: "本次挂号：" + backend.selectedDepartment
                    color: "#176B57"
                    font.pixelSize: 18
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                }
                Text {
                    Layout.fillWidth: true
                    text: backend.signConfidence >= 0
                          ? "置信度 " + Math.round(backend.signConfidence * 100) + "%" : ""
                    color: "#317466"
                    font.pixelSize: 15
                    font.bold: true
                    horizontalAlignment: Text.AlignRight
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 100
            color: '#FFF9EC'
            radius: 10
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 4
                Text { text: '我的语音 · 待确认'; color: '#976A20'; font.pixelSize: 15 }
                Text {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    text: backend.voiceDraftText.length > 0 ? backend.voiceDraftText : '等待本回合工作人员语音'
                    color: '#17394F'
                    font.pixelSize: 23
                    wrapMode: Text.WordWrap
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Button {
                text: '重新识别'
                Layout.fillWidth: true
                enabled: backend.conversationTurn === 'staff' && backend.systemState === 'READY'
                onClicked: backend.retryVoice()
            }
            Button {
                text: '确认识别结果'
                Layout.fillWidth: true
                enabled: backend.conversationTurn === 'staff' && backend.voiceCanConfirm && backend.systemState === 'READY'
                onClicked: backend.confirmVoice()
            }
        }
        RowLayout {
            Layout.fillWidth: true
            visible: root.previewControls
            Button {
                text: "模拟工作人员语音"
                Layout.fillWidth: true
                font.pixelSize: 16
                enabled: backend.conversationTurn === 'staff'
                onClicked: backend.simulateNextVoice()
            }
            Text {
                text: backend.statusMessage
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignRight
                color: "#687D89"
                elide: Text.ElideRight
            }
        }
    }
}
