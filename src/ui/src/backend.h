#pragma once

#include <QObject>
#include <QProcess>
#include <QVariantList>
#include <QVariantMap>
#include <QTcpSocket>
#include <QTimer>

class Backend final : public QObject
{
    Q_OBJECT
    Q_PROPERTY(QString systemState READ systemState NOTIFY snapshotChanged)
    Q_PROPERTY(QString statusMessage READ statusMessage NOTIFY snapshotChanged)
    Q_PROPERTY(QString conversationTurn READ conversationTurn NOTIFY snapshotChanged)
    Q_PROPERTY(int roundNumber READ roundNumber NOTIFY snapshotChanged)
    Q_PROPERTY(QVariantList signTokens READ signTokens NOTIFY signTokensChanged)
    Q_PROPERTY(QString signDraftText READ signDraftText NOTIFY snapshotChanged)
    Q_PROPERTY(QString signMatchStatus READ signMatchStatus NOTIFY snapshotChanged)
    Q_PROPERTY(QString signMatchHint READ signMatchHint NOTIFY snapshotChanged)
    Q_PROPERTY(QString signHint READ signHint NOTIFY snapshotChanged)
    Q_PROPERTY(bool signCanConfirm READ signCanConfirm NOTIFY snapshotChanged)
    Q_PROPERTY(bool signCanUndo READ signCanUndo NOTIFY snapshotChanged)
    Q_PROPERTY(QString voiceDraftText READ voiceDraftText NOTIFY snapshotChanged)
    Q_PROPERTY(double voiceDraftConfidence READ voiceDraftConfidence NOTIFY snapshotChanged)
    Q_PROPERTY(bool voiceCanConfirm READ voiceCanConfirm NOTIFY snapshotChanged)
    Q_PROPERTY(bool voiceOnline READ voiceOnline NOTIFY snapshotChanged)
    Q_PROPERTY(QString cameraStatus READ cameraStatus NOTIFY cameraStateChanged)
    Q_PROPERTY(QString cameraUrl READ cameraUrl NOTIFY cameraStateChanged)
    Q_PROPERTY(bool signOnline READ signOnline NOTIFY recognitionChanged)
    Q_PROPERTY(QString signStatus READ signStatus NOTIFY recognitionChanged)
    Q_PROPERTY(QString signCandidateText READ signCandidateText NOTIFY recognitionChanged)
    Q_PROPERTY(double signCandidateConfidence READ signCandidateConfidence NOTIFY recognitionChanged)
    Q_PROPERTY(QString signLastWord READ signLastWord NOTIFY lastGestureChanged)
    Q_PROPERTY(double signLastConfidence READ signLastConfidence NOTIFY lastGestureChanged)
    Q_PROPERTY(QString signLastCompletedAt READ signLastCompletedAt NOTIFY lastGestureChanged)
    Q_PROPERTY(QString signLastReason READ signLastReason NOTIFY lastGestureChanged)
    Q_PROPERTY(QString signLastStatus READ signLastStatus NOTIFY lastGestureChanged)
    Q_PROPERTY(int signLastAgeSeconds READ signLastAgeSeconds NOTIFY lastGestureAgeChanged)
    Q_PROPERTY(QVariantList handBoxes READ handBoxes NOTIFY overlayChanged)
    Q_PROPERTY(QVariantList handLandmarks READ handLandmarks NOTIFY overlayChanged)
    Q_PROPERTY(QVariantList bodyBoxes READ bodyBoxes NOTIFY overlayChanged)
    Q_PROPERTY(QVariantList bodyLandmarks READ bodyLandmarks NOTIFY overlayChanged)
    Q_PROPERTY(bool printEnabled READ printEnabled NOTIFY snapshotChanged)
    Q_PROPERTY(QString printStatusText READ printStatusText NOTIFY snapshotChanged)
    Q_PROPERTY(QString staffText READ staffText NOTIFY snapshotChanged)
    Q_PROPERTY(double signConfidence READ signConfidence NOTIFY snapshotChanged)
    Q_PROPERTY(QString signIntentCode READ signIntentCode NOTIFY snapshotChanged)
    Q_PROPERTY(QString patientPrompt READ patientPrompt NOTIFY snapshotChanged)
    Q_PROPERTY(QString videoAsset READ videoAsset NOTIFY videoStateChanged)
    Q_PROPERTY(QString videoUrl READ videoUrl NOTIFY videoStateChanged)
    Q_PROPERTY(int playbackNonce READ playbackNonce NOTIFY videoStateChanged)
    Q_PROPERTY(bool videoAvailable READ videoAvailable NOTIFY videoStateChanged)
    Q_PROPERTY(QString videoPlaybackState READ videoPlaybackState NOTIFY videoStateChanged)
    Q_PROPERTY(QString videoPlaybackId READ videoPlaybackId NOTIFY videoStateChanged)
    Q_PROPERTY(QString videoPlaybackError READ videoPlaybackError NOTIFY videoStateChanged)
    Q_PROPERTY(bool departmentSelectionVisible READ departmentSelectionVisible NOTIFY snapshotChanged)
    Q_PROPERTY(QVariantList departmentOptions READ departmentOptions NOTIFY departmentOptionsChanged)
    Q_PROPERTY(QString selectedDepartment READ selectedDepartment NOTIFY snapshotChanged)
    Q_PROPERTY(QVariantList eventLog READ eventLog NOTIFY snapshotChanged)
    Q_PROPERTY(QString lastError READ lastError NOTIFY snapshotChanged)

public:
    explicit Backend(QObject *parent = nullptr);
    bool hasAppliedSnapshot() const { return m_firstSnapshotApplied; }
    ~Backend() override;

    QString systemState() const;
    QString statusMessage() const;
    QString conversationTurn() const;
    int roundNumber() const;
    QVariantList signTokens() const;
    QString signDraftText() const;
    QString signMatchStatus() const;
    QString signMatchHint() const;
    QString signHint() const;
    bool signCanConfirm() const;
    bool signCanUndo() const;
    QString voiceDraftText() const;
    double voiceDraftConfidence() const;
    bool voiceCanConfirm() const;
    bool voiceOnline() const;
    QString cameraStatus() const;
    QString cameraUrl() const;
    bool signOnline() const;
    QString signStatus() const;
    QString signCandidateText() const;
    double signCandidateConfidence() const;
    QString signLastWord() const;
    double signLastConfidence() const;
    QString signLastCompletedAt() const;
    QString signLastReason() const;
    QString signLastStatus() const;
    int signLastAgeSeconds() const;
    QVariantList handBoxes() const;
    QVariantList handLandmarks() const;
    QVariantList bodyBoxes() const;
    QVariantList bodyLandmarks() const;
    bool printEnabled() const;
    QString printStatusText() const;
    QString staffText() const;
    double signConfidence() const;
    QString signIntentCode() const;
    QString patientPrompt() const;
    QString videoAsset() const;
    QString videoUrl() const;
    int playbackNonce() const;
    bool videoAvailable() const;
    QString videoPlaybackState() const;
    QString videoPlaybackId() const;
    QString videoPlaybackError() const;
    bool departmentSelectionVisible() const;
    QVariantList departmentOptions() const;
    QString selectedDepartment() const;
    QVariantList eventLog() const;
    QString lastError() const;

    Q_INVOKABLE void simulateNextSign();
    Q_INVOKABLE void simulateNextVoice();
    Q_INVOKABLE void selectDepartment(const QString &department);
    Q_INVOKABLE void replayVideo();
    Q_INVOKABLE void clearConversation();
    Q_INVOKABLE void retrySign();
    Q_INVOKABLE void undoSign();
    Q_INVOKABLE void confirmSign();
    Q_INVOKABLE void retryVoice();
    Q_INVOKABLE void confirmVoice();
    Q_INVOKABLE void openDepartments();
    Q_INVOKABLE void cancelDepartments();
    Q_INVOKABLE void videoStarted(const QString &requestId);
    Q_INVOKABLE void videoFinished(const QString &requestId);
    Q_INVOKABLE void videoFailed(const QString &requestId, const QString &error);

signals:
    void signTokensChanged();
    void departmentOptionsChanged();
    void snapshotChanged();
    void firstSnapshotApplied();
    void cameraStateChanged();
    void recognitionChanged();
    void lastGestureChanged();
    void lastGestureAgeChanged();
    void overlayChanged();
    void videoStateChanged();

private:
    QVariant value(const QString &key, const QVariant &fallback = {}) const;
    void sendCommand(const QString &action, const QVariantMap &arguments = {});
    void readStandardOutput();
    void readStandardError();
    void setBridgeError(const QString &message);

    QProcess m_python;
    QTcpSocket m_bridge;
    QTimer m_reconnect;
    bool m_sharedService = false;
    bool m_firstSnapshotApplied = false;
    quint16 m_bridgePort = 0;
    QByteArray m_stdoutBuffer;
    QVariantMap m_snapshot;
};
