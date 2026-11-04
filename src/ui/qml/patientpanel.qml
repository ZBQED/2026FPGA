import QtQuick 2.12
import QtQuick.Controls 2.5
import QtQuick.Layouts 1.12
import MedComm 1.0

Item {
    id: root
    property bool previewControls: false
    property bool videoBusy: videoPlayer.videoPlaying || backend.videoPlaybackState === 'requested' || backend.videoPlaybackState === 'playing'
    property bool videoBlocked: !visible || backend.departmentSelectionVisible || endConversationDialog.visible
    property bool videoSyncReady: false
    property string handledVideoId: ''
    function syncPlayback() {
        if (!videoSyncReady) return
        var state = backend.videoPlaybackState
        var id = backend.videoPlaybackId
        if (videoBlocked || state === 'idle' || state === 'error' || state === 'finished') {
            videoPlayer.stopVideo()
            if (videoBlocked && (state === 'requested' || state === 'playing') && id.length > 0 && handledVideoId !== id) {
                handledVideoId = id
                backend.videoFinished(id)
            }
            return
        }
        if (state === 'requested' && id.length > 0 && id !== handledVideoId) {
            handledVideoId = id
            videoPlayer.playVideo(backend.videoUrl, id)
        }
    }
    onVideoBlockedChanged: syncPlayback()
    Component.onCompleted: { videoSyncReady = true; syncPlayback() }
    Connections { target: backend; onVideoStateChanged: root.syncPlayback() }

    Dialog {
        id: endConversationDialog
        anchors.centerIn: parent
        modal: true
        title: "结束本次对话"
        standardButtons: Dialog.Ok | Dialog.Cancel

        Text {
            width: 320
            text: "确认结束后，将清空双方屏幕上的本轮手语、语音、视频和挂号科室信息。"
            color: "#17394F"
            font.pixelSize: 17
            wrapMode: Text.WordWrap
        }

        onAccepted: backend.clearConversation()
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            Column {
                spacing: 3
                Text {
                    text: "患者端"
                    color: "#17394F"
                    font.pixelSize: 27
                    font.bold: true
                }
                Text {
                    text: "第 " + backend.roundNumber + " 回合 · "
                          + (backend.conversationTurn === 'patient' ? "请患者表达并确认" : "等待工作人员回复")
                    color: "#66808F"
                    font.pixelSize: 15
                }
            }
            Item { Layout.fillWidth: true }
            StatusPill {
                label: backend.voiceOnline ? "语音端已连接" : "语音端未连接"
                active: backend.voiceOnline
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 48
            visible: backend.selectedDepartment.length > 0
            radius: 12
            color: "#EAF6F4"
            border.color: "#79BFAA"

            Text {
                anchors.centerIn: parent
                text: "本次挂号：" + backend.selectedDepartment
                color: "#176B57"
                font.pixelSize: 21
                font.bold: true
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: backend.departmentSelectionVisible ? 390 : 160
            radius: 14
            color: "#101D28"
            clip: true

            CameraPreview {
                id: videoPlayer
                anchors.fill: parent
                anchors.margins: 4
                streaming: !root.videoBlocked
                handBoxes: backend.handBoxes
                handLandmarks: backend.handLandmarks
                bodyBoxes: backend.bodyBoxes
                bodyLandmarks: backend.bodyLandmarks
                onVideoStarted: backend.videoStarted(requestId)
                onVideoFinished: backend.videoFinished(requestId)
                onVideoFailed: backend.videoFailed(requestId, error)
            }

            Column {
                anchors.centerIn: parent
                spacing: 14
                visible: !videoPlayer.available
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "实时摄像画面"
                    color: "white"
                    font.pixelSize: 30
                    font.bold: true
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "等待摄像头连接；工作人员确认后在此播放手语回复"
                    color: "#AFC4D0"
                    font.pixelSize: 17
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: backend.videoPlaybackState === 'error' ? backend.videoPlaybackError : ''
                    color: "#F4C27A"
                    font.pixelSize: 14
                }
            }

            Rectangle {
                anchors.fill: parent
                z: 10
                visible: backend.departmentSelectionVisible
                color: "#F4FAFC"
                radius: 14

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 28
                    spacing: 20

                    Text {
                        Layout.fillWidth: true
                        text: "请选择挂号科室"
                        color: "#17394F"
                        font.pixelSize: 30
                        font.bold: true
                        horizontalAlignment: Text.AlignHCenter
                    }
                    Button {
                        Layout.alignment: Qt.AlignHCenter
                        text: '取消选择'
                        onClicked: backend.cancelDepartments()
                    }
                    Text {
                        Layout.fillWidth: true
                        text: backend.departmentOptions.length > 0
                              ? "点击科室后将同步显示到工作人员端"
                              : "请先在系统配置中添加可选科室"
                        color: "#66808F"
                        font.pixelSize: 16
                        horizontalAlignment: Text.AlignHCenter
                    }
                    GridLayout {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        columns: 2
                        columnSpacing: 16
                        rowSpacing: 16

                        Repeater {
                            model: backend.departmentOptions
                            delegate: Button {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                Layout.minimumHeight: 60
                                text: modelData
                                font.pixelSize: 21
                                font.bold: true
                                onClicked: backend.selectDepartment(modelData)
                            }
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 92
            visible: !backend.departmentSelectionVisible
            radius: 12
            color: "#EEF5FA"
            border.color: "#BCD0DD"
            Text {
                anchors.fill: parent
                anchors.margins: 18
                text: '工作人员已发送：' + backend.patientPrompt
                color: "#17394F"
                font.pixelSize: 24
                font.bold: true
                wrapMode: Text.WordWrap
                verticalAlignment: Text.AlignVCenter
                horizontalAlignment: Text.AlignHCenter
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 112
            visible: !backend.departmentSelectionVisible
            color: '#FFF9EC'
            radius: 10
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 4
                Text {
                    Layout.fillWidth: true
                    text: '我的手语 · ' + (backend.conversationTurn === 'patient' ? '待确认' : '已发送')
                          + '  ' + backend.signTokens.join(' → ')
                    color: '#976A20'
                    font.pixelSize: 15
                    wrapMode: Text.WordWrap
                }
                Text {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    text: backend.conversationTurn === 'staff' ? backend.staffText
                          : backend.signDraftText.length > 0 ? backend.signDraftText : '请按顺序完成手语表达'
                    color: '#17394F'
                    font.pixelSize: 22
                    wrapMode: Text.WordWrap
                }
                Text { text: backend.signHint; color: '#58717E'; font.pixelSize: 12 }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            visible: !backend.departmentSelectionVisible
            Button {
                text: '重新识别'
                Layout.fillWidth: true
                enabled: backend.conversationTurn === 'patient' && backend.systemState === 'READY' && !root.videoBusy
                onClicked: backend.retrySign()
            }
            Button {
                text: '确认识别结果'
                Layout.fillWidth: true
                enabled: backend.conversationTurn === 'patient' && backend.signCanConfirm && backend.systemState === 'READY' && !root.videoBusy
                onClicked: backend.confirmSign()
            }
            Button {
                text: '选择科室'
                enabled: backend.systemState === 'READY'
                onClicked: backend.openDepartments()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            visible: !backend.departmentSelectionVisible
            Button {
                text: "重新播放"
                enabled: backend.videoAvailable && backend.systemState === 'READY' && !root.videoBlocked
                Layout.preferredWidth: 120
                font.pixelSize: 15
                onClicked: backend.replayVideo()
            }
            Button {
                visible: root.previewControls
                text: "模拟患者词序"
                Layout.fillWidth: true
                font.pixelSize: 15
                enabled: backend.conversationTurn === 'patient'
                onClicked: backend.simulateNextSign()
            }
            Item { Layout.fillWidth: !root.previewControls }
            Button {
                text: "结束本次对话"
                Layout.preferredWidth: 150
                font.pixelSize: 15
                onClicked: endConversationDialog.open()
            }
        }
    }
}
