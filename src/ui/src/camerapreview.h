#pragma once
#include "sameframesource.h"
#include "liveintegersource.h"
#include <QQuickPaintedItem>
#include <QImage>
#include <QTimer>
#include <QElapsedTimer>
#include <QVariant>
#include <QUrl>
#include <QStringList>

class CameraPreview : public QQuickPaintedItem {
    Q_OBJECT
    Q_PROPERTY(bool available READ available NOTIFY frameChanged)
    Q_PROPERTY(qreal paintedWidth READ paintedWidth NOTIFY frameChanged)
    Q_PROPERTY(qreal paintedHeight READ paintedHeight NOTIFY frameChanged)
    Q_PROPERTY(bool streaming READ streaming WRITE setStreaming NOTIFY streamingChanged)
    Q_PROPERTY(bool composited READ composited WRITE setComposited NOTIFY compositedChanged)
    Q_PROPERTY(bool videoPlaying READ videoPlaying NOTIFY videoPlayingChanged)
    Q_PROPERTY(bool direct READ direct CONSTANT)
    Q_PROPERTY(QVariantList handBoxes MEMBER m_handBoxes)
    Q_PROPERTY(QVariantList handLandmarks MEMBER m_handLandmarks)
    Q_PROPERTY(QVariantList bodyBoxes MEMBER m_bodyBoxes)
    Q_PROPERTY(QVariantList bodyLandmarks MEMBER m_bodyLandmarks)
public:
    explicit CameraPreview(QQuickItem *parent = nullptr);
    ~CameraPreview() override;
    void paint(QPainter *painter) override;
    bool available() const { return !m_image.isNull() && (m_videoPlaying || m_liveIntegerActive || m_sameFrameActive || (m_lastFrame.isValid() && m_lastFrame.elapsed() < 2000)); }
    bool streaming() const { return m_streaming; }
    void setStreaming(bool enabled);
    bool composited() const { return m_composited; }
    void setComposited(bool enabled);
    bool videoPlaying() const { return m_videoPlaying; }
    Q_INVOKABLE void playVideo(const QUrl &manifest, const QString &requestId);
    Q_INVOKABLE void stopVideo();
    void refreshComposition();
    void noteLiveBackendSnapshot();
    bool direct() const { return m_direct; }
    qreal paintedWidth() const;
    qreal paintedHeight() const;
signals:
    void frameChanged();
    void streamingChanged();
    void compositedChanged();
    void videoPlayingChanged();
    void videoStarted(const QString &requestId);
    void videoFinished(const QString &requestId);
    void videoFailed(const QString &requestId, const QString &error);
private:
    void pollFrame();
    void blitFrame();
    bool prepareFramebuffer();
    bool prepareLiveTransport(const QString &root);
    void noteLiveGuiFrame(quint64 signalNs);
    void noteLiveGuiTimerPulse();
    QImage preparedFrame(int w, int h);
    bool directActive() const { return m_direct && !m_composited; }
    void drawOverlay(QPainter *painter, const QRectF &target, bool prepared = false);
    void advanceVideo();
    bool readVideoFrame(int index, QImage *image, QString *error) const;
    void finishVideo(const QString &error = QString());
    void restoreCamera();
    bool m_liveIntegerActive=false;quint32 m_liveSequence=0,m_liveLogged=0;LiveIntegerInfo m_liveInfo;QString m_liveRoot;int m_scanFd=-1;
    bool m_liveTransportAttempted=false,m_liveTransportPhysicalReady=false,m_liveTransportReady=false;
    li_topology m_livePreparedTopology{};
    quint64 m_liveBackendSnapshotNs=0,m_liveGuiFrameSignalNs=0,m_liveGuiEventTurnNs=0;
    quint64 m_liveGuiProbeFirstNs=0,m_liveGuiProbeLastNs=0,m_liveGuiProbeMaxGapNs=0,m_liveReadyWrittenNs=0;
    unsigned m_liveGuiStableTimerPulses=0;
    quint64 m_liveKeeperBegin=0,m_liveKeeperDone=0,m_liveFbBegin=0,m_liveFbDone=0,m_liveTopologyDone=0;
    quint64 m_liveLastPollEntered=0;quint32 m_liveDuplicateBlits=0;
    QImage m_livePrepared;quint32 m_livePreparedSequence=0;int m_livePreparedWidth=0,m_livePreparedHeight=0;bool m_livePreparedBgr=false;
    bool m_sameFrameActive=false;
    quint32 m_sameFrameSequence=0,m_sameFrameLoggedSequence=0;
    V7FrameInfo m_sameFrameInfo;
    QTimer m_timer;
    QTimer m_videoTimer;
    QElapsedTimer m_videoClock;
    QString m_videoDirectory, m_videoRequestId, m_lastVideoRequestId;
    QStringList m_videoFrames;
    QImage m_cameraImage;
    double m_videoFps = 0;
    int m_videoFrameIndex = -1;
    bool m_videoPlaying = false;
    QElapsedTimer m_lastFrame, m_stats;
    QImage m_image;
    void *m_mapping = nullptr;
    unsigned m_sequence = 0, m_frames = 0;
    qint64 m_paintNanoseconds = 0;
    unsigned m_paints = 0;
    bool m_streaming = true, m_direct = false, m_composited = false;
    QVariantList m_handBoxes, m_handLandmarks, m_bodyBoxes, m_bodyLandmarks;
    void *m_fb = nullptr;
    unsigned m_fbBytes = 0, m_fbStride = 0, m_fbWidth = 0, m_fbHeight = 0;
    bool m_fbBgr = true;
};
