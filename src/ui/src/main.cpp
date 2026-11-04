#include "backend.h"
#include "camerapreview.h"
#include "networktouch.h"

#include <QGuiApplication>
#include <QFont>
#include <QFontDatabase>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QStringList>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#ifdef Q_OS_UNIX
#include <execinfo.h>
#include <unistd.h>
#endif

namespace {
void startupMarker(const char *message)
{
    std::fprintf(stderr, "MEDCOMM_STARTUP:%s\n", message);
    std::fflush(stderr);
}

void crashHandler(int signal)
{
#ifdef Q_OS_UNIX
    void *frames[48];
    const int count = ::backtrace(frames, 48);
    std::fprintf(stderr, "MEDCOMM_CRASH:signal=%d frames=%d\n", signal, count);
    ::backtrace_symbols_fd(frames, count, STDERR_FILENO);
#else
    std::fprintf(stderr, "MEDCOMM_CRASH:signal=%d\n", signal);
#endif
    std::_Exit(128 + signal);
}
}

int main(int argc, char *argv[])
{
    std::signal(SIGSEGV, crashHandler);
#ifdef SIGBUS
    std::signal(SIGBUS, crashHandler);
#endif
    startupMarker("main-enter");
    QCoreApplication::setAttribute(Qt::AA_EnableHighDpiScaling);
    startupMarker("before-qguiapplication");
    QGuiApplication app(argc, argv);
    startupMarker("after-qguiapplication");
    QGuiApplication::setApplicationName(QStringLiteral("医手相通"));
    QGuiApplication::setOrganizationName(QStringLiteral("MedComm"));

    startupMarker("before-qml-engine");
    qmlRegisterType<CameraPreview>("MedComm", 1, 0, "CameraPreview");
    QQmlApplicationEngine engine;
    startupMarker("after-qml-engine");

    startupMarker("before-backend");
    Backend backend;
    startupMarker("after-backend");
    engine.rootContext()->setContextProperty(QStringLiteral("backend"), &backend);
    const bool embeddedMode = app.arguments().contains(QStringLiteral("--embedded"));
    if (embeddedMode) {
        const QString runtimeRoot = qEnvironmentVariable("MEDCOMM_PROJECT_ROOT",
                                                        QString::fromUtf8(MEDCOMM_PROJECT_ROOT));
        const int fontId = QFontDatabase::addApplicationFont(runtimeRoot + QStringLiteral("/fonts/simhei.ttf"));
        const QStringList families = QFontDatabase::applicationFontFamilies(fontId);
        if (!families.isEmpty())
            app.setFont(QFont(families.first()));
    }
    startupMarker(embeddedMode ? "before-load-embedded" : "before-load-desktop");
    engine.load(QUrl(embeddedMode
                         ? (app.arguments().contains(QStringLiteral("--dual"))
                                ? QStringLiteral("qrc:/qml/EmbeddedDualWindow.qml")
                                : QStringLiteral("qrc:/qml/EmbeddedWindow.qml"))
                         : QStringLiteral("qrc:/qml/Main.qml")));
    startupMarker("after-qml-load");
    if (engine.rootObjects().isEmpty())
        return -1;
    // Only the HDMI patient process can receive the explicitly enabled bridge.
    if (embeddedMode && app.arguments().contains(QStringLiteral("--patient")) &&
        !app.arguments().contains(QStringLiteral("--staff"))) {
        const QString path=qEnvironmentVariable("MEDCOMM_TOUCH_SOCKET");
        if (!path.isEmpty()) {
            auto *window=qobject_cast<QQuickWindow *>(engine.rootObjects().first());
            if (!window || !(new NetworkTouch(window,path,&app))->listening()) return -2;
        }
    }
    for (QObject *root : engine.rootObjects()) {
        for (CameraPreview *preview : root->findChildren<CameraPreview *>()) {
            QObject::connect(&backend, &Backend::firstSnapshotApplied,
                             preview, &CameraPreview::noteLiveBackendSnapshot);
            if (backend.hasAppliedSnapshot()) preview->noteLiveBackendSnapshot();
            QObject::connect(&backend, &Backend::snapshotChanged,
                             preview, &CameraPreview::refreshComposition);
            QObject::connect(&backend, &Backend::recognitionChanged,
                             preview, &CameraPreview::refreshComposition);
            QObject::connect(&backend, &Backend::lastGestureChanged,
                             preview, &CameraPreview::refreshComposition);
        }
    }
    startupMarker("before-event-loop");
    return app.exec();
}
