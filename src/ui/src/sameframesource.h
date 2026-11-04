#pragma once
#include "camerapixelcopy.h"
#include <QFile>
#include <QFont>
#include <QImage>
#include <QPainter>
#include <QtEndian>
#include <cstdint>
#include <cstring>
#include <time.h>

struct V7FrameInfo {
    quint32 publication=0, source=0;
    quint64 observed=0, inferred=0, published=0, acquired=0;
};

inline quint64 v7MonotonicNs() {
    struct timespec now{};
    ::clock_gettime(CLOCK_MONOTONIC,&now);
    return quint64(now.tv_sec)*1000000000ULL+quint64(now.tv_nsec);
}

// Each open descriptor owns a complete immutable inode. The producer replaces
// the path only after writing its complete header+image; no shared-slot race.
inline bool v7ReadSameFrame(const QString &path,quint32 previous,QImage *image,V7FrameInfo *info) {
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly) || file.size()!=64+800*480*3) return false;
    const QByteArray head=file.read(64);
    if (head.size()!=64) return false;
    auto u32=[&](int offset){return qFromLittleEndian<quint32>(reinterpret_cast<const uchar *>(head.constData()+offset));};
    auto u64=[&](int offset){return qFromLittleEndian<quint64>(reinterpret_cast<const uchar *>(head.constData()+offset));};
    if (u32(0)!=0x46533756 || u32(4)!=1 || u32(8)!=800 || u32(12)!=480 ||
        u32(16)!=2400 || !u32(20) || u32(20)==previous || !u32(24) ||
        u32(28)!=1 || u32(56)!=800*480*3) return false;
    V7FrameInfo value;
    value.publication=u32(20);value.source=u32(24);
    value.observed=u64(32);value.inferred=u64(40);value.published=u64(48);
    if (!value.observed || value.inferred<value.observed || value.published<value.inferred) return false;
    const QByteArray pixels=file.read(800*480*3);
    if (pixels.size()!=800*480*3) return false;
    QImage output(800,480,QImage::Format_RGB888);
    medcomm_copy_bgr_to_rgb(output.bits(),reinterpret_cast<const unsigned char *>(pixels.constData()),800*480);
    value.acquired=v7MonotonicNs();
    if (value.acquired<value.observed) return false;
    // The displayed picture includes its actual age. The original business
    // posture freshness rule remains 350ms and receives no substituted clock.
    QPainter painter(&output);
    painter.fillRect(QRect(0,450,800,30),QColor(12,28,34));
    painter.setPen(Qt::white);
    QFont font=painter.font();font.setPixelSize(16);painter.setFont(font);
    painter.drawText(QRect(8,450,784,30),Qt::AlignVCenter,
        QStringLiteral("same source %1 | source to UI copy %2 ms | held frame").arg(value.source)
          .arg(double(value.acquired-value.observed)/1000000.,0,'f',1));
    painter.end();
    *image=output;*info=value;return true;
}
