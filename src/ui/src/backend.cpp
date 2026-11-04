#include "backend.h"

#include <QDir>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcessEnvironment>
#include <QDebug>
#include <cstdio>
#include <initializer_list>

namespace {
bool fieldsChanged(const QVariantMap &before, const QVariantMap &after,
                   std::initializer_list<const char *> keys)
{
    for (const char *key : keys) {
        const QString field = QString::fromLatin1(key);
        if (before.value(field) != after.value(field))
            return true;
    }
    return false;
}
}

Backend::Backend(QObject *parent)
    : QObject(parent)
{
    std::fprintf(stderr, "MEDCOMM_STARTUP:backend-enter\n");
    std::fflush(stderr);
    m_snapshot = {
        {"system_state", "STARTING"},
        {"status_message", "正在启动界面服务……"},
        {"conversation_turn", "patient"},
        {"round_number", 1},
        {"sign_tokens", QVariantList{}},
        {"sign_draft_text", ""},
        {"sign_match_status", "empty"},
        {"sign_match_hint", "请按顺序完成本次手语表达。"},
        {"sign_hint", "请按顺序完成手语表达"},
        {"sign_can_confirm", false},
        {"sign_can_undo", false},
        {"voice_draft_text", ""},
        {"voice_draft_confidence", -1.0},
        {"voice_can_confirm", false},
        {"voice_online", false},
        {"camera_status", "WAITING"},
        {"staff_text", "等待患者进行手语表达"},
        {"sign_confidence", -1.0},
        {"sign_intent_code", ""},
        {"patient_prompt", "等待工作人员说话"},
        {"video_asset", ""},
        {"video_url", ""},
        {"playback_nonce", 0},
        {"video_available", false},
        {"video_playback_state", "idle"},
        {"video_playback_id", ""},
        {"video_playback_error", ""},
        {"department_selection_visible", false},
        {"department_options", QVariantList{}},
        {"selected_department", ""},
        {"event_log", QVariantList{}},
        {"last_error", ""}
    };

    connect(&m_python, &QProcess::readyReadStandardOutput,
            this, &Backend::readStandardOutput);
    connect(&m_python, &QProcess::readyReadStandardError,
            this, &Backend::readStandardError);
    connect(&m_python, &QProcess::errorOccurred, this,
            [this](QProcess::ProcessError) {
                setBridgeError(QStringLiteral("无法启动界面服务：%1").arg(m_python.errorString()));
            });

    auto environment = QProcessEnvironment::systemEnvironment();
    m_bridgePort = environment.value(QStringLiteral("MEDCOMM_UI_BRIDGE_PORT")).toUShort();
    if (m_bridgePort) {
        m_sharedService = true;
        connect(&m_bridge, &QTcpSocket::readyRead, this, &Backend::readStandardOutput);
        connect(&m_bridge, &QTcpSocket::connected, this, [this]() {
            m_bridge.setSocketOption(QAbstractSocket::LowDelayOption, 1);
            m_stdoutBuffer.clear();
            sendCommand(QStringLiteral("snapshot"));
        });
        connect(&m_bridge, &QTcpSocket::disconnected, this, [this]() {
            setBridgeError(QStringLiteral("正在重新连接双屏共享服务"));
        });
        m_reconnect.setInterval(1000);
        connect(&m_reconnect, &QTimer::timeout, this, [this]() {
            if (m_bridge.state() == QAbstractSocket::UnconnectedState)
                m_bridge.connectToHost(QStringLiteral("127.0.0.1"), m_bridgePort);
        });
        m_reconnect.start();
        m_bridge.connectToHost(QStringLiteral("127.0.0.1"), m_bridgePort);
        return;
    }
    QString python = environment.value(QStringLiteral("MEDCOMM_UI_PYTHON"));
    if (python.isEmpty())
        python = QStringLiteral("python3");

    QString projectRoot = environment.value(QStringLiteral("MEDCOMM_PROJECT_ROOT"));
    if (projectRoot.isEmpty())
        projectRoot = QString::fromUtf8(MEDCOMM_PROJECT_ROOT);
    const QString script = QDir(projectRoot)
                               .filePath(QStringLiteral("qt_dual_display/backend_server.py"));
    environment.insert(QStringLiteral("PYTHONUNBUFFERED"), QStringLiteral("1"));
    m_python.setProcessEnvironment(environment);
    m_python.setProgram(python);
    m_python.setArguments({script});
    m_python.setProcessChannelMode(QProcess::SeparateChannels);
    std::fprintf(stderr, "MEDCOMM_STARTUP:backend-before-python-start\n");
    std::fflush(stderr);
    m_python.start();
    std::fprintf(stderr, "MEDCOMM_STARTUP:backend-exit\n");
    std::fflush(stderr);
}

Backend::~Backend()
{
    if (m_python.state() == QProcess::Running) {
        sendCommand(QStringLiteral("shutdown"));
        m_python.closeWriteChannel();
        if (!m_python.waitForFinished(800)) {
            m_python.terminate();
            m_python.waitForFinished(500);
        }
    }
}

QVariant Backend::value(const QString &key, const QVariant &fallback) const
{
    return m_snapshot.value(key, fallback);
}

QString Backend::systemState() const { return value("system_state", "UNKNOWN").toString(); }
QString Backend::statusMessage() const { return value("status_message").toString(); }
QString Backend::conversationTurn() const { return value("conversation_turn", "patient").toString(); }
int Backend::roundNumber() const { return value("round_number", 1).toInt(); }
QVariantList Backend::signTokens() const { return value("sign_tokens").toList(); }
QString Backend::signDraftText() const { return value("sign_draft_text").toString(); }
QString Backend::signMatchStatus() const { return value("sign_match_status", "empty").toString(); }
QString Backend::signMatchHint() const { return value("sign_match_hint").toString(); }
QString Backend::signHint() const { return value("sign_hint").toString(); }
bool Backend::signCanConfirm() const { return value("sign_can_confirm", false).toBool(); }
bool Backend::signCanUndo() const { return value("sign_can_undo", false).toBool(); }
QString Backend::voiceDraftText() const { return value("voice_draft_text").toString(); }
double Backend::voiceDraftConfidence() const { return value("voice_draft_confidence", -1.0).toDouble(); }
bool Backend::voiceCanConfirm() const { return value("voice_can_confirm", false).toBool(); }
bool Backend::voiceOnline() const { return value("voice_online", false).toBool(); }
QString Backend::cameraStatus() const { return value("camera_status", "UNKNOWN").toString(); }
QString Backend::cameraUrl() const { return value("camera_url").toString(); }
bool Backend::signOnline() const { return value("sign_online", false).toBool(); }
QString Backend::signStatus() const { return value("sign_status", "等待 A 识别服务").toString(); }
QString Backend::signCandidateText() const { return value("sign_candidate_text").toString(); }
double Backend::signCandidateConfidence() const { return value("sign_candidate_confidence", -1.0).toDouble(); }
QString Backend::signLastWord() const { return value("sign_last_word").toString(); }
double Backend::signLastConfidence() const { return value("sign_last_confidence", -1.0).toDouble(); }
QString Backend::signLastCompletedAt() const { return value("sign_last_completed_at").toString(); }
QString Backend::signLastReason() const { return value("sign_last_reason").toString(); }
QString Backend::signLastStatus() const { return value("sign_last_status", "empty").toString(); }
int Backend::signLastAgeSeconds() const { return value("sign_last_age_seconds", -1).toInt(); }
QVariantList Backend::handBoxes() const { return value("hand_boxes").toList(); }
QVariantList Backend::handLandmarks() const { return value("hand_landmarks").toList(); }
QVariantList Backend::bodyBoxes() const { return value("body_boxes").toList(); }
QVariantList Backend::bodyLandmarks() const { return value("body_landmarks").toList(); }
bool Backend::printEnabled() const { return value("print_enabled", false).toBool(); }
QString Backend::printStatusText() const { return value("print_status_text", "打印已关闭").toString(); }
QString Backend::staffText() const { return value("staff_text").toString(); }
double Backend::signConfidence() const { return value("sign_confidence", -1.0).toDouble(); }
QString Backend::signIntentCode() const { return value("sign_intent_code").toString(); }
QString Backend::patientPrompt() const { return value("patient_prompt").toString(); }
QString Backend::videoAsset() const { return value("video_asset").toString(); }
QString Backend::videoUrl() const { return value("video_url").toString(); }
int Backend::playbackNonce() const { return value("playback_nonce", 0).toInt(); }
bool Backend::videoAvailable() const { return value("video_available", false).toBool(); }
QString Backend::videoPlaybackState() const { return value("video_playback_state", "idle").toString(); }
QString Backend::videoPlaybackId() const { return value("video_playback_id").toString(); }
QString Backend::videoPlaybackError() const { return value("video_playback_error").toString(); }
bool Backend::departmentSelectionVisible() const { return value("department_selection_visible", false).toBool(); }
QVariantList Backend::departmentOptions() const { return value("department_options").toList(); }
QString Backend::selectedDepartment() const { return value("selected_department").toString(); }
QVariantList Backend::eventLog() const { return value("event_log").toList(); }
QString Backend::lastError() const { return value("last_error").toString(); }

void Backend::simulateNextSign() { sendCommand(QStringLiteral("simulate_sign")); }
void Backend::simulateNextVoice() { sendCommand(QStringLiteral("simulate_voice")); }
void Backend::selectDepartment(const QString &department)
{
    sendCommand(QStringLiteral("select_department"), {{"department", department}});
}
void Backend::replayVideo() { sendCommand(QStringLiteral("replay_video")); }
void Backend::clearConversation() { sendCommand(QStringLiteral("clear")); }
void Backend::retrySign() { sendCommand(QStringLiteral("retry_sign")); }
void Backend::undoSign() { sendCommand(QStringLiteral("undo_sign")); }
void Backend::confirmSign() { sendCommand(QStringLiteral("confirm_sign")); }
void Backend::retryVoice() { sendCommand(QStringLiteral("retry_voice")); }
void Backend::confirmVoice() { sendCommand(QStringLiteral("confirm_voice")); }
void Backend::openDepartments() { sendCommand(QStringLiteral("open_departments")); }
void Backend::cancelDepartments() { sendCommand(QStringLiteral("cancel_departments")); }
void Backend::videoStarted(const QString &requestId)
{
    sendCommand(QStringLiteral("video_started"), {{"request_id", requestId}});
}
void Backend::videoFinished(const QString &requestId)
{
    sendCommand(QStringLiteral("video_finished"), {{"request_id", requestId}});
}
void Backend::videoFailed(const QString &requestId, const QString &error)
{
    sendCommand(QStringLiteral("video_failed"), {{"request_id", requestId}, {"error", error}});
}

void Backend::sendCommand(const QString &action, const QVariantMap &arguments)
{
    if (m_sharedService ? m_bridge.state() != QAbstractSocket::ConnectedState
                        : m_python.state() != QProcess::Running) {
        setBridgeError(QStringLiteral("界面服务未运行，请检查Python路径。"));
        return;
    }
    QVariantMap command = arguments;
    command.insert(QStringLiteral("action"), action);
    QByteArray line = QJsonDocument(QJsonObject::fromVariantMap(command))
                          .toJson(QJsonDocument::Compact);
    line.append('\n');
    if (m_sharedService)
        m_bridge.write(line);
    else
        m_python.write(line);
}

void Backend::readStandardOutput()
{
    m_stdoutBuffer.append(m_sharedService ? m_bridge.readAll() : m_python.readAllStandardOutput());
    while (true) {
        const int newline = m_stdoutBuffer.indexOf('\n');
        if (newline < 0)
            break;
        const QByteArray line = m_stdoutBuffer.left(newline).trimmed();
        m_stdoutBuffer.remove(0, newline + 1);
        if (line.isEmpty())
            continue;
        QJsonParseError error;
        const auto document = QJsonDocument::fromJson(line, &error);
        if (error.error != QJsonParseError::NoError || !document.isObject()) {
            setBridgeError(QStringLiteral("界面服务返回了无效数据：%1").arg(error.errorString()));
            continue;
        }
        const QVariantMap next = document.object().toVariantMap();
        const bool tokensChanged = fieldsChanged(m_snapshot, next, {"sign_tokens"});
        const bool departmentsChanged = fieldsChanged(m_snapshot, next, {"department_options"});
        // Camera packets arrive much more often than business state changes.
        // Keep unchanged list models and text layouts out of their refresh path.
        const bool businessChanged = fieldsChanged(m_snapshot, next, {
            "system_state", "status_message", "conversation_turn", "round_number",
            "sign_tokens", "sign_draft_text", "sign_match_status", "sign_match_hint", "sign_hint",
            "sign_can_confirm", "sign_can_undo", "voice_draft_text", "voice_draft_confidence",
            "voice_can_confirm", "voice_online", "staff_text", "sign_confidence",
            "sign_intent_code", "patient_prompt",
            "department_selection_visible", "department_options",
            "selected_department", "event_log", "last_error", "print_enabled", "print_status_text"
        });
        const bool cameraChanged = fieldsChanged(m_snapshot, next, {
            "camera_status", "camera_url"
        });
        const bool recognitionStateChanged = fieldsChanged(m_snapshot, next, {
            "sign_online", "sign_status", "sign_candidate_text", "sign_candidate_confidence"
        });
        const bool geometryChanged = fieldsChanged(m_snapshot, next, {
            "hand_boxes", "hand_landmarks", "body_boxes", "body_landmarks"
        });
        const bool lastGestureUpdated = fieldsChanged(m_snapshot, next, {
            "sign_last_word", "sign_last_confidence", "sign_last_completed_at",
            "sign_last_reason", "sign_last_status"
        });
        const bool playbackChanged = fieldsChanged(m_snapshot, next, {
            "video_asset", "video_url", "playback_nonce", "video_available",
            "video_playback_state", "video_playback_id", "video_playback_error"
        });
        const bool lastGestureAgeUpdated = fieldsChanged(m_snapshot, next, {"sign_last_age_seconds"});
        m_snapshot = next;
        if (tokensChanged)
            emit signTokensChanged();
        if (departmentsChanged)
            emit departmentOptionsChanged();
        if (businessChanged)
            emit snapshotChanged();
        if (cameraChanged)
            emit cameraStateChanged();
        if (recognitionStateChanged)
            emit recognitionChanged();
        if (lastGestureUpdated)
            emit lastGestureChanged();
        if (lastGestureAgeUpdated)
            emit lastGestureAgeChanged();
        if (geometryChanged)
            emit overlayChanged();
        if (playbackChanged)
            emit videoStateChanged();
        if (!m_firstSnapshotApplied) {
            m_firstSnapshotApplied = true;
            emit firstSnapshotApplied();
        }
    }
}

void Backend::readStandardError()
{
    const QString details = QString::fromUtf8(m_python.readAllStandardError()).trimmed();
    if (!details.isEmpty())
        qWarning().noquote() << details;
}

void Backend::setBridgeError(const QString &message)
{
    m_snapshot.insert(QStringLiteral("sign_can_confirm"), false);
    m_snapshot.insert(QStringLiteral("sign_can_undo"), false);
    m_snapshot.insert(QStringLiteral("voice_can_confirm"), false);
    m_snapshot.insert(QStringLiteral("hand_boxes"), QVariantList{});
    m_snapshot.insert(QStringLiteral("hand_landmarks"), QVariantList{});
    m_snapshot.insert(QStringLiteral("body_boxes"), QVariantList{});
    m_snapshot.insert(QStringLiteral("body_landmarks"), QVariantList{});
    m_snapshot.insert(QStringLiteral("system_state"), QStringLiteral("ERROR"));
    m_snapshot.insert(QStringLiteral("status_message"), QStringLiteral("界面服务连接失败"));
    m_snapshot.insert(QStringLiteral("last_error"), message);
    m_snapshot.insert(QStringLiteral("video_available"), false);
    m_snapshot.insert(QStringLiteral("video_playback_state"), QStringLiteral("error"));
    m_snapshot.insert(QStringLiteral("video_playback_error"), message);
    emit snapshotChanged();
    emit cameraStateChanged();
    emit recognitionChanged();
    emit overlayChanged();
    emit videoStateChanged();
}
