import QtQuick 2.12
import QtQuick.Layouts 1.12
import QtQuick.Window 2.12
import MedComm 1.0

Window {
    id: root
    property bool staff: Qt.application.arguments.indexOf('--staff') >= 0
    property bool demo: Qt.application.arguments.indexOf('--demo') >= 0
    property real scale: width / 800
    property int signGuideStep: backend.signStatus.indexOf('做完动作后') >= 0 ? 1
                                : (backend.signStatus.indexOf('双手保持下垂') >= 0 || backend.signStatus.indexOf('正在接收') >= 0 || backend.signStatus.indexOf('已识别：') >= 0) ? 2 : 0
    property int tokenCount: backend.signTokens.length
    property int previousTokenCount: 0
    onTokenCountChanged: {
        var appended = tokenCount > previousTokenCount
        previousTokenCount = tokenCount
        Qt.callLater(function() {
            tokenStrip.followTail = appended
            tokenStrip.restoreHorizontal()
        })
    }
    property bool patientTurn: backend.conversationTurn === 'patient'
    property bool videoBusy: cameraImage.videoPlaying || backend.videoPlaybackState === 'requested' || backend.videoPlaybackState === 'playing'
    property bool patientModal: backend.departmentSelectionVisible || confirmEnd.visible
    property bool canPatientAct: patientTurn && backend.systemState === 'READY' && !videoBusy && !patientModal
    property bool canStaffAct: !patientTurn && backend.systemState === 'READY'
    property bool videoBlocked: staff || !visible || backend.departmentSelectionVisible || confirmEnd.visible
    property bool videoSyncReady: false
    property string handledVideoId: ''
    function syncPlayback() {
        if (!videoSyncReady) return
        if (staff) { cameraImage.stopVideo(); return }
        var state = backend.videoPlaybackState
        var id = backend.videoPlaybackId
        if (videoBlocked || state === 'idle' || state === 'error' || state === 'finished') {
            cameraImage.stopVideo()
            if (videoBlocked && (state === 'requested' || state === 'playing') && id.length > 0 && handledVideoId !== id) {
                handledVideoId = id
                backend.videoFinished(id)
            }
            return
        }
        if (state === 'requested' && id.length > 0 && id !== handledVideoId) {
            handledVideoId = id
            cameraImage.playVideo(backend.videoUrl, id)
        }
    }
    onVideoBlockedChanged: syncPlayback()
    Component.onCompleted: { videoSyncReady = true; syncPlayback() }
    Connections {
        target: backend
        onVideoStateChanged: root.syncPlayback()
    }
    visible: true
    visibility: Window.FullScreen
    width: staff ? 800 : 1920
    height: staff ? 480 : 1080
    title: staff ? '医手相通 · 工作人员端' : '医手相通 · 患者端'
    color: '#ECEEF2'

    Text {
        z: 30
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 6 * root.scale
        text: backend.printStatusText
        color: backend.printEnabled ? '#23704A' : '#737983'
        font.pixelSize: 10 * root.scale
    }

    Item {
        id: header
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.topMargin: root.staff ? 0 : 10 * root.scale
        anchors.leftMargin: root.staff ? 14 * root.scale : 14 * root.scale
        anchors.rightMargin: anchors.leftMargin
        height: root.staff ? 48 * root.scale : 32 * root.scale
        Rectangle {
            visible: !root.staff
            anchors.fill: parent
            radius: 8 * root.scale
            color: root.patientTurn ? '#DDEFE7' : '#F5E3D8'
            border.color: '#FFFFFF'
        }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: root.staff ? 0 : 9 * root.scale
            anchors.rightMargin: root.staff ? 0 : 9 * root.scale
            spacing: 7 * root.scale
            Rectangle {
                visible: root.staff
                Layout.preferredWidth: root.staff ? 25 * root.scale : 28 * root.scale
                Layout.preferredHeight: width
                radius: width * 0.32
                color: '#F8F9FA'
                border.color: 'white'
                Rectangle { anchors.centerIn: parent; width: parent.width * 0.54; height: width; radius: width * 0.33; rotation: 45; color: '#FF7033' }
                Rectangle { anchors.centerIn: parent; anchors.horizontalCenterOffset: parent.width * 0.15; width: parent.width * 0.28; height: parent.width * 0.54; radius: width / 2; rotation: 45; color: '#A8E6CF' }
            }
            Text {
                visible: root.staff
                text: '医手相通 · ' + (root.staff ? '工作人员端' : '患者端')
                color: '#2B2E33'
                font.pixelSize: root.staff ? 23 * root.scale : 18 * root.scale
                font.bold: true
            }
            Item { visible: root.staff; Layout.fillWidth: true }
            Rectangle {
                visible: !root.staff
                Layout.preferredWidth: roundLabel.implicitWidth + 24 * root.scale
                Layout.preferredHeight: 24 * root.scale
                radius: 6 * root.scale
                border.color: '#FFF0E8'
                gradient: Gradient {
                    GradientStop { position: 0; color: '#FF8549' }
                    GradientStop { position: 1; color: '#F2662E' }
                }
                Text { id: roundLabel; anchors.centerIn: parent; text: '第 ' + backend.roundNumber + ' 回合'; color: 'white'; font.bold: true; font.pixelSize: 14 * root.scale }
            }
            Text {
                visible: !root.staff
                Layout.maximumWidth: 400 * root.scale
                text: root.videoBusy ? '正在播放工作人员的手语回复' : root.patientTurn ? '现在请患者表达并确认' : '现在请工作人员回复并确认'
                color: '#2B2E33'
                font.pixelSize: 16 * root.scale
                font.bold: true
                elide: Text.ElideRight
            }
            Item { visible: !root.staff; Layout.fillWidth: true }
            Rectangle {
                Layout.preferredWidth: onlineLabel.implicitWidth + 28 * root.scale
                Layout.preferredHeight: 25 * root.scale
                radius: height / 2
                color: (root.staff ? backend.voiceOnline : backend.signOnline) ? '#CDEEE2' : '#E4E5E8'
                border.color: '#F7FFFA'
                Row {
                    anchors.centerIn: parent
                    spacing: 6 * root.scale
                    Rectangle { anchors.verticalCenter: parent.verticalCenter; width: 5 * root.scale; height: width; radius: width / 2; color: (root.staff ? backend.voiceOnline : backend.signOnline) ? '#359675' : '#92979E' }
                    Text {
                        id: onlineLabel
                        text: root.staff ? (backend.voiceOnline ? '语音已连接' : '等待语音连接') : (backend.signOnline ? '手语识别已连接' : '等待手语识别')
                        color: (root.staff ? backend.voiceOnline : backend.signOnline) ? '#286F57' : '#666C75'
                        font.pixelSize: 12 * root.scale
                    }
                }
            }
        }
    }
    Rectangle {
        id: turnBar
        visible: root.staff
        anchors.top: header.bottom
        anchors.topMargin: root.staff ? 8 * root.scale : 0
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: 12 * root.scale
        anchors.rightMargin: 12 * root.scale
        height: root.staff ? 28 * root.scale : 0
        radius: height / 2
        color: root.patientTurn ? '#D9EEE5' : '#F8E1D5'
        border.color: '#FFFFFF'
        Text {
            anchors.centerIn: parent
            text: '第 ' + backend.roundNumber + ' 回合  ·  '
                  + (root.videoBusy ? '正在播放工作人员的手语回复，播放后继续'
                     : root.patientTurn ? '现在请患者表达并确认' : '现在请工作人员回复并确认')
            color: root.patientTurn ? '#286F57' : '#B65329'
            font.pixelSize: 17 * root.scale
            font.bold: true
        }
    }

    ColumnLayout {
        visible: root.staff
        anchors.top: turnBar.bottom
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 12 * root.scale
        spacing: 8 * root.scale
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 0
            Layout.preferredHeight: 136 * root.scale
            color: 'white'
            radius: 10 * root.scale
            border.color: '#FFFFFF'
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 10 * root.scale
                spacing: 4 * root.scale
                Text { text: '患者已发送'; color: '#35856C'; font.pixelSize: 14 * root.scale; font.bold: true }
                Text {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: 0
                    text: backend.staffText
                    color: '#2B2E33'
                    font.pixelSize: 30 * root.scale
                    minimumPixelSize: 23 * root.scale
                    fontSizeMode: Text.Fit
                    font.bold: true
                    wrapMode: Text.WordWrap
                    verticalAlignment: Text.AlignVCenter
                }
            }
        }
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 0
            Layout.preferredHeight: 140 * root.scale
            color: root.patientTurn ? '#F1F3F6' : '#FFF7F1'
            radius: 10 * root.scale
            border.color: '#FFFFFF'
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 10 * root.scale
                spacing: 4 * root.scale
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: '我的语音 · 待确认'; color: '#DF602D'; font.pixelSize: 14 * root.scale; font.bold: true }
                    Item { Layout.fillWidth: true }
                    Text {
                        visible: backend.voiceDraftConfidence >= 0 && backend.voiceDraftText.length > 0
                        text: '置信度 ' + Math.round(backend.voiceDraftConfidence * 100) + '%'
                        color: '#8A776C'
                        font.pixelSize: 13 * root.scale
                    }
                }
                Text {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: 0
                    text: backend.voiceDraftText.length > 0 ? backend.voiceDraftText
                          : root.patientTurn ? '等待患者确认后，再开始语音识别' : '请说出回复，核对后确认发送'
                    color: backend.voiceDraftText.length > 0 ? '#2B2E33' : '#747A83'
                    font.pixelSize: 28 * root.scale
                    minimumPixelSize: 21 * root.scale
                    fontSizeMode: Text.Fit
                    wrapMode: Text.WordWrap
                    verticalAlignment: Text.AlignVCenter
                }
                Text {
                    text: root.patientTurn ? '请等待患者完成本回合' : '确认后发送给患者，并进入下一回合'
                    color: '#747A83'
                    font.pixelSize: 13 * root.scale
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 58 * root.scale
            Layout.minimumHeight: 58 * root.scale
            Layout.maximumHeight: 58 * root.scale
            spacing: 12 * root.scale
            TouchButton {
                Layout.fillWidth: true
                Layout.fillHeight: true
                text: '重新识别'
                font.pixelSize: 23 * root.scale
                enabled: root.canStaffAct
                onClicked: backend.retryVoice()
            }
            TouchButton {
                Layout.fillWidth: true
                Layout.fillHeight: true
                text: '确认识别结果'
                font.pixelSize: 23 * root.scale
                primary: true
                enabled: root.canStaffAct && backend.voiceCanConfirm
                onClicked: backend.confirmVoice()
            }
            TouchButton {
                visible: root.demo
                Layout.fillHeight: true
                text: '模拟语音'
                enabled: root.canStaffAct
                onClicked: backend.simulateNextVoice()
            }
        }
        Text {
            Layout.fillWidth: true
            Layout.preferredHeight: 14 * root.scale
            text: (backend.selectedDepartment.length > 0 ? '科室：' + backend.selectedDepartment + '  ·  ' : '') + backend.statusMessage
            font.pixelSize: 12 * root.scale
            color: '#737983'
            elide: Text.ElideRight
        }
    }

    ColumnLayout {
        id: patientLayout
        visible: !root.staff
        anchors.top: header.bottom
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.topMargin: 9 * root.scale
        anchors.bottomMargin: 9 * root.scale
        anchors.leftMargin: 14 * root.scale
        anchors.rightMargin: 14 * root.scale
        spacing: 7 * root.scale
        RowLayout {
            id: patientWorkArea
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 0
            spacing: 7 * root.scale
            Rectangle {
                id: cameraCard
                objectName: 'patientCameraCard'
                Layout.preferredWidth: (patientLayout.width - 7 * root.scale) * 0.53
                Layout.fillHeight: true
                Layout.minimumHeight: 0
                radius: 12 * root.scale
                // A static surface is deliberate: recognition updates must not
                // repaint an opaque parent over the direct framebuffer preview.
                color: '#2B2E33'
                border.color: '#64666A'
                RowLayout {
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.topMargin: 10 * root.scale
                    anchors.leftMargin: 12 * root.scale
                    anchors.rightMargin: 12 * root.scale
                    height: 25 * root.scale
                    spacing: 8 * root.scale
                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: cameraImage.videoPlaying ? '工作人员手语回复' : '我的手语画面'
                        color: '#F8F9FA'
                        font.pixelSize: 17 * root.scale
                        font.bold: true
                        elide: Text.ElideRight
                    }
                    TouchButton {
                        Layout.preferredWidth: 92 * root.scale
                        Layout.fillHeight: true
                        text: '重新播放'
                        playIcon: true
                        font.pixelSize: 12 * root.scale
                        dark: true
                        enabled: backend.videoAvailable && backend.systemState === 'READY' && !root.videoBlocked
                        onClicked: backend.replayVideo()
                    }
                }
                CameraPreview {
                    id: cameraImage
                    objectName: 'patientCameraPreview'
                    // The native writer aligns absolute framebuffer x to 16 pixels.
                    // Bind every ancestor position so both render paths share one origin.
                    property real cardSceneX: patientLayout.x + patientWorkArea.x + cameraCard.x
                    x: Math.round((cardSceneX + (parent.width - width) / 2) / 16) * 16 - cardSceneX
                    y: 43 * root.scale + Math.max(0, (parent.height - 91 * root.scale - height) / 2)
                    // Keep the native, already verified RGB path and overlay model.
                    width: Math.min(800, parent.width - 24 * root.scale)
                    height: Math.min(480, Math.max(0, parent.height - 91 * root.scale))
                    streaming: !root.staff && root.visible && !backend.departmentSelectionVisible
                    composited: confirmEnd.visible
                    handBoxes: backend.handBoxes
                    handLandmarks: backend.handLandmarks
                    bodyBoxes: backend.bodyBoxes
                    bodyLandmarks: backend.bodyLandmarks
                    onVideoStarted: backend.videoStarted(requestId)
                    onVideoFinished: backend.videoFinished(requestId)
                    onVideoFailed: backend.videoFailed(requestId, error)
                }
                Column {
                    anchors.centerIn: cameraImage
                    visible: !cameraImage.available
                    spacing: 9 * root.scale
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: '实时手语画面'; color: '#F8F9FA'; font.pixelSize: 24 * root.scale; font.bold: true }
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: '等待摄像头连接'; color: '#BEC2CA'; font.pixelSize: 13 * root.scale }
                }
                RowLayout {
                    visible: !root.videoBusy && root.patientTurn && backend.videoPlaybackState !== 'error'
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.leftMargin: 9 * root.scale
                    anchors.rightMargin: 9 * root.scale
                    anchors.bottomMargin: 19 * root.scale
                    height: 23 * root.scale
                    spacing: 3 * root.scale
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredWidth: 128 * root.scale
                        Layout.fillHeight: true
                        radius: height / 2
                        color: root.signGuideStep === 0 ? '#A8E6CF' : 'transparent'
                        Text { anchors.centerIn: parent; text: '双手自然下垂待机'; color: root.signGuideStep === 0 ? '#264B3F' : '#F0F2F5'; font.pixelSize: 10 * root.scale; font.bold: root.signGuideStep === 0 }
                    }
                    Text { text: '→'; color: '#92989F'; font.pixelSize: 13 * root.scale }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredWidth: 84 * root.scale
                        Layout.fillHeight: true
                        radius: height / 2
                        color: root.signGuideStep === 1 ? '#A8E6CF' : 'transparent'
                        Text { anchors.centerIn: parent; text: '做一个动作'; color: root.signGuideStep === 1 ? '#264B3F' : '#F0F2F5'; font.pixelSize: 10 * root.scale; font.bold: root.signGuideStep === 1 }
                    }
                    Text { text: '→'; color: '#92989F'; font.pixelSize: 13 * root.scale }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredWidth: 128 * root.scale
                        Layout.fillHeight: true
                        radius: height / 2
                        color: root.signGuideStep === 2 ? '#A8E6CF' : 'transparent'
                        Text { anchors.centerIn: parent; text: '双手自然下垂完成'; color: root.signGuideStep === 2 ? '#264B3F' : '#F0F2F5'; font.pixelSize: 10 * root.scale; font.bold: root.signGuideStep === 2 }
                    }
                }
                Text {
                    anchors.bottom: parent.bottom
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: 12 * root.scale
                    anchors.rightMargin: 12 * root.scale
                    anchors.bottomMargin: 5 * root.scale
                    text: root.videoBusy ? '请观看手语回复，播放结束后自动恢复摄像'
                          : backend.videoPlaybackState === 'error' ? backend.videoPlaybackError
                          : root.patientTurn ? (backend.signCandidateText.length > 0 ? '正在识别：' + backend.signCandidateText : backend.signStatus)
                          : '本次表达已发送，等待工作人员回复'
                    color: backend.videoPlaybackState === 'error' ? '#FFAF88' : '#BFC6CD'
                    font.pixelSize: 10 * root.scale
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 0
                spacing: 7 * root.scale
                Rectangle {
                    objectName: 'patientStaffMessageCard'
                    Layout.fillWidth: true
                    Layout.preferredHeight: 50 * root.scale
                    Layout.minimumHeight: 50 * root.scale
                    Layout.maximumHeight: 50 * root.scale
                    radius: 10 * root.scale
                    border.color: '#FCFDFE'
                    gradient: Gradient {
                        GradientStop { position: 0; color: '#E3E6EB' }
                        GradientStop { position: 1; color: '#E9EBEF' }
                    }
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 6 * root.scale
                        spacing: 2 * root.scale
                        Text { Layout.fillWidth: true; text: '工作人员已发送'; color: '#737880'; font.pixelSize: 10 * root.scale; horizontalAlignment: Text.AlignLeft }
                        Text {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.minimumHeight: 0
                            Layout.preferredHeight: 30 * root.scale
                            text: backend.patientPrompt
                            color: '#24262A'
                            font.pixelSize: 17 * root.scale
                            minimumPixelSize: 14 * root.scale
                            fontSizeMode: Text.Fit
                            font.bold: true
                            wrapMode: Text.WordWrap
                            verticalAlignment: Text.AlignVCenter
                            horizontalAlignment: Text.AlignLeft
                        }
                    }
                }
                Rectangle {
                    objectName: 'patientLastRecognitionCard'
                    Layout.fillWidth: true
                    Layout.preferredHeight: 75 * root.scale
                    Layout.minimumHeight: 75 * root.scale
                    Layout.maximumHeight: 75 * root.scale
                    radius: 10 * root.scale
                    color: backend.signLastStatus === 'rejected' ? '#FFF5EA' : '#F2F7F3'
                    border.color: backend.signLastStatus === 'rejected' ? '#EAC6A3' : '#FFFFFF'
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 6 * root.scale
                        spacing: 2 * root.scale
                        RowLayout {
                            Layout.fillWidth: true
                            Text { text: '最近识别的词'; font.pixelSize: 11 * root.scale; font.bold: true; color: '#35856C' }
                            Item { Layout.fillWidth: true }
                            Text { text: '最近完整动作'; font.pixelSize: 10 * root.scale; color: '#858B93' }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 20 * root.scale
                            Layout.minimumHeight: 20 * root.scale
                            Layout.maximumHeight: 20 * root.scale
                            Text {
                                objectName: 'patientLastWord'
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: backend.signLastStatus === 'empty' ? '等待完成一个动作' : backend.signLastWord
                                font.pixelSize: 16 * root.scale
                                font.bold: true
                                color: backend.signLastStatus === 'rejected' ? '#A76A29' : '#2B2E33'
                                elide: Text.ElideRight
                            }
                            Text {
                                objectName: 'patientLastConfidence'
                                text: backend.signLastConfidence < 0 ? '模型置信度 —' : '模型置信度 ' + (backend.signLastConfidence * 100).toFixed(1) + '%'
                                font.pixelSize: 10 * root.scale
                                color: '#6E7F75'
                            }
                        }
                        Text {
                            objectName: 'patientLastCompletedAt'
                            Layout.fillWidth: true
                            text: backend.signLastStatus === 'empty' ? '做完动作后，自然放下双手'
                                  : backend.signLastAgeSeconds < 0 ? '上次识别结果'
                                  : backend.signLastAgeSeconds < 60 ? '完成于刚刚'
                                  : backend.signLastAgeSeconds < 3600 ? '完成于 ' + Math.floor(backend.signLastAgeSeconds / 60) + ' 分钟前'
                                  : backend.signLastAgeSeconds < 86400 ? '完成于 ' + Math.floor(backend.signLastAgeSeconds / 3600) + ' 小时前'
                                  : '完成于 ' + Math.floor(backend.signLastAgeSeconds / 86400) + ' 天前'
                            color: '#7F858E'
                            font.pixelSize: 9 * root.scale
                            elide: Text.ElideRight
                        }
                        Text {
                            objectName: 'patientLastReason'
                            Layout.fillWidth: true
                            visible: backend.signLastReason.length > 0
                            text: backend.signLastReason
                            color: '#B46B30'
                            font.pixelSize: 9 * root.scale
                            maximumLineCount: 1
                            elide: Text.ElideRight
                        }
                    }
                }
                Rectangle {
                    id: draftCard
                    objectName: 'patientDraftCard'
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: 0
                    Layout.preferredHeight: 202 * root.scale
                    radius: 12 * root.scale
                    color: '#F1F3F6'
                    border.color: '#FFFFFF'
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 6 * root.scale
                        spacing: 3 * root.scale
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 21 * root.scale
                            Layout.minimumHeight: 21 * root.scale
                            Layout.maximumHeight: 21 * root.scale
                            Text {
                                Layout.fillWidth: true
                                text: root.patientTurn ? '我的手语 · 待确认' : '我的手语 · 已发送'
                                color: root.patientTurn ? '#DF602D' : '#35856C'
                                font.pixelSize: 14 * root.scale
                                font.bold: true
                            }
                            TouchButton {
                                objectName: 'patientUndoButton'
                                Layout.preferredWidth: 91 * root.scale
                                Layout.fillHeight: true
                                text: '撤回上一词'
                                font.pixelSize: 11 * root.scale
                                enabled: root.canPatientAct && backend.signCanUndo
                                onClicked: backend.undoSign()
                            }
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.minimumHeight: 0
                            radius: 9 * root.scale
                            color: '#FFFFFF'
                            border.color: '#F8F9FA'
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 6 * root.scale
                                spacing: 2 * root.scale
                                RowLayout {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 15 * root.scale
                                    Layout.minimumHeight: 15 * root.scale
                                    Layout.maximumHeight: 15 * root.scale
                                    Text {
                                        objectName: 'patientTokenCount'
                                        Layout.fillWidth: true
                                        text: '我的词序 · ' + root.tokenCount + ' 个词'
                                        color: '#626872'
                                        font.pixelSize: 10 * root.scale
                                    }
                                    Text {
                                        visible: tokenStrip.contentWidth > tokenStrip.width
                                        text: '← 左右滑动查看全部 →'
                                        color: '#8B9098'
                                        font.pixelSize: 9 * root.scale
                                    }
                                }
                                Item {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 32 * root.scale
                                    Layout.minimumHeight: 32 * root.scale
                                    Layout.maximumHeight: 32 * root.scale
                                    Rectangle {
                                        objectName: 'patientTokenPlaceholder'
                                        visible: root.tokenCount === 0
                                        anchors.fill: parent
                                        radius: 7 * root.scale
                                        color: '#F8F9FB'
                                        border.color: '#E7E9ED'
                                        Text {
                                            anchors.fill: parent
                                            anchors.margins: 8 * root.scale
                                            text: '等待词语，识别后会按顺序添加'
                                            color: '#8B9098'
                                            font.pixelSize: 11 * root.scale
                                            verticalAlignment: Text.AlignVCenter
                                        }
                                    }
                                    Flickable {
                                        id: tokenStrip
                                        objectName: 'patientTokenStrip'
                                        anchors.fill: parent
                                        visible: root.tokenCount > 0
                                        contentWidth: tokenRow.width
                                        contentHeight: height
                                        clip: true
                                        flickableDirection: Flickable.HorizontalFlick
                                        boundsBehavior: Flickable.StopAtBounds
                                        interactive: contentWidth > width
                                        property bool followTail: true
                                        onMovementStarted: followTail = false
                                        function restoreHorizontal() {
                                            if (followTail) contentX = Math.max(0, contentWidth - width)
                                            else clampHorizontal()
                                            contentY = 0
                                        }
                                        function clampHorizontal() {
                                            contentX = Math.max(0, Math.min(contentX, Math.max(0, contentWidth - width)))
                                            contentY = 0
                                        }
                                        onContentWidthChanged: restoreHorizontal()
                                        onWidthChanged: restoreHorizontal()
                                        onContentYChanged: if (contentY !== 0) contentY = 0
                                        Row {
                                            id: tokenRow
                                            objectName: 'patientTokenRow'
                                            y: (tokenStrip.height - height) / 2
                                            spacing: 4 * root.scale
                                            Repeater {
                                                model: backend.signTokens
                                                Rectangle {
                                                    id: wordChip
                                                    objectName: 'patientTokenChip-' + index
                                                    property string token: modelData
                                                    property int position: index + 1
                                                    width: Math.max(56 * root.scale, wordLabel.implicitWidth + 16 * root.scale)
                                                    height: 24 * root.scale
                                                    radius: 6 * root.scale
                                                    color: '#F1F6F3'
                                                    border.color: '#DDE8E2'
                                                    Text {
                                                        id: wordLabel
                                                        objectName: 'patientTokenLabel-' + index
                                                        anchors.centerIn: parent
                                                        text: wordChip.position + '. ' + wordChip.token
                                                        color: '#41464E'
                                                        font.pixelSize: 12 * root.scale
                                                        font.bold: true
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    Rectangle {
                                        anchors.bottom: parent.bottom
                                        visible: root.tokenCount > 0 && tokenStrip.contentWidth > tokenStrip.width
                                        x: tokenStrip.visibleArea.xPosition * parent.width
                                        width: Math.max(12 * root.scale, tokenStrip.visibleArea.widthRatio * parent.width)
                                        height: 2 * root.scale
                                        radius: height / 2
                                        color: '#BEC7C2'
                                    }
                                }
                                Text {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 8 * root.scale
                                    Layout.minimumHeight: 8 * root.scale
                                    Layout.maximumHeight: 8 * root.scale
                                    text: root.patientTurn ? '组合意图' : '已确认表达'
                                    color: '#8B9098'
                                    font.pixelSize: 8 * root.scale
                                }
                                Text {
                                    objectName: 'patientComposedIntent'
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    Layout.minimumHeight: 36 * root.scale
                                    text: !root.patientTurn ? backend.staffText
                                          : backend.signMatchStatus === 'matched' ? backend.signDraftText
                                          : backend.signMatchStatus === 'unmatched' ? '当前词序暂无对应意图'
                                          : backend.signMatchStatus === 'prefix' ? '请继续按顺序表达'
                                          : '请按顺序完成手语表达'
                                    color: '#24262A'
                                    font.pixelSize: 18 * root.scale
                                    minimumPixelSize: 12 * root.scale
                                    fontSizeMode: Text.Fit
                                    font.bold: true
                                    wrapMode: Text.Wrap
                                    verticalAlignment: Text.AlignVCenter
                                }
                                Text {
                                    objectName: 'patientDraftHint'
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 22 * root.scale
                                    Layout.minimumHeight: 22 * root.scale
                                    Layout.maximumHeight: 22 * root.scale
                                    text: !root.patientTurn ? '已确认发送，请等待工作人员回复。'
                                          : root.tokenCount === 0 ? '请先让双手自然下垂，保持上半身在画面内，再开始表达。'
                                          : backend.signMatchStatus === 'matched' ? '词序已匹配，请核对句子后点击“确认识别结果”。'
                                          : backend.signMatchStatus === 'unmatched' ? '词序暂未匹配，可撤回上一词或重新识别。'
                                          : '请继续按顺序表达，完整匹配后确认发送。'
                                    color: root.patientTurn && backend.signMatchStatus === 'unmatched' ? '#BB622F' : '#737983'
                                    font.pixelSize: 9 * root.scale
                                    minimumPixelSize: 8 * root.scale
                                    fontSizeMode: Text.Fit
                                    wrapMode: Text.Wrap
                                    verticalAlignment: Text.AlignVCenter
                                }
                            }
                        }
                    }
                }
            }
        }
        RowLayout {
            objectName: 'patientActionBar'
            Layout.fillWidth: true
            Layout.preferredHeight: 42 * root.scale
            Layout.minimumHeight: 42 * root.scale
            Layout.maximumHeight: 42 * root.scale
            spacing: 7 * root.scale
            TouchButton {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.minimumWidth: 0
                Layout.fillHeight: true
                text: '重新识别'
                font.pixelSize: 19 * root.scale
                enabled: root.canPatientAct
                onClicked: backend.retrySign()
            }
            TouchButton {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.minimumWidth: 0
                Layout.fillHeight: true
                text: '确认识别结果'
                font.pixelSize: 19 * root.scale
                primary: true
                enabled: root.canPatientAct && backend.signCanConfirm
                onClicked: backend.confirmSign()
            }
            TouchButton {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.minimumWidth: 0
                Layout.fillHeight: true
                text: '选择科室'
                font.pixelSize: 19 * root.scale
                enabled: backend.systemState === 'READY' && !root.patientModal
                onClicked: backend.openDepartments()
            }
            TouchButton {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.minimumWidth: 0
                Layout.fillHeight: true
                text: '结束对话'
                font.pixelSize: 19 * root.scale
                danger: true
                enabled: backend.systemState !== 'ERROR' && !backend.departmentSelectionVisible
                onClicked: confirmEnd.visible = true
            }
            TouchButton {
                visible: root.demo
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.fillHeight: true
                text: '模拟手语'
                enabled: root.canPatientAct
                onClicked: backend.simulateNextSign()
            }
        }
        Text {
            Layout.fillWidth: true
            Layout.preferredHeight: 12 * root.scale
            text: (backend.selectedDepartment.length > 0 ? '已选科室：' + backend.selectedDepartment + '  ·  ' : '') + backend.statusMessage
            color: '#80858D'
            font.pixelSize: 10 * root.scale
            elide: Text.ElideRight
        }
    }

    Rectangle {
        anchors.fill: parent
        visible: !root.staff && backend.departmentSelectionVisible
        color: '#ECEEF2'
        MouseArea { anchors.fill: parent }
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 20 * root.scale
            spacing: 12 * root.scale
            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 46 * root.scale
                Layout.minimumHeight: 46 * root.scale
                Layout.maximumHeight: 46 * root.scale
                Text { text: '请选择挂号科室'; font.pixelSize: 27 * root.scale; font.bold: true; color: '#2B2E33' }
                Item { Layout.fillWidth: true }
                TouchButton {
                    Layout.preferredWidth: 135 * root.scale
                    Layout.fillHeight: true
                    text: '取消选择'
                    font.pixelSize: 21 * root.scale
                    onClicked: backend.cancelDepartments()
                }
            }
            GridLayout {
                columns: 4
                columnSpacing: 7 * root.scale
                rowSpacing: 7 * root.scale
                Layout.fillWidth: true
                Layout.fillHeight: true
                Repeater {
                    model: backend.departmentOptions
                    TouchButton {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        text: modelData
                        radius: 12 * root.scale
                        font.pixelSize: 22 * root.scale
                        enabled: backend.systemState === 'READY'
                        onClicked: backend.selectDepartment(modelData)
                    }
                }
            }
        }
    }
    Rectangle {
        id: confirmEnd
        anchors.fill: parent
        visible: false
        color: '#AA2B2E33'
        MouseArea { anchors.fill: parent }
        Rectangle {
            anchors.centerIn: parent
            width: 440 * root.scale
            height: 180 * root.scale
            radius: 12 * root.scale
            color: 'white'
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 20 * root.scale
                Text { text: '确认结束本次对话？'; font.pixelSize: 24 * root.scale; color: '#2B2E33' }
                Text { text: backend.printEnabled ? '将打印本次对话记录，并清空双方屏幕' : '双方屏幕将清空本次对话，并从第 1 回合开始'; font.pixelSize: 15 * root.scale; color: '#737983' }
                Item { Layout.fillHeight: true }
                RowLayout {
                    TouchButton {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 46 * root.scale
                        font.pixelSize: 18 * root.scale
                        text: '继续对话'
                        onClicked: confirmEnd.visible = false
                    }
                    TouchButton {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 46 * root.scale
                        font.pixelSize: 18 * root.scale
                        text: '确认结束'
                        onClicked: { backend.clearConversation(); confirmEnd.visible = false }
                    }
                }
            }
        }
    }
}
