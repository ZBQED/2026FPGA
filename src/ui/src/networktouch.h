#pragma once

#include <QCoreApplication>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLocalServer>
#include <QLocalSocket>
#include <QMouseEvent>
#include <QPointer>
#include <QQuickItem>
#include <QQuickWindow>
#include <QTimer>
#include <QtMath>
#include <ctime>
#include <chrono>

// The network authentication lives in a separate process. This owner-only local
// endpoint dispatches genuine single-contact reports on the Qt GUI thread.
class NetworkTouch : public QObject {
public:
    explicit NetworkTouch(QQuickWindow *window, const QString &path, QObject *parent=nullptr)
        : QObject(parent), window_(window), server_(this), timer_(this)
    {
        server_.setSocketOptions(QLocalServer::UserAccessOption);
        // The supervisor owns this private directory and starts one patient UI.
        QLocalServer::removeServer(path);
        connect(&server_, &QLocalServer::newConnection, this, [this]() {
            while (server_.hasPendingConnections()) {
                QLocalSocket *candidate = server_.nextPendingConnection();
                if (socket_) { candidate->abort(); candidate->deleteLater(); continue; }
                socket_ = candidate;
                buffer_.clear(); sequence_=0; cancel(); lastPacket_=monotonicMs();
                connect(candidate, &QLocalSocket::readyRead, this, [this]() { read(); });
                connect(candidate, &QLocalSocket::disconnected, this, [this,candidate]() {
                    if (socket_ == candidate) { cancel(); socket_=nullptr; buffer_.clear(); }
                    candidate->deleteLater();
                });
            }
        });
        connect(&timer_, &QTimer::timeout, this, [this]() {
            if (socket_ && monotonicMs()-lastPacket_ > 500) reject();
        });
        timer_.start(50);
        listening_ = server_.listen(path);
        qInfo("PATIENT_NETWORK_TOUCH listening=%d", int(listening_));
    }

    bool listening() const { return listening_; }
    ~NetworkTouch() override {
        // QObject child destruction can emit disconnected after C++ members
        // have been destroyed; detach callbacks while all state is still live.
        timer_.stop();
        cancel();
        if (socket_) {
            QObject::disconnect(socket_, nullptr, this, nullptr);
            socket_->abort();
        }
        QObject::disconnect(&server_, nullptr, this, nullptr);
        server_.close();
    }
    static qint64 monotonicMs() {
#ifdef Q_OS_UNIX
        struct timespec value;
        if (clock_gettime(CLOCK_MONOTONIC, &value) != 0) return -1;
        return qint64(value.tv_sec)*1000 + value.tv_nsec/1000000;
#else
        return std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count();
#endif
    }

private:
    void cancel() {
        // Ungrab emits QML canceled, never clicked. Do not synthesize release.
        if (down_ && window_) {
            if (auto *grabber = window_->mouseGrabberItem()) grabber->ungrabMouse();
            QEvent ungrab(QEvent::UngrabMouse);
            QCoreApplication::sendEvent(window_, &ungrab);
        }
        down_=false; armed_=false;
    }
    void reject() {
        cancel();
        if (socket_) socket_->abort();
        buffer_.clear();
    }
    void read() {
        if (!socket_) return;
        buffer_ += socket_->readAll();
        if (buffer_.size() > 8192) { reject(); return; }
        int newline;
        while ((newline=buffer_.indexOf('\n')) >= 0) {
            const QByteArray line=buffer_.left(newline);
            buffer_.remove(0,newline+1);
            QJsonParseError error;
            const auto document=QJsonDocument::fromJson(line,&error);
            if (error.error!=QJsonParseError::NoError || !document.isObject() || line.size()>1024) {
                reject(); return;
            }
            const auto obj=document.object();
            const qint64 now=monotonicMs();
            const auto seq=obj.value("seq");
            const auto stamp=obj.value("monotonic_ms");
            if (!seq.isDouble() || seq.toDouble()!=double(sequence_+1) ||
                !stamp.isDouble() || stamp.toDouble()>now || now-stamp.toDouble()>250) {
                reject(); return;
            }
            ++sequence_; lastPacket_=now;
            const auto type=obj.value("type").toString();
            if (type=="cancel") { cancel(); continue; }
            if (type=="heartbeat") continue;
            if (type=="ready") { if (!down_) armed_=true; continue; }
            const auto x=obj.value("x"), y=obj.value("y"), down=obj.value("down");
            if (type!="touch_frame" || !x.isDouble() || !y.isDouble() || !down.isBool() ||
                !qIsFinite(x.toDouble()) || !qIsFinite(y.toDouble()) ||
                x.toDouble()<0 || x.toDouble()>1 || y.toDouble()<0 || y.toDouble()>1 || !window_) {
                reject(); return;
            }
            const bool next=down.toBool();
            if (!armed_) { if (!next) armed_=true; continue; }
            if (!next && !down_) continue;
            const QPointF point(x.toDouble()*(window_->width()-1), y.toDouble()*(window_->height()-1));
            const auto eventType=next ? (down_ ? QEvent::MouseMove : QEvent::MouseButtonPress)
                                      : QEvent::MouseButtonRelease;
            const auto button=eventType==QEvent::MouseMove ? Qt::NoButton : Qt::LeftButton;
            const auto buttons=next ? Qt::LeftButton : Qt::NoButton;
            QMouseEvent event(eventType, point, point, window_->mapToGlobal(point.toPoint()),
                              button, buttons, Qt::NoModifier, Qt::MouseEventSynthesizedByApplication);
            down_=next;
            QCoreApplication::sendEvent(window_, &event);
        }
    }
    QPointer<QQuickWindow> window_;
    QLocalServer server_;
    QPointer<QLocalSocket> socket_;
    QTimer timer_;
    QByteArray buffer_;
    qint64 sequence_=0, lastPacket_=0;
    bool down_=false, armed_=false, listening_=false;
};
