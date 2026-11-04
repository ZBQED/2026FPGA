QT += core gui qml quick network multimedia
CONFIG += c++17 release
TEMPLATE = app
TARGET = medcomm_touch_ui
SOURCES += src/main.cpp src/backend.cpp src/camerapreview.cpp
HEADERS += src/backend.h src/camerapreview.h
RESOURCES += qml.qrc
DEFINES += MEDCOMM_PROJECT_ROOT=\"/opt/medcomm\"
INCLUDEPATH += src
LIBS += -L$$PWD/../../board/lib -llive_integer_frame
