import QtQuick 2.12
import QtQuick.Controls 2.5

Rectangle {
    property string label: ""
    property bool active: false
    implicitWidth: statusText.implicitWidth + 34
    implicitHeight: 34
    radius: 17
    color: active ? "#DDF4EA" : "#FBE9E7"
    border.color: active ? "#6BBF9B" : "#E39A91"

    Row {
        anchors.centerIn: parent
        spacing: 8
        Rectangle {
            width: 9
            height: 9
            radius: 5
            color: active ? "#168A61" : "#B94A42"
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            id: statusText
            text: parent.parent.label
            color: active ? "#126446" : "#8B342F"
            font.pixelSize: 14
            font.bold: true
        }
    }
}
