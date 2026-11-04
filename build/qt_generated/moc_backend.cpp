/****************************************************************************
** Meta object code from reading C++ file 'Backend.h'
**
** Created by: The Qt Meta Object Compiler version 67 (Qt 5.12.8)
**
** WARNING! All changes made in this file will be lost!
*****************************************************************************/

#include "backend.h"
#include <QtCore/qbytearray.h>
#include <QtCore/qmetatype.h>
#if !defined(Q_MOC_OUTPUT_REVISION)
#error "The header file 'Backend.h' doesn't include <QObject>."
#elif Q_MOC_OUTPUT_REVISION != 67
#error "This file was generated using the moc from 5.12.8. It"
#error "cannot be used with the include files from this version of Qt."
#error "(The moc has changed too much.)"
#endif

QT_BEGIN_MOC_NAMESPACE
QT_WARNING_PUSH
QT_WARNING_DISABLE_DEPRECATED
struct qt_meta_stringdata_Backend_t {
    QByteArrayData data[79];
    char stringdata0[1153];
};
#define QT_MOC_LITERAL(idx, ofs, len) \
    Q_STATIC_BYTE_ARRAY_DATA_HEADER_INITIALIZER_WITH_OFFSET(len, \
    qptrdiff(offsetof(qt_meta_stringdata_Backend_t, stringdata0) + ofs \
        - idx * sizeof(QByteArrayData)) \
    )
static const qt_meta_stringdata_Backend_t qt_meta_stringdata_Backend = {
    {
QT_MOC_LITERAL(0, 0, 7), // "Backend"
QT_MOC_LITERAL(1, 8, 17), // "signTokensChanged"
QT_MOC_LITERAL(2, 26, 0), // ""
QT_MOC_LITERAL(3, 27, 24), // "departmentOptionsChanged"
QT_MOC_LITERAL(4, 52, 15), // "snapshotChanged"
QT_MOC_LITERAL(5, 68, 20), // "firstSnapshotApplied"
QT_MOC_LITERAL(6, 89, 18), // "cameraStateChanged"
QT_MOC_LITERAL(7, 108, 18), // "recognitionChanged"
QT_MOC_LITERAL(8, 127, 18), // "lastGestureChanged"
QT_MOC_LITERAL(9, 146, 21), // "lastGestureAgeChanged"
QT_MOC_LITERAL(10, 168, 14), // "overlayChanged"
QT_MOC_LITERAL(11, 183, 17), // "videoStateChanged"
QT_MOC_LITERAL(12, 201, 16), // "simulateNextSign"
QT_MOC_LITERAL(13, 218, 17), // "simulateNextVoice"
QT_MOC_LITERAL(14, 236, 16), // "selectDepartment"
QT_MOC_LITERAL(15, 253, 10), // "department"
QT_MOC_LITERAL(16, 264, 11), // "replayVideo"
QT_MOC_LITERAL(17, 276, 17), // "clearConversation"
QT_MOC_LITERAL(18, 294, 9), // "retrySign"
QT_MOC_LITERAL(19, 304, 8), // "undoSign"
QT_MOC_LITERAL(20, 313, 11), // "confirmSign"
QT_MOC_LITERAL(21, 325, 10), // "retryVoice"
QT_MOC_LITERAL(22, 336, 12), // "confirmVoice"
QT_MOC_LITERAL(23, 349, 15), // "openDepartments"
QT_MOC_LITERAL(24, 365, 17), // "cancelDepartments"
QT_MOC_LITERAL(25, 383, 12), // "videoStarted"
QT_MOC_LITERAL(26, 396, 9), // "requestId"
QT_MOC_LITERAL(27, 406, 13), // "videoFinished"
QT_MOC_LITERAL(28, 420, 11), // "videoFailed"
QT_MOC_LITERAL(29, 432, 5), // "error"
QT_MOC_LITERAL(30, 438, 11), // "systemState"
QT_MOC_LITERAL(31, 450, 13), // "statusMessage"
QT_MOC_LITERAL(32, 464, 16), // "conversationTurn"
QT_MOC_LITERAL(33, 481, 11), // "roundNumber"
QT_MOC_LITERAL(34, 493, 10), // "signTokens"
QT_MOC_LITERAL(35, 504, 13), // "signDraftText"
QT_MOC_LITERAL(36, 518, 15), // "signMatchStatus"
QT_MOC_LITERAL(37, 534, 13), // "signMatchHint"
QT_MOC_LITERAL(38, 548, 8), // "signHint"
QT_MOC_LITERAL(39, 557, 14), // "signCanConfirm"
QT_MOC_LITERAL(40, 572, 11), // "signCanUndo"
QT_MOC_LITERAL(41, 584, 14), // "voiceDraftText"
QT_MOC_LITERAL(42, 599, 20), // "voiceDraftConfidence"
QT_MOC_LITERAL(43, 620, 15), // "voiceCanConfirm"
QT_MOC_LITERAL(44, 636, 11), // "voiceOnline"
QT_MOC_LITERAL(45, 648, 12), // "cameraStatus"
QT_MOC_LITERAL(46, 661, 9), // "cameraUrl"
QT_MOC_LITERAL(47, 671, 10), // "signOnline"
QT_MOC_LITERAL(48, 682, 10), // "signStatus"
QT_MOC_LITERAL(49, 693, 17), // "signCandidateText"
QT_MOC_LITERAL(50, 711, 23), // "signCandidateConfidence"
QT_MOC_LITERAL(51, 735, 12), // "signLastWord"
QT_MOC_LITERAL(52, 748, 18), // "signLastConfidence"
QT_MOC_LITERAL(53, 767, 19), // "signLastCompletedAt"
QT_MOC_LITERAL(54, 787, 14), // "signLastReason"
QT_MOC_LITERAL(55, 802, 14), // "signLastStatus"
QT_MOC_LITERAL(56, 817, 18), // "signLastAgeSeconds"
QT_MOC_LITERAL(57, 836, 9), // "handBoxes"
QT_MOC_LITERAL(58, 846, 13), // "handLandmarks"
QT_MOC_LITERAL(59, 860, 9), // "bodyBoxes"
QT_MOC_LITERAL(60, 870, 13), // "bodyLandmarks"
QT_MOC_LITERAL(61, 884, 12), // "printEnabled"
QT_MOC_LITERAL(62, 897, 15), // "printStatusText"
QT_MOC_LITERAL(63, 913, 9), // "staffText"
QT_MOC_LITERAL(64, 923, 14), // "signConfidence"
QT_MOC_LITERAL(65, 938, 14), // "signIntentCode"
QT_MOC_LITERAL(66, 953, 13), // "patientPrompt"
QT_MOC_LITERAL(67, 967, 10), // "videoAsset"
QT_MOC_LITERAL(68, 978, 8), // "videoUrl"
QT_MOC_LITERAL(69, 987, 13), // "playbackNonce"
QT_MOC_LITERAL(70, 1001, 14), // "videoAvailable"
QT_MOC_LITERAL(71, 1016, 18), // "videoPlaybackState"
QT_MOC_LITERAL(72, 1035, 15), // "videoPlaybackId"
QT_MOC_LITERAL(73, 1051, 18), // "videoPlaybackError"
QT_MOC_LITERAL(74, 1070, 26), // "departmentSelectionVisible"
QT_MOC_LITERAL(75, 1097, 17), // "departmentOptions"
QT_MOC_LITERAL(76, 1115, 18), // "selectedDepartment"
QT_MOC_LITERAL(77, 1134, 8), // "eventLog"
QT_MOC_LITERAL(78, 1143, 9) // "lastError"

    },
    "Backend\0signTokensChanged\0\0"
    "departmentOptionsChanged\0snapshotChanged\0"
    "firstSnapshotApplied\0cameraStateChanged\0"
    "recognitionChanged\0lastGestureChanged\0"
    "lastGestureAgeChanged\0overlayChanged\0"
    "videoStateChanged\0simulateNextSign\0"
    "simulateNextVoice\0selectDepartment\0"
    "department\0replayVideo\0clearConversation\0"
    "retrySign\0undoSign\0confirmSign\0"
    "retryVoice\0confirmVoice\0openDepartments\0"
    "cancelDepartments\0videoStarted\0requestId\0"
    "videoFinished\0videoFailed\0error\0"
    "systemState\0statusMessage\0conversationTurn\0"
    "roundNumber\0signTokens\0signDraftText\0"
    "signMatchStatus\0signMatchHint\0signHint\0"
    "signCanConfirm\0signCanUndo\0voiceDraftText\0"
    "voiceDraftConfidence\0voiceCanConfirm\0"
    "voiceOnline\0cameraStatus\0cameraUrl\0"
    "signOnline\0signStatus\0signCandidateText\0"
    "signCandidateConfidence\0signLastWord\0"
    "signLastConfidence\0signLastCompletedAt\0"
    "signLastReason\0signLastStatus\0"
    "signLastAgeSeconds\0handBoxes\0handLandmarks\0"
    "bodyBoxes\0bodyLandmarks\0printEnabled\0"
    "printStatusText\0staffText\0signConfidence\0"
    "signIntentCode\0patientPrompt\0videoAsset\0"
    "videoUrl\0playbackNonce\0videoAvailable\0"
    "videoPlaybackState\0videoPlaybackId\0"
    "videoPlaybackError\0departmentSelectionVisible\0"
    "departmentOptions\0selectedDepartment\0"
    "eventLog\0lastError"
};
#undef QT_MOC_LITERAL

static const uint qt_meta_data_Backend[] = {

 // content:
       8,       // revision
       0,       // classname
       0,    0, // classinfo
      25,   14, // methods
      49,  174, // properties
       0,    0, // enums/sets
       0,    0, // constructors
       0,       // flags
      10,       // signalCount

 // signals: name, argc, parameters, tag, flags
       1,    0,  139,    2, 0x06 /* Public */,
       3,    0,  140,    2, 0x06 /* Public */,
       4,    0,  141,    2, 0x06 /* Public */,
       5,    0,  142,    2, 0x06 /* Public */,
       6,    0,  143,    2, 0x06 /* Public */,
       7,    0,  144,    2, 0x06 /* Public */,
       8,    0,  145,    2, 0x06 /* Public */,
       9,    0,  146,    2, 0x06 /* Public */,
      10,    0,  147,    2, 0x06 /* Public */,
      11,    0,  148,    2, 0x06 /* Public */,

 // methods: name, argc, parameters, tag, flags
      12,    0,  149,    2, 0x02 /* Public */,
      13,    0,  150,    2, 0x02 /* Public */,
      14,    1,  151,    2, 0x02 /* Public */,
      16,    0,  154,    2, 0x02 /* Public */,
      17,    0,  155,    2, 0x02 /* Public */,
      18,    0,  156,    2, 0x02 /* Public */,
      19,    0,  157,    2, 0x02 /* Public */,
      20,    0,  158,    2, 0x02 /* Public */,
      21,    0,  159,    2, 0x02 /* Public */,
      22,    0,  160,    2, 0x02 /* Public */,
      23,    0,  161,    2, 0x02 /* Public */,
      24,    0,  162,    2, 0x02 /* Public */,
      25,    1,  163,    2, 0x02 /* Public */,
      27,    1,  166,    2, 0x02 /* Public */,
      28,    2,  169,    2, 0x02 /* Public */,

 // signals: parameters
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,

 // methods: parameters
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void, QMetaType::QString,   15,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void, QMetaType::QString,   26,
    QMetaType::Void, QMetaType::QString,   26,
    QMetaType::Void, QMetaType::QString, QMetaType::QString,   26,   29,

 // properties: name, type, flags
      30, QMetaType::QString, 0x00495001,
      31, QMetaType::QString, 0x00495001,
      32, QMetaType::QString, 0x00495001,
      33, QMetaType::Int, 0x00495001,
      34, QMetaType::QVariantList, 0x00495001,
      35, QMetaType::QString, 0x00495001,
      36, QMetaType::QString, 0x00495001,
      37, QMetaType::QString, 0x00495001,
      38, QMetaType::QString, 0x00495001,
      39, QMetaType::Bool, 0x00495001,
      40, QMetaType::Bool, 0x00495001,
      41, QMetaType::QString, 0x00495001,
      42, QMetaType::Double, 0x00495001,
      43, QMetaType::Bool, 0x00495001,
      44, QMetaType::Bool, 0x00495001,
      45, QMetaType::QString, 0x00495001,
      46, QMetaType::QString, 0x00495001,
      47, QMetaType::Bool, 0x00495001,
      48, QMetaType::QString, 0x00495001,
      49, QMetaType::QString, 0x00495001,
      50, QMetaType::Double, 0x00495001,
      51, QMetaType::QString, 0x00495001,
      52, QMetaType::Double, 0x00495001,
      53, QMetaType::QString, 0x00495001,
      54, QMetaType::QString, 0x00495001,
      55, QMetaType::QString, 0x00495001,
      56, QMetaType::Int, 0x00495001,
      57, QMetaType::QVariantList, 0x00495001,
      58, QMetaType::QVariantList, 0x00495001,
      59, QMetaType::QVariantList, 0x00495001,
      60, QMetaType::QVariantList, 0x00495001,
      61, QMetaType::Bool, 0x00495001,
      62, QMetaType::QString, 0x00495001,
      63, QMetaType::QString, 0x00495001,
      64, QMetaType::Double, 0x00495001,
      65, QMetaType::QString, 0x00495001,
      66, QMetaType::QString, 0x00495001,
      67, QMetaType::QString, 0x00495001,
      68, QMetaType::QString, 0x00495001,
      69, QMetaType::Int, 0x00495001,
      70, QMetaType::Bool, 0x00495001,
      71, QMetaType::QString, 0x00495001,
      72, QMetaType::QString, 0x00495001,
      73, QMetaType::QString, 0x00495001,
      74, QMetaType::Bool, 0x00495001,
      75, QMetaType::QVariantList, 0x00495001,
      76, QMetaType::QString, 0x00495001,
      77, QMetaType::QVariantList, 0x00495001,
      78, QMetaType::QString, 0x00495001,

 // properties: notify_signal_id
       2,
       2,
       2,
       2,
       0,
       2,
       2,
       2,
       2,
       2,
       2,
       2,
       2,
       2,
       2,
       4,
       4,
       5,
       5,
       5,
       5,
       6,
       6,
       6,
       6,
       6,
       7,
       8,
       8,
       8,
       8,
       2,
       2,
       2,
       2,
       2,
       2,
       9,
       9,
       9,
       9,
       9,
       9,
       9,
       2,
       1,
       2,
       2,
       2,

       0        // eod
};

void Backend::qt_static_metacall(QObject *_o, QMetaObject::Call _c, int _id, void **_a)
{
    if (_c == QMetaObject::InvokeMetaMethod) {
        auto *_t = static_cast<Backend *>(_o);
        Q_UNUSED(_t)
        switch (_id) {
        case 0: _t->signTokensChanged(); break;
        case 1: _t->departmentOptionsChanged(); break;
        case 2: _t->snapshotChanged(); break;
        case 3: _t->firstSnapshotApplied(); break;
        case 4: _t->cameraStateChanged(); break;
        case 5: _t->recognitionChanged(); break;
        case 6: _t->lastGestureChanged(); break;
        case 7: _t->lastGestureAgeChanged(); break;
        case 8: _t->overlayChanged(); break;
        case 9: _t->videoStateChanged(); break;
        case 10: _t->simulateNextSign(); break;
        case 11: _t->simulateNextVoice(); break;
        case 12: _t->selectDepartment((*reinterpret_cast< const QString(*)>(_a[1]))); break;
        case 13: _t->replayVideo(); break;
        case 14: _t->clearConversation(); break;
        case 15: _t->retrySign(); break;
        case 16: _t->undoSign(); break;
        case 17: _t->confirmSign(); break;
        case 18: _t->retryVoice(); break;
        case 19: _t->confirmVoice(); break;
        case 20: _t->openDepartments(); break;
        case 21: _t->cancelDepartments(); break;
        case 22: _t->videoStarted((*reinterpret_cast< const QString(*)>(_a[1]))); break;
        case 23: _t->videoFinished((*reinterpret_cast< const QString(*)>(_a[1]))); break;
        case 24: _t->videoFailed((*reinterpret_cast< const QString(*)>(_a[1])),(*reinterpret_cast< const QString(*)>(_a[2]))); break;
        default: ;
        }
    } else if (_c == QMetaObject::IndexOfMethod) {
        int *result = reinterpret_cast<int *>(_a[0]);
        {
            using _t = void (Backend::*)();
            if (*reinterpret_cast<_t *>(_a[1]) == static_cast<_t>(&Backend::signTokensChanged)) {
                *result = 0;
                return;
            }
        }
        {
            using _t = void (Backend::*)();
            if (*reinterpret_cast<_t *>(_a[1]) == static_cast<_t>(&Backend::departmentOptionsChanged)) {
                *result = 1;
                return;
            }
        }
        {
            using _t = void (Backend::*)();
            if (*reinterpret_cast<_t *>(_a[1]) == static_cast<_t>(&Backend::snapshotChanged)) {
                *result = 2;
                return;
            }
        }
        {
            using _t = void (Backend::*)();
            if (*reinterpret_cast<_t *>(_a[1]) == static_cast<_t>(&Backend::firstSnapshotApplied)) {
                *result = 3;
                return;
            }
        }
        {
            using _t = void (Backend::*)();
            if (*reinterpret_cast<_t *>(_a[1]) == static_cast<_t>(&Backend::cameraStateChanged)) {
                *result = 4;
                return;
            }
        }
        {
            using _t = void (Backend::*)();
            if (*reinterpret_cast<_t *>(_a[1]) == static_cast<_t>(&Backend::recognitionChanged)) {
                *result = 5;
                return;
            }
        }
        {
            using _t = void (Backend::*)();
            if (*reinterpret_cast<_t *>(_a[1]) == static_cast<_t>(&Backend::lastGestureChanged)) {
                *result = 6;
                return;
            }
        }
        {
            using _t = void (Backend::*)();
            if (*reinterpret_cast<_t *>(_a[1]) == static_cast<_t>(&Backend::lastGestureAgeChanged)) {
                *result = 7;
                return;
            }
        }
        {
            using _t = void (Backend::*)();
            if (*reinterpret_cast<_t *>(_a[1]) == static_cast<_t>(&Backend::overlayChanged)) {
                *result = 8;
                return;
            }
        }
        {
            using _t = void (Backend::*)();
            if (*reinterpret_cast<_t *>(_a[1]) == static_cast<_t>(&Backend::videoStateChanged)) {
                *result = 9;
                return;
            }
        }
    }
#ifndef QT_NO_PROPERTIES
    else if (_c == QMetaObject::ReadProperty) {
        auto *_t = static_cast<Backend *>(_o);
        Q_UNUSED(_t)
        void *_v = _a[0];
        switch (_id) {
        case 0: *reinterpret_cast< QString*>(_v) = _t->systemState(); break;
        case 1: *reinterpret_cast< QString*>(_v) = _t->statusMessage(); break;
        case 2: *reinterpret_cast< QString*>(_v) = _t->conversationTurn(); break;
        case 3: *reinterpret_cast< int*>(_v) = _t->roundNumber(); break;
        case 4: *reinterpret_cast< QVariantList*>(_v) = _t->signTokens(); break;
        case 5: *reinterpret_cast< QString*>(_v) = _t->signDraftText(); break;
        case 6: *reinterpret_cast< QString*>(_v) = _t->signMatchStatus(); break;
        case 7: *reinterpret_cast< QString*>(_v) = _t->signMatchHint(); break;
        case 8: *reinterpret_cast< QString*>(_v) = _t->signHint(); break;
        case 9: *reinterpret_cast< bool*>(_v) = _t->signCanConfirm(); break;
        case 10: *reinterpret_cast< bool*>(_v) = _t->signCanUndo(); break;
        case 11: *reinterpret_cast< QString*>(_v) = _t->voiceDraftText(); break;
        case 12: *reinterpret_cast< double*>(_v) = _t->voiceDraftConfidence(); break;
        case 13: *reinterpret_cast< bool*>(_v) = _t->voiceCanConfirm(); break;
        case 14: *reinterpret_cast< bool*>(_v) = _t->voiceOnline(); break;
        case 15: *reinterpret_cast< QString*>(_v) = _t->cameraStatus(); break;
        case 16: *reinterpret_cast< QString*>(_v) = _t->cameraUrl(); break;
        case 17: *reinterpret_cast< bool*>(_v) = _t->signOnline(); break;
        case 18: *reinterpret_cast< QString*>(_v) = _t->signStatus(); break;
        case 19: *reinterpret_cast< QString*>(_v) = _t->signCandidateText(); break;
        case 20: *reinterpret_cast< double*>(_v) = _t->signCandidateConfidence(); break;
        case 21: *reinterpret_cast< QString*>(_v) = _t->signLastWord(); break;
        case 22: *reinterpret_cast< double*>(_v) = _t->signLastConfidence(); break;
        case 23: *reinterpret_cast< QString*>(_v) = _t->signLastCompletedAt(); break;
        case 24: *reinterpret_cast< QString*>(_v) = _t->signLastReason(); break;
        case 25: *reinterpret_cast< QString*>(_v) = _t->signLastStatus(); break;
        case 26: *reinterpret_cast< int*>(_v) = _t->signLastAgeSeconds(); break;
        case 27: *reinterpret_cast< QVariantList*>(_v) = _t->handBoxes(); break;
        case 28: *reinterpret_cast< QVariantList*>(_v) = _t->handLandmarks(); break;
        case 29: *reinterpret_cast< QVariantList*>(_v) = _t->bodyBoxes(); break;
        case 30: *reinterpret_cast< QVariantList*>(_v) = _t->bodyLandmarks(); break;
        case 31: *reinterpret_cast< bool*>(_v) = _t->printEnabled(); break;
        case 32: *reinterpret_cast< QString*>(_v) = _t->printStatusText(); break;
        case 33: *reinterpret_cast< QString*>(_v) = _t->staffText(); break;
        case 34: *reinterpret_cast< double*>(_v) = _t->signConfidence(); break;
        case 35: *reinterpret_cast< QString*>(_v) = _t->signIntentCode(); break;
        case 36: *reinterpret_cast< QString*>(_v) = _t->patientPrompt(); break;
        case 37: *reinterpret_cast< QString*>(_v) = _t->videoAsset(); break;
        case 38: *reinterpret_cast< QString*>(_v) = _t->videoUrl(); break;
        case 39: *reinterpret_cast< int*>(_v) = _t->playbackNonce(); break;
        case 40: *reinterpret_cast< bool*>(_v) = _t->videoAvailable(); break;
        case 41: *reinterpret_cast< QString*>(_v) = _t->videoPlaybackState(); break;
        case 42: *reinterpret_cast< QString*>(_v) = _t->videoPlaybackId(); break;
        case 43: *reinterpret_cast< QString*>(_v) = _t->videoPlaybackError(); break;
        case 44: *reinterpret_cast< bool*>(_v) = _t->departmentSelectionVisible(); break;
        case 45: *reinterpret_cast< QVariantList*>(_v) = _t->departmentOptions(); break;
        case 46: *reinterpret_cast< QString*>(_v) = _t->selectedDepartment(); break;
        case 47: *reinterpret_cast< QVariantList*>(_v) = _t->eventLog(); break;
        case 48: *reinterpret_cast< QString*>(_v) = _t->lastError(); break;
        default: break;
        }
    } else if (_c == QMetaObject::WriteProperty) {
    } else if (_c == QMetaObject::ResetProperty) {
    }
#endif // QT_NO_PROPERTIES
}

QT_INIT_METAOBJECT const QMetaObject Backend::staticMetaObject = { {
    &QObject::staticMetaObject,
    qt_meta_stringdata_Backend.data,
    qt_meta_data_Backend,
    qt_static_metacall,
    nullptr,
    nullptr
} };


const QMetaObject *Backend::metaObject() const
{
    return QObject::d_ptr->metaObject ? QObject::d_ptr->dynamicMetaObject() : &staticMetaObject;
}

void *Backend::qt_metacast(const char *_clname)
{
    if (!_clname) return nullptr;
    if (!strcmp(_clname, qt_meta_stringdata_Backend.stringdata0))
        return static_cast<void*>(this);
    return QObject::qt_metacast(_clname);
}

int Backend::qt_metacall(QMetaObject::Call _c, int _id, void **_a)
{
    _id = QObject::qt_metacall(_c, _id, _a);
    if (_id < 0)
        return _id;
    if (_c == QMetaObject::InvokeMetaMethod) {
        if (_id < 25)
            qt_static_metacall(this, _c, _id, _a);
        _id -= 25;
    } else if (_c == QMetaObject::RegisterMethodArgumentMetaType) {
        if (_id < 25)
            *reinterpret_cast<int*>(_a[0]) = -1;
        _id -= 25;
    }
#ifndef QT_NO_PROPERTIES
    else if (_c == QMetaObject::ReadProperty || _c == QMetaObject::WriteProperty
            || _c == QMetaObject::ResetProperty || _c == QMetaObject::RegisterPropertyMetaType) {
        qt_static_metacall(this, _c, _id, _a);
        _id -= 49;
    } else if (_c == QMetaObject::QueryPropertyDesignable) {
        _id -= 49;
    } else if (_c == QMetaObject::QueryPropertyScriptable) {
        _id -= 49;
    } else if (_c == QMetaObject::QueryPropertyStored) {
        _id -= 49;
    } else if (_c == QMetaObject::QueryPropertyEditable) {
        _id -= 49;
    } else if (_c == QMetaObject::QueryPropertyUser) {
        _id -= 49;
    }
#endif // QT_NO_PROPERTIES
    return _id;
}

// SIGNAL 0
void Backend::signTokensChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 0, nullptr);
}

// SIGNAL 1
void Backend::departmentOptionsChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 1, nullptr);
}

// SIGNAL 2
void Backend::snapshotChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 2, nullptr);
}

// SIGNAL 3
void Backend::firstSnapshotApplied()
{
    QMetaObject::activate(this, &staticMetaObject, 3, nullptr);
}

// SIGNAL 4
void Backend::cameraStateChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 4, nullptr);
}

// SIGNAL 5
void Backend::recognitionChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 5, nullptr);
}

// SIGNAL 6
void Backend::lastGestureChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 6, nullptr);
}

// SIGNAL 7
void Backend::lastGestureAgeChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 7, nullptr);
}

// SIGNAL 8
void Backend::overlayChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 8, nullptr);
}

// SIGNAL 9
void Backend::videoStateChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 9, nullptr);
}
QT_WARNING_POP
QT_END_MOC_NAMESPACE
