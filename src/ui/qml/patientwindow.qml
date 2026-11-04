import QtQuick 2.12
import QtQuick.Controls 2.5
import QtQuick.Window 2.12

ApplicationWindow {
    title: "医手相通 · 患者端"
    color: "#F7FBFC"
    PatientPanel { anchors.fill: parent; previewControls: false }
}
