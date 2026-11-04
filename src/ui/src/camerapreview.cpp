#ifdef Q_OS_LINUX
#include <arm_neon.h>
#endif
#include "camerapreview.h"
#include "cameraframe.h"
#include "camerapixelcopy.h"
#include "pcdemooverlay.h"
#include <QPainter>
#include <QFontMetricsF>
#include <QQuickWindow>
#include <QVariantMap>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QImageReader>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <cmath>
#include <cstdio>
#include <cstring>
#ifdef __ARM_NEON
#include <arm_neon.h>
#endif
#ifdef Q_OS_LINUX
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/ioctl.h>
#include <linux/fb.h>
#include <unistd.h>
#endif

CameraPreview::CameraPreview(QQuickItem *parent) : QQuickPaintedItem(parent) {
    setFillColor(QColor("#153747"));
    setOpaquePainting(true);
    m_timer.setTimerType(Qt::PreciseTimer);
    m_timer.setInterval(33);
    bool profilePollOk=false;const int profilePollMs=qEnvironmentVariable("MEDCOMM_V18_POLL_MS").toInt(&profilePollOk);
    if(profilePollOk&&profilePollMs>=1&&profilePollMs<=33)m_timer.setInterval(profilePollMs);
    connect(&m_timer, &QTimer::timeout, this, &CameraPreview::noteLiveGuiTimerPulse);
    connect(&m_timer, &QTimer::timeout, this, &CameraPreview::pollFrame);
    connect(this, &QQuickItem::widthChanged, this, &CameraPreview::frameChanged);
    connect(this, &QQuickItem::heightChanged, this, &CameraPreview::frameChanged);
    m_timer.start();
    m_stats.start();
    m_videoTimer.setTimerType(Qt::PreciseTimer);
    connect(&m_videoTimer, &QTimer::timeout, this, &CameraPreview::advanceVideo);
    connect(this, &QQuickItem::visibleChanged, this, [this]() {
        if (!isVisible()) stopVideo();
    });
    m_direct = qEnvironmentVariableIntValue("MEDCOMM_DIRECT_PREVIEW") == 1;
    connect(this, &QQuickItem::windowChanged, this, [this](QQuickWindow *window) {
        if (window) connect(window, &QQuickWindow::frameSwapped, this, [this]() {
            const quint64 swapped=li_monotonic_ns();
            QMetaObject::invokeMethod(this,[this,swapped](){noteLiveGuiFrame(swapped);},Qt::QueuedConnection);
        },Qt::DirectConnection);
        if (window) connect(window, &QQuickWindow::frameSwapped, this, [this]() {
            if (directActive()) QTimer::singleShot(0, this, &CameraPreview::blitFrame);
        });
    });
}
CameraPreview::~CameraPreview() {
#ifdef Q_OS_LINUX
    if(m_scanFd>=0)close(m_scanFd);
    if (m_mapping) munmap(m_mapping, CameraMapBytes);
    if (m_fb) munmap(m_fb, m_fbBytes);
#endif
}
void CameraPreview::setStreaming(bool enabled) {
    if (m_streaming == enabled) return;
    m_streaming = enabled;
    if (!enabled) stopVideo();
    // Let the modal close and Qt compose the main page before resuming camera
    // writes; a synchronous blit here delays input handling and is overwritten.
    else QTimer::singleShot(0, this, &CameraPreview::pollFrame);
    emit streamingChanged();
}
void CameraPreview::setComposited(bool enabled) {
    if (m_composited == enabled) return;
    m_composited = enabled;
    // A translucent dialog must be composed above every fresh camera frame.
    // Keep acquisition running but never write over the dialog in fb memory.
    update();
    QTimer::singleShot(0, this, &CameraPreview::pollFrame);
    emit compositedChanged();
}
void CameraPreview::playVideo(const QUrl &manifest, const QString &requestId) {
    if (requestId.isEmpty() || requestId == m_lastVideoRequestId) return;
    stopVideo();
    m_lastVideoRequestId = requestId;
    const auto reject = [this, &requestId](const QString &reason) {
        emit videoFailed(requestId, reason);
    };
    if (!m_streaming || !isVisible()) {
        reject(QStringLiteral("画面暂不可播放，请关闭弹窗后重试"));
        return;
    }
    if (!manifest.isLocalFile() || !manifest.host().isEmpty() || manifest.hasQuery() || manifest.hasFragment()) {
        reject(QStringLiteral("手语视频地址不是有效的本地文件"));
        return;
    }
    const QFileInfo manifestInfo(manifest.toLocalFile());
    QFile file(manifestInfo.canonicalFilePath());
    if (!manifestInfo.isFile() || manifestInfo.size() <= 0 || manifestInfo.size() > 256 * 1024 ||
        !file.open(QIODevice::ReadOnly)) {
        reject(QStringLiteral("手语视频清单无法读取"));
        return;
    }
    QJsonParseError parseError;
    const QJsonDocument document = QJsonDocument::fromJson(file.readAll(), &parseError);
    const QJsonObject info = document.object();
    const double fps = info.value(QStringLiteral("fps")).toDouble(-1);
    const double count = info.value(QStringLiteral("frame_count")).toDouble(-1);
    const QJsonArray frames = info.value(QStringLiteral("frames")).toArray();
    if (parseError.error != QJsonParseError::NoError || !document.isObject() ||
        info.value(QStringLiteral("format")).toString() != QStringLiteral("medcomm-jpeg-sequence") ||
        info.value(QStringLiteral("version")).toDouble(-1) != 1 ||
        info.value(QStringLiteral("width")).toDouble(-1) != CameraWidth ||
        info.value(QStringLiteral("height")).toDouble(-1) != CameraHeight ||
        !std::isfinite(fps) || fps <= 0 || fps > 30 ||
        !std::isfinite(count) || count < 1 || count > 1800 || count != frames.size() ||
        count / fps > 60.0) {
        reject(QStringLiteral("手语视频清单的格式、尺寸或时长不正确"));
        return;
    }
    QStringList names;
    for (const QJsonValue &value : frames) {
        const QString name = value.toString();
        const QString suffix = QFileInfo(name).suffix().toLower();
        if (!value.isString() || name.isEmpty() || name == QStringLiteral(".") || name == QStringLiteral("..") ||
            name.contains('/') || name.contains('\\') || name.contains(':') || name.contains(QChar(0)) ||
            (suffix != QStringLiteral("jpg") && suffix != QStringLiteral("jpeg"))) {
            reject(QStringLiteral("手语视频清单包含无效的帧文件名"));
            return;
        }
        names.append(name);
    }
    m_videoDirectory = QFileInfo(manifestInfo.canonicalFilePath()).canonicalPath();
    m_videoFrames = names;
    m_videoFps = fps;
    m_videoRequestId = requestId;
    QImage first;
    QString error;
    if (!readVideoFrame(0, &first, &error)) {
        finishVideo(error);
        return;
    }
    m_videoPlaying = true;
    m_frames = 0; m_paints = 0; m_paintNanoseconds = 0; m_stats.restart();
    m_videoFrameIndex = 0;
    m_image = first;
    m_videoClock.start();
    m_videoTimer.setSingleShot(true);
    m_videoTimer.start(qMax(1, int(std::ceil(1000.0 / m_videoFps))));
    emit videoPlayingChanged();
    emit frameChanged();
    emit videoStarted(requestId);
    if (directActive()) blitFrame(); else update();
}
bool CameraPreview::readVideoFrame(int index, QImage *image, QString *error) const {
    if (index < 0 || index >= m_videoFrames.size()) {
        *error = QStringLiteral("手语视频帧序号不正确");
        return false;
    }
    const QFileInfo file(QDir(m_videoDirectory).filePath(m_videoFrames[index]));
    // Resolve symlinks as well as names: no listed frame may escape its asset directory.
    if (!file.isFile() || QFileInfo(file.canonicalFilePath()).absolutePath() != m_videoDirectory ||
        file.size() <= 0 || file.size() > 4 * 1024 * 1024) {
        *error = QStringLiteral("手语视频帧缺失或不可读取，请重新准备视频");
        return false;
    }
    QImageReader reader(file.canonicalFilePath(), "jpeg");
    reader.setAutoTransform(false);
    if (!reader.canRead() || reader.size() != QSize(CameraWidth, CameraHeight)) {
        *error = QStringLiteral("手语视频帧格式或尺寸不正确");
        return false;
    }
    QImage frame = reader.read();
    if (frame.isNull() || frame.size() != QSize(CameraWidth, CameraHeight)) {
        *error = QStringLiteral("手语视频解码失败，请重新播放");
        return false;
    }
    *image = frame.convertToFormat(QImage::Format_RGB888);
    return !image->isNull();
}
void CameraPreview::advanceVideo() {
    if (!m_videoPlaying) return;
    if (!m_streaming || !isVisible()) {
        stopVideo();
        return;
    }
    // Select by elapsed time, so slow storage/decoding skips frames without a queue.
    const int index = int(std::floor(m_videoClock.elapsed() * m_videoFps / 1000.0));
    if (index >= m_videoFrames.size()) {
        finishVideo();
        return;
    }
    if (index != m_videoFrameIndex) {
        QImage frame;
        QString error;
        if (!readVideoFrame(index, &frame, &error)) {
            finishVideo(error);
            return;
        }
        m_videoFrameIndex = index;
        m_image = frame;
        if (directActive()) blitFrame(); else update();
    }
    const double nextDue = (m_videoFrameIndex + 1) * 1000.0 / m_videoFps;
    m_videoTimer.start(qMax(1, int(std::ceil(nextDue - m_videoClock.elapsed()))));
}
void CameraPreview::restoreCamera() {
    m_image = m_cameraImage;
    m_sequence = 0; // Immediately acquire the latest complete frame, even after a long clip.
    m_frames = 0; m_paints = 0; m_paintNanoseconds = 0; m_stats.restart();
    pollFrame();
    if (directActive()) blitFrame(); else update();
    emit frameChanged();
}
void CameraPreview::finishVideo(const QString &error) {
    const QString requestId = m_videoRequestId;
    if (requestId.isEmpty()) return;
    const bool wasPlaying = m_videoPlaying;
    m_videoTimer.stop();
    m_videoPlaying = false;
    m_videoRequestId.clear();
    m_videoFrames.clear();
    m_videoFrameIndex = -1;
    restoreCamera();
    if (wasPlaying) emit videoPlayingChanged();
    if (error.isEmpty()) emit videoFinished(requestId);
    else emit videoFailed(requestId, error);
}
void CameraPreview::stopVideo() {
    if (!m_videoRequestId.isEmpty()) finishVideo();
}
qreal CameraPreview::paintedWidth() const {
    return qMin(width(), height() * CameraWidth / CameraHeight);
}
qreal CameraPreview::paintedHeight() const {
    return paintedWidth() * CameraHeight / CameraWidth;
}
void CameraPreview::paint(QPainter *painter) {
    if (m_image.isNull()) return;
    // LinuxFB can flush a dirty UI rectangle across the camera plane when a
    // recognition label changes. Its backing store must contain a real frame,
    // even while the high-rate preview writes directly to the framebuffer.
    QElapsedTimer elapsed; elapsed.start();
    const QRectF target((width() - paintedWidth()) / 2, (height() - paintedHeight()) / 2,
                        paintedWidth(), paintedHeight());
    painter->drawImage(target, m_image);
    if (!m_videoPlaying && !m_sameFrameActive && !m_liveIntegerActive) drawOverlay(painter, target);
    m_paintNanoseconds += elapsed.nsecsElapsed(); ++m_paints;
}
void CameraPreview::refreshComposition() {
    // Refresh only for UI changes, not every incoming camera/landmark packet.
    // This prevents blank damage rectangles without putting the full camera
    // stream through the slower software scene graph.
    if (m_direct && isVisible() && !m_image.isNull()) update();
}
void CameraPreview::drawOverlay(QPainter *painter, const QRectF &target, bool prepared) {
    if(pcDemoDraw(painter,target,prepared))return;
    // The same native-camera coordinates drive both the software Qt fallback
    // and direct framebuffer preview, without a second video composition pass.
    const qreal sx = target.width() / CameraWidth, sy = target.height() / CameraHeight;
    painter->save();
    painter->setClipRect(target);
    painter->translate(target.topLeft());
    QFont labelFont = painter->font();
    labelFont.setPixelSize(qMax(12, qRound(15 * qMin(sx, sy))));
    labelFont.setBold(true);
    painter->setFont(labelFont);
    const QFontMetricsF labelMetrics(labelFont);
    const auto drawBoxes = [&](const QVariantList &boxes, const QColor &color, int thickness, const QString &label) {
        const qreal labelWidth = qMin(target.width(), labelMetrics.horizontalAdvance(label) + 10);
        const qreal labelHeight = qMin(target.height(), labelMetrics.height() + 4);
        for (const QVariant &value : boxes) {
            const auto box = value.toMap();
            const QRectF bounds(box.value("x0").toDouble() * sx, box.value("y0").toDouble() * sy,
                                (box.value("x1").toDouble() - box.value("x0").toDouble()) * sx,
                                (box.value("y1").toDouble() - box.value("y0").toDouble()) * sy);
            painter->setPen(QPen(color, thickness));
            painter->setBrush(Qt::NoBrush);
            painter->drawRect(bounds);
            // Keep the caption just inside the upper edge and on the camera
            // plane, including detections touching the image boundary.
            const QRectF plate(qBound(qreal(0), bounds.left() + thickness / 2.0 + 1, target.width() - labelWidth),
                               qBound(qreal(0), bounds.top() + thickness / 2.0 + 1, target.height() - labelHeight),
                               labelWidth, labelHeight);
            painter->setPen(QPen(color, 1));
            painter->setBrush(QColor("#102128"));
            painter->drawRect(plate);
            painter->setPen(Qt::white);
            painter->drawText(plate, Qt::AlignCenter, label);
        }
    };
    // All seventeen COCO Body points are rendered, including low confidence points.
    // The frame clip handles coordinates outside the camera; no prediction is substituted.
    if (m_bodyLandmarks.size() == 17) {
        QPointF points[17];
        for (int i = 0; i < 17; ++i) {
            const auto point = m_bodyLandmarks[i].toMap();
            points[i] = QPointF(point.value("x").toDouble() * sx, point.value("y").toDouble() * sy);
        }
        static const unsigned char bodyEdges[][2] = {
            {5,6},{5,7},{7,9},{6,8},{8,10},
            {5,11},{6,12},{11,12},{11,13},{13,15},{12,14},{14,16}
        };
        painter->setPen(QPen(QColor("#071318"), 7, Qt::SolidLine, Qt::RoundCap, Qt::RoundJoin));
        for (const auto &edge : bodyEdges) painter->drawLine(points[edge[0]], points[edge[1]]);
        painter->setPen(QPen(QColor("#48BFFF"), 4, Qt::SolidLine, Qt::RoundCap, Qt::RoundJoin));
        for (const auto &edge : bodyEdges) painter->drawLine(points[edge[0]], points[edge[1]]);
        painter->setPen(QPen(QColor("#071318"), 2));
        painter->setBrush(QColor("#FFD84D"));
        for (const QPointF &point : points) painter->drawEllipse(point, 5, 5);
    }
    // MediaPipe HAND_CONNECTIONS, identical to A's PC landmark rendering.
    static const unsigned char connections[][2] = {
        {0,1}, {1,2}, {2,3}, {3,4}, {0,5}, {5,6}, {6,7}, {7,8},
        {5,9}, {9,10}, {10,11}, {11,12}, {9,13}, {13,14}, {14,15},
        {15,16}, {13,17}, {0,17}, {17,18}, {18,19}, {19,20}
    };
    unsigned handIndex = 0;
    for (const QVariant &value : m_handLandmarks) {
        const QVariantList rawPoints = value.toMap().value("keypoints").toList();
        if (rawPoints.size() != 21) continue;
        QPointF points[21];
        for (int i = 0; i < 21; ++i) {
            const auto point = rawPoints[i].toMap();
            points[i] = QPointF(point.value("x").toDouble() * sx, point.value("y").toDouble() * sy);
        }
        const QColor color = handIndex++ % 2 ? QColor(255,80,200) : QColor(120,220,60);
        painter->setPen(QPen(QColor("#071318"), 7, Qt::SolidLine, Qt::RoundCap, Qt::RoundJoin));
        for (const auto &connection : connections)
            painter->drawLine(points[connection[0]], points[connection[1]]);
        painter->setPen(QPen(color, 4, Qt::SolidLine, Qt::RoundCap, Qt::RoundJoin));
        for (const auto &connection : connections)
            painter->drawLine(points[connection[0]], points[connection[1]]);
        painter->setPen(QPen(QColor("#071318"), 2));
        painter->setBrush(QColor(245,245,245));
        for (const QPointF &point : points) painter->drawEllipse(point, 4, 4);
    }
    drawBoxes(m_bodyBoxes, QColor("#00FF00"), 4, QStringLiteral("person"));
    drawBoxes(m_handBoxes, QColor("#FFD84D"), 4, QStringLiteral("hand"));
    painter->restore();
}
void CameraPreview::pollFrame() {
#ifdef Q_OS_LINUX
    if (!isVisible() || !m_streaming || m_videoPlaying) return;
    const quint64 profilePollEntered=li_monotonic_ns(),profilePreviousPoll=m_liveLastPollEntered;m_liveLastPollEntered=profilePollEntered;
    if(!qEnvironmentVariableIsEmpty("MEDCOMM_PC_DEMO_ROOT")){
        QImage pair;quint64 fid=0;const int action=pcDemoPollPair(&pair,&fid);
        if(action){
            const bool first=!m_lastFrame.isValid();m_image=pair;m_cameraImage=pair;m_sequence=quint32(fid);
            if(action==1){m_lastFrame.start();++m_frames;}
            if(directActive())blitFrame();else update();
            if(first&&action==1){if(directActive())update();emit frameChanged();}
        }else if(m_lastFrame.isValid()&&m_lastFrame.elapsed()>=2000){m_lastFrame.invalidate();emit frameChanged();}
        if(m_stats.elapsed()>=5000){std::fprintf(stderr,"PC_DEMO_PAIRED_IMAGE_FPS %.2f paint_ms=%.2f paints=%u no_new_pair_no_timer_blit=1\n",m_frames*1000.0/m_stats.elapsed(),m_paints?m_paintNanoseconds/(1000000.0*m_paints):0,m_paints);std::fflush(stderr);m_frames=0;m_paints=0;m_paintNanoseconds=0;m_stats.restart();}
        return;
    }
    const QString liveRoot=qEnvironmentVariable("MEDCOMM_V18_LIVE_ROOT");
    if(liveRoot.startsWith(QStringLiteral("/run/gesture-live-integer-hdmi-v18/")) && QFile::exists(liveRoot+QStringLiteral("/live.enable"))){
        if(qEnvironmentVariableIntValue("MEDCOMM_V18_PREPARE_BEFORE_CAPTURE")==1&&!prepareLiveTransport(liveRoot))return;
        int profilePollMs=0;QByteArray profileConfigSha;if(!v18ApplySessionProfile(liveRoot,&profilePollMs,&profileConfigSha))return;
        if(m_timer.interval()!=profilePollMs)m_timer.setInterval(profilePollMs);
        m_liveIntegerActive=true;m_liveRoot=liveRoot;
        QImage candidate;LiveIntegerInfo info;
        if(!v18ReadFrame(liveRoot,m_liveSequence,&candidate,&info))return;
        info.pollEntered=profilePollEntered;info.previousPollEntered=profilePreviousPoll;info.pollIntervalMs=quint32(m_timer.interval());info.previousFrameDuplicateBlits=m_liveDuplicateBlits;m_liveDuplicateBlits=0;
        info.profileConfigSha=profileConfigSha;info.configuredCachePrepared=qEnvironmentVariableIntValue("MEDCOMM_V18_CACHE_PREPARED")==1;
        m_liveSequence=info.publication;m_liveInfo=info;
        if(m_scanFd<0){m_liveKeeperBegin=li_monotonic_ns();m_scanFd=v18ReceiveKeeperFd(liveRoot);m_liveKeeperDone=li_monotonic_ns();}
        m_liveInfo.keeperReceiveBegin=m_liveKeeperBegin;m_liveInfo.keeperReceiveDone=m_liveKeeperDone;
        m_image=candidate;m_cameraImage=candidate;m_lastFrame.start();
        if(directActive())blitFrame();else {update();v18Acknowledge(liveRoot,info,0,-1);}
        emit frameChanged();return;
    }
    if(m_liveIntegerActive){m_liveIntegerActive=false;m_liveSequence=0;m_sequence=0;}
    const bool sameFrameRequested=QFile::exists(QStringLiteral("/run/medcomm/v7_same_frame.enable"));
    if (sameFrameRequested) {
        m_sameFrameActive=true;
        QImage candidate;V7FrameInfo info;
        if (!v7ReadSameFrame(QStringLiteral("/run/medcomm/v7_same_frame.frame"),m_sameFrameSequence,&candidate,&info))return;
        m_sameFrameSequence=info.publication;m_sameFrameInfo=info;
        m_image=candidate;m_cameraImage=candidate;m_lastFrame.start();
        std::fprintf(stderr,"V7_SAME_FRAME_ACQUIRED source_id=%u publication_id=%u observed_ns=%llu acquired_ns=%llu source_to_ui_copy_ms=%.3f scan_verified=0\n",
            info.source,info.publication,(unsigned long long)info.observed,(unsigned long long)info.acquired,
            double(info.acquired-info.observed)/1000000.);
        std::fflush(stderr);
        if(directActive())blitFrame();else update();
        emit frameChanged();return;
    }
    if(m_sameFrameActive){m_sameFrameActive=false;m_sameFrameSequence=0;m_sequence=0;}

    if (!m_mapping) {
        const int fd = open("/run/medcomm/camera.frame", O_RDONLY);
        if (fd < 0) return;
        struct stat st{};
        if (fstat(fd, &st) == 0 && st.st_size == CameraMapBytes) {
            m_mapping = mmap(nullptr, CameraMapBytes, PROT_READ, MAP_SHARED, fd, 0);
            if (m_mapping == MAP_FAILED) m_mapping = nullptr;
        }
        close(fd);
        if (!m_mapping) return;
    }
    const auto *header = static_cast<const CameraFrameHeader *>(m_mapping);
    const unsigned before = __atomic_load_n(&header->sequence, __ATOMIC_ACQUIRE);
    if (!before || before == m_sequence || header->magic != CameraFrameMagic ||
        header->width != CameraWidth || header->height != CameraHeight || header->stride != CameraWidth * 3) {
        if (m_lastFrame.isValid() && m_lastFrame.elapsed() >= 2000) {
            m_lastFrame.invalidate(); emit frameChanged();
        }
        return;
    }
    const unsigned slot = before % 3;
    const unsigned slotBefore = __atomic_load_n(&header->slotSequence[slot], __ATOMIC_ACQUIRE);
    if (slotBefore != before * 2) return;
    QImage candidate(CameraWidth, CameraHeight, QImage::Format_RGB888);
    // Convert while copying from the shared slot into private QImage storage.
    // The sequence check below covers every shared source read.
    medcomm_copy_bgr_to_rgb(candidate.bits(),
        reinterpret_cast<const unsigned char *>(header + 1) + slot * CameraBytes,
        CameraWidth * CameraHeight);
    __atomic_thread_fence(__ATOMIC_ACQUIRE);
    if (slotBefore != __atomic_load_n(&header->slotSequence[slot], __ATOMIC_ACQUIRE)) return;
    m_sequence = before;
    m_image = candidate;
    m_cameraImage = candidate;
    const bool firstFrame = !m_lastFrame.isValid();
    m_lastFrame.start();
    if (directActive()) blitFrame(); else update();
    if (directActive() && firstFrame) update();
    if (!directActive() || firstFrame) emit frameChanged();
    ++m_frames;
    if (m_stats.elapsed() >= 5000) {
        std::fprintf(stderr, "CAMERA_PREVIEW_FPS %.2f paint_ms=%.2f paints=%u\n", m_frames * 1000.0 / m_stats.elapsed(),
                     m_paints ? m_paintNanoseconds / (1000000.0 * m_paints) : 0, m_paints);
        std::fflush(stderr);
        m_frames = 0; m_stats.restart();
        m_paints = 0; m_paintNanoseconds = 0;
    }
#endif
}
bool CameraPreview::prepareFramebuffer() {
#ifdef Q_OS_LINUX
    if (!m_fb) {
        m_liveFbBegin=li_monotonic_ns();
        const int fd = open("/dev/fb1", O_RDWR);
        if (fd < 0) return false;
        fb_var_screeninfo v{}; fb_fix_screeninfo f{};
        if (ioctl(fd, FBIOGET_VSCREENINFO, &v) == 0 && ioctl(fd, FBIOGET_FSCREENINFO, &f) == 0 &&
            v.bits_per_pixel == 24 && v.xoffset == 0 && v.yoffset == 0 && v.green.offset == 8 &&
            ((v.red.offset == 16 && v.blue.offset == 0) || (v.red.offset == 0 && v.blue.offset == 16))) {
            m_fbBytes = f.smem_len; m_fbStride = f.line_length; m_fbWidth = v.xres; m_fbHeight = v.yres;
            // Vendor PL contains a channel swap after VDMA. Its framebuffer
            // bitfields alone therefore do not describe the HDMI wire order.
            const QString order = qEnvironmentVariable("MEDCOMM_FB_ORDER");
            m_fbBgr = order.isEmpty() ? v.red.offset == 16 : order == QStringLiteral("BGR");
            m_fb = mmap(nullptr, m_fbBytes, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
            if (m_fb == MAP_FAILED) m_fb = nullptr;
        }
        close(fd);
        m_liveFbDone=li_monotonic_ns();
        if (!m_fb) return false;
    }
    return true;
#else
    return false;
#endif
}
void CameraPreview::noteLiveBackendSnapshot() {
    if(m_liveBackendSnapshotNs || qEnvironmentVariableIntValue("MEDCOMM_V18_PREPARE_BEFORE_CAPTURE")!=1)return;
    const QString root=qEnvironmentVariable("MEDCOMM_V18_LIVE_ROOT");
    if(!root.startsWith(QStringLiteral("/run/gesture-live-integer-hdmi-v18/")))return;
    m_liveBackendSnapshotNs=li_monotonic_ns();
    if(window())window()->update();
    std::fprintf(stderr,"V18_UI_FIRST_BACKEND_SNAPSHOT ns=%llu\n",(unsigned long long)m_liveBackendSnapshotNs);std::fflush(stderr);
}
void CameraPreview::noteLiveGuiFrame(quint64 signalNs) {
    if(m_liveTransportReady || !m_liveBackendSnapshotNs || signalNs<m_liveBackendSnapshotNs || m_liveGuiFrameSignalNs)return;
    if(!window() || !window()->isVisible() || !window()->isExposed())return;
    m_liveGuiFrameSignalNs=signalNs;m_liveGuiEventTurnNs=li_monotonic_ns();
    std::fprintf(stderr,"V18_UI_FIRST_REAL_GUI_FRAME swapped_ns=%llu gui_queue_return_ns=%llu\n",(unsigned long long)m_liveGuiFrameSignalNs,(unsigned long long)m_liveGuiEventTurnNs);std::fflush(stderr);
}
void CameraPreview::noteLiveGuiTimerPulse() {
    if(m_liveTransportReady || !m_liveGuiEventTurnNs)return;
    const quint64 now=li_monotonic_ns();
    if(m_timer.interval()!=33)return;
    const quint64 gap=m_liveGuiProbeLastNs?now-m_liveGuiProbeLastNs:0;
    if(!m_liveGuiProbeLastNs || gap>100000000 || gap<16000000){m_liveGuiStableTimerPulses=1;m_liveGuiProbeFirstNs=now;m_liveGuiProbeMaxGapNs=0;}
    else {++m_liveGuiStableTimerPulses;if(gap>m_liveGuiProbeMaxGapNs)m_liveGuiProbeMaxGapNs=gap;}
    m_liveGuiProbeLastNs=now;
}
bool CameraPreview::prepareLiveTransport(const QString &root) {
#ifdef Q_OS_LINUX
    if(m_liveTransportReady)return true;
    if(!directActive())return false;
    if(!m_liveTransportAttempted){
      m_liveTransportAttempted=true;
      if(!prepareFramebuffer())return false;
      m_liveKeeperBegin=li_monotonic_ns();m_scanFd=v18ReceiveKeeperFd(root);m_liveKeeperDone=li_monotonic_ns();
      if(m_scanFd<0)return false;
      const int rc=li_scan_validate_fd(m_scanFd,&m_livePreparedTopology);m_liveTopologyDone=li_monotonic_ns();
      if(rc)return false;
      m_liveTransportPhysicalReady=true;
    }
    if(!m_liveTransportPhysicalReady || !m_liveBackendSnapshotNs || !m_liveGuiFrameSignalNs || !m_liveGuiEventTurnNs || m_liveGuiStableTimerPulses<3)return false;
    if(!window() || !window()->isVisible() || !window()->isExposed())return false;
    const li_topology &topology=m_livePreparedTopology;m_liveReadyWrittenNs=li_monotonic_ns();
    QJsonObject result{{"version",2},{"status",QStringLiteral("UI_REAL_GUI_COMPOSED_AND_EVENT_LOOP_READY_BEFORE_CAPTURE")},{"session_id",QFileInfo(root).fileName()},{"UI_pid",int(getpid())},
      {"framebuffer_init_begin_ns",QString::number(m_liveFbBegin)},{"framebuffer_init_done_ns",QString::number(m_liveFbDone)},
      {"keeper_receive_begin_ns",QString::number(m_liveKeeperBegin)},{"keeper_receive_done_ns",QString::number(m_liveKeeperDone)},{"topology_done_ns",QString::number(m_liveTopologyDone)},
      {"first_backend_snapshot_applied_ns",QString::number(m_liveBackendSnapshotNs)},{"first_gui_frame_swapped_signal_ns",QString::number(m_liveGuiFrameSignalNs)},
      {"first_gui_queued_return_ns",QString::number(m_liveGuiEventTurnNs)},{"gui_stable_timer_first_ns",QString::number(m_liveGuiProbeFirstNs)},
      {"gui_stable_timer_last_ns",QString::number(m_liveGuiProbeLastNs)},{"gui_stable_timer_max_gap_ns",QString::number(m_liveGuiProbeMaxGapNs)},
      {"gui_stable_timer_pulses",int(m_liveGuiStableTimerPulses)},{"gui_probe_timer_interval_ms",m_timer.interval()},{"ready_written_ns",QString::number(m_liveReadyWrittenNs)},
      {"framebuffer_width",int(m_fbWidth)},{"framebuffer_height",int(m_fbHeight)},{"framebuffer_stride",int(m_fbStride)},{"framebuffer_bytes",int(m_fbBytes)},
      {"crtc_id",int(topology.crtc_id)},{"connector_id",int(topology.connector_id)},{"mode_width",int(topology.width)},{"mode_height",int(topology.height)},
      {"initial_real_GUI_composition_completed",true},{"normal_GUI_backingstore_flushed",true},{"GUI_event_loop_queued_callback_returned",true},
      {"preparation_current_frame_read",false},{"preparation_direct_camera_framebuffer_pixels_written",false},{"preparation_scan_or_atomic_commit_executed",false},{"new_DRM_open",false},{"NN_RUN",0}};
    const QByteArray receipt=QJsonDocument(result).toJson(QJsonDocument::Compact);QSaveFile ready(root+QStringLiteral("/ui_transport_ready.json"));
    if(!ready.open(QIODevice::WriteOnly)||!ready.setPermissions(QFileDevice::ReadOwner|QFileDevice::WriteOwner)||ready.write(receipt)!=receipt.size()||!ready.commit())return false;
    m_liveTransportReady=true;
    std::fprintf(stderr,"V18_UI_REAL_GUI_PREPARED pid=%d snapshot_ns=%llu swap_ns=%llu queued_ns=%llu timer_pulses=%u max_gap_ns=%llu ready_ns=%llu current_frame_read=0 scan_commits=0\n",int(getpid()),(unsigned long long)m_liveBackendSnapshotNs,(unsigned long long)m_liveGuiFrameSignalNs,(unsigned long long)m_liveGuiEventTurnNs,m_liveGuiStableTimerPulses,(unsigned long long)m_liveGuiProbeMaxGapNs,(unsigned long long)m_liveReadyWrittenNs);std::fflush(stderr);
    return true;
#else
    Q_UNUSED(root);return false;
#endif
}
void CameraPreview::blitFrame() {
#ifdef Q_OS_LINUX
    if (!directActive() || !m_streaming || !isVisible() || m_image.isNull()) return;
    if (!prepareFramebuffer()) return;
    QElapsedTimer elapsed; elapsed.start();
    if(m_liveIntegerActive){m_liveInfo.framebufferInitBegin=m_liveFbBegin;m_liveInfo.framebufferInitDone=m_liveFbDone;}
    if(m_liveIntegerActive){m_liveInfo.blitBegin=li_monotonic_ns();if(m_liveLogged==m_liveSequence)++m_liveDuplicateBlits;}
    int w = qRound(paintedWidth()), h = qRound(paintedHeight());
    if (w >= int(CameraWidth) && w - int(CameraWidth) <= 16 && h >= int(CameraHeight) && h - int(CameraHeight) <= 16) {
        w = CameraWidth; h = CameraHeight;
    }
    const QPointF origin = mapToScene(QPointF((width() - w) / 2, (height() - h) / 2));
    // Aligned writes avoid byte stores to the write-combined framebuffer.
    const int x = (qRound(origin.x()) + 8) & ~15, y = qRound(origin.y());
    if (x < 0 || y < 0 || w <= 0 || h <= 0 || x + w > int(m_fbWidth) || y + h > int(m_fbHeight) ||
        (y + h) * m_fbStride > m_fbBytes) return;
    const quint64 prepareBegin=li_monotonic_ns();
    QImage output = preparedFrame(w, h);
    const quint64 prepareDone=li_monotonic_ns();
    const bool neonCopy=qEnvironmentVariableIntValue("MEDCOMM_FB_NEON")==1;
    if(m_liveIntegerActive){m_liveInfo.preparedDone=li_monotonic_ns();m_liveInfo.blitWriteBegin=li_monotonic_ns();}
    for (int row = 0; row < h; ++row) {
        auto *dst=static_cast<unsigned char *>(m_fb)+(y+row)*m_fbStride+x*3;
        const auto *src=output.constScanLine(row);int bytes=w*3;
        if(neonCopy){
            while(bytes>=64){const uint8x16_t a=vld1q_u8(src),b=vld1q_u8(src+16),c=vld1q_u8(src+32),d=vld1q_u8(src+48);vst1q_u8(dst,a);vst1q_u8(dst+16,b);vst1q_u8(dst+32,c);vst1q_u8(dst+48,d);src+=64;dst+=64;bytes-=64;}
            while(bytes>=16){vst1q_u8(dst,vld1q_u8(src));src+=16;dst+=16;bytes-=16;}
        }
        std::memcpy(dst,src,bytes);
    }
    pcDemoCopied(li_monotonic_ns(),m_sequence,prepareBegin,prepareDone,neonCopy);
    if(m_liveIntegerActive && m_liveLogged!=m_liveSequence){
        const quint64 copied=li_monotonic_ns();m_liveLogged=m_liveSequence;
        v18Acknowledge(m_liveRoot,m_liveInfo,copied,m_scanFd);
    }
    if(m_sameFrameActive && m_sameFrameLoggedSequence!=m_sameFrameSequence){
        const quint64 completed=v7MonotonicNs();m_sameFrameLoggedSequence=m_sameFrameSequence;
        std::fprintf(stderr,"V7_FRAMEBUFFER_COPY_COMPLETE source_id=%u publication_id=%u completed_ns=%llu source_to_fb_copy_ms=%.3f ui_copy_to_fb_copy_ms=%.3f scan_verified=0\n",
            m_sameFrameInfo.source,m_sameFrameInfo.publication,(unsigned long long)completed,
            double(completed-m_sameFrameInfo.observed)/1000000.,
            double(completed-m_sameFrameInfo.acquired)/1000000.);
        std::fflush(stderr);
    }
    m_paintNanoseconds += elapsed.nsecsElapsed(); ++m_paints;
#endif
}

QImage CameraPreview::preparedFrame(int w, int h) {
    if(!m_videoPlaying&&!qEnvironmentVariableIsEmpty("MEDCOMM_PC_DEMO_ROOT")){
        const bool fast=qEnvironmentVariableIntValue("MEDCOMM_RENDER_FAST")==1;
        const bool verify=qEnvironmentVariableIntValue("MEDCOMM_RENDER_VERIFY")==1;
        QImage reference;
        if(verify){reference=QImage(w,h,QImage::Format_RGB888);reference.fill(Qt::black);
            QPainter painter(&reference);pcDemoDraw(&painter,QRectF(0,0,w,h),true);}
        QImage output;bool seeded=false;
        if(fast){auto &state=pcDemoState();QMutexLocker lock(&state.mutex);
            if(state.pair.valid&&state.pair.image.size()==QSize(w,h)){output=state.pair.image.copy();seeded=true;}}
        if(output.isNull()){output=QImage(w,h,QImage::Format_RGB888);output.fill(Qt::black);}
        {QPainter painter(&output);pcDemoDraw(&painter,QRectF(0,0,w,h),true,seeded,fast);}
        if(verify&&output!=reference)qFatal("RENDER_PIXEL_EQUIVALENCE_FAILED");
        if(m_fbBgr){
            if(qEnvironmentVariableIntValue("MEDCOMM_SWAP_NEON")==1){
                QImage swapped(w,h,QImage::Format_RGB888);
                for(int y=0;y<h;++y)medcomm_copy_bgr_to_rgb(swapped.scanLine(y),output.constScanLine(y),w);
                if(verify&&swapped!=output.rgbSwapped())qFatal("SWAP_PIXEL_EQUIVALENCE_FAILED");
                output=swapped;
            }else output=output.rgbSwapped();
        }return output;
    }
    const bool cacheLive=m_liveIntegerActive&&qEnvironmentVariableIntValue("MEDCOMM_V18_CACHE_PREPARED")==1;
    if(m_liveIntegerActive)m_liveInfo.preparedCacheHit=false;
    if(cacheLive&&m_livePreparedSequence==m_liveSequence&&m_livePreparedWidth==w&&m_livePreparedHeight==h&&m_livePreparedBgr==m_fbBgr&&!m_livePrepared.isNull()){m_liveInfo.preparedCacheHit=true;return m_livePrepared;}
    // A shallow QImage copy retains immutable pixels. QPainter detaches it if
    // an overlay really needs drawing; scaling/conversion still own outputs.
    QImage output = w == m_image.width() && h == m_image.height()
                        ? m_image : m_image.scaled(w, h, Qt::IgnoreAspectRatio, Qt::FastTransformation);
    if (!m_liveIntegerActive && !m_sameFrameActive && !m_videoPlaying && (!qEnvironmentVariableIsEmpty("MEDCOMM_PC_DEMO_ROOT") || !m_handBoxes.isEmpty() || !m_handLandmarks.isEmpty() || !m_bodyBoxes.isEmpty() || !m_bodyLandmarks.isEmpty())) {
        QPainter painter(&output);
        drawOverlay(&painter, QRectF(0, 0, w, h));
    }
    if (output.format() != QImage::Format_RGB888)
        output = output.convertToFormat(QImage::Format_RGB888);
    if (m_fbBgr) output = output.rgbSwapped();
    if(cacheLive){m_livePrepared=output;m_livePreparedSequence=m_liveSequence;m_livePreparedWidth=w;m_livePreparedHeight=h;m_livePreparedBgr=m_fbBgr;}
    return output;
}
