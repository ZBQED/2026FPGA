import QtQuick 2.12

Rectangle {
    id: control
    property string text: ""
    property alias font: label.font
    property bool checked: false
    property bool primary: false
    property bool dark: false
    property bool danger: false
    property bool playIcon: false
    signal clicked()
    implicitWidth: 120
    implicitHeight: 46
    radius: height / 2
    border.width: 1
    border.color: !enabled ? "#E1E3E7" : (primary || dark || danger) ? "#55FFFFFF" : "#FFFFFF"
    gradient: Gradient {
        GradientStop { position: 0; color: !control.enabled ? "#E5E7EB" : control.primary ? (area.pressed ? "#ED672D" : "#FF8549") : control.danger ? "#503839" : control.dark ? "#484B50" : area.pressed ? "#E1E4E9" : control.checked ? "#CBEDDF" : "#FFFFFF" }
        GradientStop { position: 1; color: !control.enabled ? "#DFE2E7" : control.primary ? "#F05E28" : control.danger ? "#2B2E33" : control.dark ? "#35383D" : area.pressed ? "#D6DADF" : control.checked ? "#A8E6CF" : "#F0F2F5" }
    }
    Rectangle {
        x: 1; y: 3; z: -1
        width: parent.width - 2; height: parent.height
        radius: parent.radius
        color: control.primary && control.enabled ? "#26F66B30" : "#0B2B2E33"
    }
    Text {
        id: label
        anchors.fill: parent
        anchors.margins: 6
        anchors.leftMargin: control.playIcon ? font.pixelSize : 6
        text: control.text
        font.pixelSize: 16
        font.bold: true
        color: !control.enabled ? "#8F949B" : (control.primary || control.dark || control.danger) ? "white" : "#2B2E33"
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    Canvas {
        id: playTriangle
        visible: control.playIcon
        anchors.left: parent.left
        anchors.leftMargin: parent.width * 0.15
        anchors.verticalCenter: parent.verticalCenter
        width: label.font.pixelSize * 0.6
        height: label.font.pixelSize * 0.7
        onPaint: {
            var context = getContext('2d')
            context.clearRect(0, 0, width, height)
            context.fillStyle = control.enabled ? '#FFFFFF' : '#8F949B'
            context.beginPath()
            context.moveTo(0, 0)
            context.lineTo(width, height / 2)
            context.lineTo(0, height)
            context.closePath()
            context.fill()
        }
        Connections { target: control; onEnabledChanged: if (control.playIcon) playTriangle.requestPaint() }
    }
    MouseArea {
        id: area
        anchors.fill: parent
        enabled: control.enabled
        onClicked: control.clicked()
    }
}
