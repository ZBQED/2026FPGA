/****************************************************************************
** Meta object code from reading C++ file 'CameraPreview.h'
**
** Created by: The Qt Meta Object Compiler version 67 (Qt 5.12.8)
**
** WARNING! All changes made in this file will be lost!
*****************************************************************************/

#include "camerapreview.h"
#include <QtCore/qbytearray.h>
#include <QtCore/qmetatype.h>
#if !defined(Q_MOC_OUTPUT_REVISION)
#error "The header file 'CameraPreview.h' doesn't include <QObject>."
#elif Q_MOC_OUTPUT_REVISION != 67
#error "This file was generated using the moc from 5.12.8. It"
#error "cannot be used with the include files from this version of Qt."
#error "(The moc has changed too much.)"
#endif

QT_BEGIN_MOC_NAMESPACE
QT_WARNING_PUSH
QT_WARNING_DISABLE_DEPRECATED
struct qt_meta_stringdata_CameraPreview_t {
    QByteArrayData data[25];
    char stringdata0[293];
};
#define QT_MOC_LITERAL(idx, ofs, len) \
    Q_STATIC_BYTE_ARRAY_DATA_HEADER_INITIALIZER_WITH_OFFSET(len, \
    qptrdiff(offsetof(qt_meta_stringdata_CameraPreview_t, stringdata0) + ofs \
        - idx * sizeof(QByteArrayData)) \
    )
static const qt_meta_stringdata_CameraPreview_t qt_meta_stringdata_CameraPreview = {
    {
QT_MOC_LITERAL(0, 0, 13), // "CameraPreview"
QT_MOC_LITERAL(1, 14, 12), // "frameChanged"
QT_MOC_LITERAL(2, 27, 0), // ""
QT_MOC_LITERAL(3, 28, 16), // "streamingChanged"
QT_MOC_LITERAL(4, 45, 17), // "compositedChanged"
QT_MOC_LITERAL(5, 63, 19), // "videoPlayingChanged"
QT_MOC_LITERAL(6, 83, 12), // "videoStarted"
QT_MOC_LITERAL(7, 96, 9), // "requestId"
QT_MOC_LITERAL(8, 106, 13), // "videoFinished"
QT_MOC_LITERAL(9, 120, 11), // "videoFailed"
QT_MOC_LITERAL(10, 132, 5), // "error"
QT_MOC_LITERAL(11, 138, 9), // "playVideo"
QT_MOC_LITERAL(12, 148, 8), // "manifest"
QT_MOC_LITERAL(13, 157, 9), // "stopVideo"
QT_MOC_LITERAL(14, 167, 9), // "available"
QT_MOC_LITERAL(15, 177, 12), // "paintedWidth"
QT_MOC_LITERAL(16, 190, 13), // "paintedHeight"
QT_MOC_LITERAL(17, 204, 9), // "streaming"
QT_MOC_LITERAL(18, 214, 10), // "composited"
QT_MOC_LITERAL(19, 225, 12), // "videoPlaying"
QT_MOC_LITERAL(20, 238, 6), // "direct"
QT_MOC_LITERAL(21, 245, 9), // "handBoxes"
QT_MOC_LITERAL(22, 255, 13), // "handLandmarks"
QT_MOC_LITERAL(23, 269, 9), // "bodyBoxes"
QT_MOC_LITERAL(24, 279, 13) // "bodyLandmarks"

    },
    "CameraPreview\0frameChanged\0\0"
    "streamingChanged\0compositedChanged\0"
    "videoPlayingChanged\0videoStarted\0"
    "requestId\0videoFinished\0videoFailed\0"
    "error\0playVideo\0manifest\0stopVideo\0"
    "available\0paintedWidth\0paintedHeight\0"
    "streaming\0composited\0videoPlaying\0"
    "direct\0handBoxes\0handLandmarks\0bodyBoxes\0"
    "bodyLandmarks"
};
#undef QT_MOC_LITERAL

static const uint qt_meta_data_CameraPreview[] = {

 // content:
       8,       // revision
       0,       // classname
       0,    0, // classinfo
       9,   14, // methods
      11,   80, // properties
       0,    0, // enums/sets
       0,    0, // constructors
       0,       // flags
       7,       // signalCount

 // signals: name, argc, parameters, tag, flags
       1,    0,   59,    2, 0x06 /* Public */,
       3,    0,   60,    2, 0x06 /* Public */,
       4,    0,   61,    2, 0x06 /* Public */,
       5,    0,   62,    2, 0x06 /* Public */,
       6,    1,   63,    2, 0x06 /* Public */,
       8,    1,   66,    2, 0x06 /* Public */,
       9,    2,   69,    2, 0x06 /* Public */,

 // methods: name, argc, parameters, tag, flags
      11,    2,   74,    2, 0x02 /* Public */,
      13,    0,   79,    2, 0x02 /* Public */,

 // signals: parameters
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void, QMetaType::QString,    7,
    QMetaType::Void, QMetaType::QString,    7,
    QMetaType::Void, QMetaType::QString, QMetaType::QString,    7,   10,

 // methods: parameters
    QMetaType::Void, QMetaType::QUrl, QMetaType::QString,   12,    7,
    QMetaType::Void,

 // properties: name, type, flags
      14, QMetaType::Bool, 0x00495001,
      15, QMetaType::QReal, 0x00495001,
      16, QMetaType::QReal, 0x00495001,
      17, QMetaType::Bool, 0x00495103,
      18, QMetaType::Bool, 0x00495103,
      19, QMetaType::Bool, 0x00495001,
      20, QMetaType::Bool, 0x00095401,
      21, QMetaType::QVariantList, 0x00095003,
      22, QMetaType::QVariantList, 0x00095003,
      23, QMetaType::QVariantList, 0x00095003,
      24, QMetaType::QVariantList, 0x00095003,

 // properties: notify_signal_id
       0,
       0,
       0,
       1,
       2,
       3,
       0,
       0,
       0,
       0,
       0,

       0        // eod
};

void CameraPreview::qt_static_metacall(QObject *_o, QMetaObject::Call _c, int _id, void **_a)
{
    if (_c == QMetaObject::InvokeMetaMethod) {
        auto *_t = static_cast<CameraPreview *>(_o);
        Q_UNUSED(_t)
        switch (_id) {
        case 0: _t->frameChanged(); break;
        case 1: _t->streamingChanged(); break;
        case 2: _t->compositedChanged(); break;
        case 3: _t->videoPlayingChanged(); break;
        case 4: _t->videoStarted((*reinterpret_cast< const QString(*)>(_a[1]))); break;
        case 5: _t->videoFinished((*reinterpret_cast< const QString(*)>(_a[1]))); break;
        case 6: _t->videoFailed((*reinterpret_cast< const QString(*)>(_a[1])),(*reinterpret_cast< const QString(*)>(_a[2]))); break;
        case 7: _t->playVideo((*reinterpret_cast< const QUrl(*)>(_a[1])),(*reinterpret_cast< const QString(*)>(_a[2]))); break;
        case 8: _t->stopVideo(); break;
        default: ;
        }
    } else if (_c == QMetaObject::IndexOfMethod) {
        int *result = reinterpret_cast<int *>(_a[0]);
        {
            using _t = void (CameraPreview::*)();
            if (*reinterpret_cast<_t *>(_a[1]) == static_cast<_t>(&CameraPreview::frameChanged)) {
                *result = 0;
                return;
            }
        }
        {
            using _t = void (CameraPreview::*)();
            if (*reinterpret_cast<_t *>(_a[1]) == static_cast<_t>(&CameraPreview::streamingChanged)) {
                *result = 1;
                return;
            }
        }
        {
            using _t = void (CameraPreview::*)();
            if (*reinterpret_cast<_t *>(_a[1]) == static_cast<_t>(&CameraPreview::compositedChanged)) {
                *result = 2;
                return;
            }
        }
        {
            using _t = void (CameraPreview::*)();
            if (*reinterpret_cast<_t *>(_a[1]) == static_cast<_t>(&CameraPreview::videoPlayingChanged)) {
                *result = 3;
                return;
            }
        }
        {
            using _t = void (CameraPreview::*)(const QString & );
            if (*reinterpret_cast<_t *>(_a[1]) == static_cast<_t>(&CameraPreview::videoStarted)) {
                *result = 4;
                return;
            }
        }
        {
            using _t = void (CameraPreview::*)(const QString & );
            if (*reinterpret_cast<_t *>(_a[1]) == static_cast<_t>(&CameraPreview::videoFinished)) {
                *result = 5;
                return;
            }
        }
        {
            using _t = void (CameraPreview::*)(const QString & , const QString & );
            if (*reinterpret_cast<_t *>(_a[1]) == static_cast<_t>(&CameraPreview::videoFailed)) {
                *result = 6;
                return;
            }
        }
    }
#ifndef QT_NO_PROPERTIES
    else if (_c == QMetaObject::ReadProperty) {
        auto *_t = static_cast<CameraPreview *>(_o);
        Q_UNUSED(_t)
        void *_v = _a[0];
        switch (_id) {
        case 0: *reinterpret_cast< bool*>(_v) = _t->available(); break;
        case 1: *reinterpret_cast< qreal*>(_v) = _t->paintedWidth(); break;
        case 2: *reinterpret_cast< qreal*>(_v) = _t->paintedHeight(); break;
        case 3: *reinterpret_cast< bool*>(_v) = _t->streaming(); break;
        case 4: *reinterpret_cast< bool*>(_v) = _t->composited(); break;
        case 5: *reinterpret_cast< bool*>(_v) = _t->videoPlaying(); break;
        case 6: *reinterpret_cast< bool*>(_v) = _t->direct(); break;
        case 7: *reinterpret_cast< QVariantList*>(_v) = _t->m_handBoxes; break;
        case 8: *reinterpret_cast< QVariantList*>(_v) = _t->m_handLandmarks; break;
        case 9: *reinterpret_cast< QVariantList*>(_v) = _t->m_bodyBoxes; break;
        case 10: *reinterpret_cast< QVariantList*>(_v) = _t->m_bodyLandmarks; break;
        default: break;
        }
    } else if (_c == QMetaObject::WriteProperty) {
        auto *_t = static_cast<CameraPreview *>(_o);
        Q_UNUSED(_t)
        void *_v = _a[0];
        switch (_id) {
        case 3: _t->setStreaming(*reinterpret_cast< bool*>(_v)); break;
        case 4: _t->setComposited(*reinterpret_cast< bool*>(_v)); break;
        case 7:
            if (_t->m_handBoxes != *reinterpret_cast< QVariantList*>(_v)) {
                _t->m_handBoxes = *reinterpret_cast< QVariantList*>(_v);
            }
            break;
        case 8:
            if (_t->m_handLandmarks != *reinterpret_cast< QVariantList*>(_v)) {
                _t->m_handLandmarks = *reinterpret_cast< QVariantList*>(_v);
            }
            break;
        case 9:
            if (_t->m_bodyBoxes != *reinterpret_cast< QVariantList*>(_v)) {
                _t->m_bodyBoxes = *reinterpret_cast< QVariantList*>(_v);
            }
            break;
        case 10:
            if (_t->m_bodyLandmarks != *reinterpret_cast< QVariantList*>(_v)) {
                _t->m_bodyLandmarks = *reinterpret_cast< QVariantList*>(_v);
            }
            break;
        default: break;
        }
    } else if (_c == QMetaObject::ResetProperty) {
    }
#endif // QT_NO_PROPERTIES
}

QT_INIT_METAOBJECT const QMetaObject CameraPreview::staticMetaObject = { {
    &QQuickPaintedItem::staticMetaObject,
    qt_meta_stringdata_CameraPreview.data,
    qt_meta_data_CameraPreview,
    qt_static_metacall,
    nullptr,
    nullptr
} };


const QMetaObject *CameraPreview::metaObject() const
{
    return QObject::d_ptr->metaObject ? QObject::d_ptr->dynamicMetaObject() : &staticMetaObject;
}

void *CameraPreview::qt_metacast(const char *_clname)
{
    if (!_clname) return nullptr;
    if (!strcmp(_clname, qt_meta_stringdata_CameraPreview.stringdata0))
        return static_cast<void*>(this);
    return QQuickPaintedItem::qt_metacast(_clname);
}

int CameraPreview::qt_metacall(QMetaObject::Call _c, int _id, void **_a)
{
    _id = QQuickPaintedItem::qt_metacall(_c, _id, _a);
    if (_id < 0)
        return _id;
    if (_c == QMetaObject::InvokeMetaMethod) {
        if (_id < 9)
            qt_static_metacall(this, _c, _id, _a);
        _id -= 9;
    } else if (_c == QMetaObject::RegisterMethodArgumentMetaType) {
        if (_id < 9)
            *reinterpret_cast<int*>(_a[0]) = -1;
        _id -= 9;
    }
#ifndef QT_NO_PROPERTIES
    else if (_c == QMetaObject::ReadProperty || _c == QMetaObject::WriteProperty
            || _c == QMetaObject::ResetProperty || _c == QMetaObject::RegisterPropertyMetaType) {
        qt_static_metacall(this, _c, _id, _a);
        _id -= 11;
    } else if (_c == QMetaObject::QueryPropertyDesignable) {
        _id -= 11;
    } else if (_c == QMetaObject::QueryPropertyScriptable) {
        _id -= 11;
    } else if (_c == QMetaObject::QueryPropertyStored) {
        _id -= 11;
    } else if (_c == QMetaObject::QueryPropertyEditable) {
        _id -= 11;
    } else if (_c == QMetaObject::QueryPropertyUser) {
        _id -= 11;
    }
#endif // QT_NO_PROPERTIES
    return _id;
}

// SIGNAL 0
void CameraPreview::frameChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 0, nullptr);
}

// SIGNAL 1
void CameraPreview::streamingChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 1, nullptr);
}

// SIGNAL 2
void CameraPreview::compositedChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 2, nullptr);
}

// SIGNAL 3
void CameraPreview::videoPlayingChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 3, nullptr);
}

// SIGNAL 4
void CameraPreview::videoStarted(const QString & _t1)
{
    void *_a[] = { nullptr, const_cast<void*>(reinterpret_cast<const void*>(&_t1)) };
    QMetaObject::activate(this, &staticMetaObject, 4, _a);
}

// SIGNAL 5
void CameraPreview::videoFinished(const QString & _t1)
{
    void *_a[] = { nullptr, const_cast<void*>(reinterpret_cast<const void*>(&_t1)) };
    QMetaObject::activate(this, &staticMetaObject, 5, _a);
}

// SIGNAL 6
void CameraPreview::videoFailed(const QString & _t1, const QString & _t2)
{
    void *_a[] = { nullptr, const_cast<void*>(reinterpret_cast<const void*>(&_t1)), const_cast<void*>(reinterpret_cast<const void*>(&_t2)) };
    QMetaObject::activate(this, &staticMetaObject, 6, _a);
}
QT_WARNING_POP
QT_END_MOC_NAMESPACE
