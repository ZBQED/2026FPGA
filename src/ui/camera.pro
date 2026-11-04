QT += core gui
CONFIG += c++17 release
TEMPLATE = app
TARGET = medcomm_camera
SOURCES += camera_bridge.cpp
HEADERS += src/cameraframe.h src/cameracapturetiming.h
LIBS += -lrt
