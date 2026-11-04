// Linux V4L2 capture shared by patient preview and A's unchanged SG receiver.
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <QCoreApplication>
#include <QImage>
#include <QSaveFile>
#include <QDir>
#include "src/cameraframe.h"
#include "src/cameracapturetiming.h"
#include <time.h>
#include <arpa/inet.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/uio.h>
#include <unistd.h>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <vector>
#include <chrono>
#include <atomic>
#include <thread>
#include <algorithm>

static int checked(int fd, unsigned long request, void *arg) {
    int rc;
    do { rc = ioctl(fd, request, arg); } while (rc < 0 && errno == EINTR);
    if (rc < 0) { std::perror("V4L2 ioctl"); std::exit(1); }
    return rc;
}
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    int fd = open("/dev/video0", O_RDWR | O_NONBLOCK);
    if (fd < 0) { std::perror("camera open"); return 1; }
    v4l2_format fmt{};
    fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
    fmt.fmt.pix_mp.width = 800;
    fmt.fmt.pix_mp.height = 480;
    fmt.fmt.pix_mp.pixelformat = V4L2_PIX_FMT_BGR24;
    fmt.fmt.pix_mp.field = V4L2_FIELD_NONE;
    checked(fd, VIDIOC_S_FMT, &fmt);
    const unsigned width = fmt.fmt.pix_mp.width, height = fmt.fmt.pix_mp.height;
    const unsigned stride = fmt.fmt.pix_mp.plane_fmt[0].bytesperline;
    if (fmt.fmt.pix_mp.pixelformat != V4L2_PIX_FMT_BGR24 || width != 800 || height != 480 || stride < width * 3) {
        std::fprintf(stderr, "Unsupported camera format %ux%u fourcc=%08x stride=%u\n", width, height, fmt.fmt.pix_mp.pixelformat, stride);
        return 1;
    }
    v4l2_requestbuffers req{};
    req.count = 3; req.type = fmt.type; req.memory = V4L2_MEMORY_MMAP;
    checked(fd, VIDIOC_REQBUFS, &req);
    if (req.count < 2) return 1;
    struct Buffer { void *data; size_t size; };
    std::vector<Buffer> buffers(req.count);
    for (unsigned i = 0; i < req.count; ++i) {
        v4l2_plane plane{}; v4l2_buffer b{};
        b.type = fmt.type; b.memory = V4L2_MEMORY_MMAP; b.index = i;
        b.length = 1; b.m.planes = &plane;
        checked(fd, VIDIOC_QUERYBUF, &b);
        buffers[i] = {mmap(nullptr, plane.length, PROT_READ | PROT_WRITE, MAP_SHARED, fd, plane.m.mem_offset), plane.length};
        if (buffers[i].data == MAP_FAILED) { std::perror("camera mmap"); return 1; }
        checked(fd, VIDIOC_QBUF, &b);
    }
    int type = fmt.type; checked(fd, VIDIOC_STREAMON, &type);
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) { std::perror("camera UDP socket"); return 1; }
    sockaddr_in target{}; target.sin_family = AF_INET; target.sin_port = htons(5003);
    inet_pton(AF_INET, qgetenv("MEDCOMM_PC_IP").isEmpty() ? "192.168.1.100" : qgetenv("MEDCOMM_PC_IP").constData(), &target.sin_addr);
    QDir().mkpath("/run/medcomm");
    int previewFd = open("/run/medcomm/camera.frame", O_RDWR | O_CREAT, 0600);
    if (previewFd < 0 || ftruncate(previewFd, CameraMapBytes) < 0) { std::perror("preview file"); return 1; }
    void *previewMap = mmap(nullptr, CameraMapBytes, PROT_READ | PROT_WRITE, MAP_SHARED, previewFd, 0);
    if (previewMap == MAP_FAILED) { std::perror("preview mmap"); return 1; }
    auto *previewHeader = static_cast<CameraFrameHeader *>(previewMap);
    unsigned previewSequence = __atomic_load_n(&previewHeader->sequence, __ATOMIC_RELAXED);
    int timingFd = open("/run/medcomm/camera.timing", O_RDWR | O_CREAT, 0600);
    if (timingFd < 0 || ftruncate(timingFd, sizeof(CameraTimingMap)) < 0) { std::perror("camera timing file"); return 1; }
    auto *timingMap = static_cast<CameraTimingMap *>(mmap(nullptr, sizeof(CameraTimingMap), PROT_READ | PROT_WRITE, MAP_SHARED, timingFd, 0));
    if (timingMap == MAP_FAILED) { std::perror("camera timing mmap"); return 1; }
    std::memset(timingMap, 0, sizeof(*timingMap));
    timingMap->magic = CameraTimingMagic; timingMap->version = 1; timingMap->bytes = sizeof(*timingMap);
    std::uint32_t lastTimingFlags = ~0u, lastTimingKind = 0;
    const unsigned streamWidth = qgetenv("MEDCOMM_STREAM_WIDTH") == "400" ? 400 : 800;
    const unsigned streamHeight = streamWidth * 3 / 5;
    const unsigned streamFps = qgetenv("MEDCOMM_STREAM_FPS") == "10" ? 10 : 20;
    const auto streamPeriod = std::chrono::milliseconds(1000 / streamFps);
    auto statsTime = std::chrono::steady_clock::now();
    std::atomic<unsigned> captures{0}, networkFrames{0}, copyMisses{0};
    std::atomic<bool> networkRunning{true};
    previewHeader->magic = CameraFrameMagic;
    previewHeader->width = width; previewHeader->height = height; previewHeader->stride = width * 3;
    std::fprintf(stderr, "CAMERA_STREAMING %ux%u BGR24 stride=%u buffers=%u\n", width, height, stride, req.count);
    std::fprintf(stderr, "CAMERA_NETWORK %ux%u target_fps=%u batch=32\n", streamWidth, streamHeight, streamFps);
    std::fflush(stderr);
    // Packet pacing, Ethernet congestion and diagnostic BMP writes must never
    // hold a camera buffer or delay publishing the next local preview frame.
    // The sender takes only the newest completed slot; there is no frame queue.
    const unsigned initialSequence = previewSequence;
    std::thread networkThread([&]() {
        std::vector<unsigned char> raw(streamWidth * streamHeight * 3);
        constexpr unsigned batchPackets = 32;
        unsigned char headers[batchPackets][18]{};
        iovec vectors[batchPackets][2]{};
        mmsghdr messages[batchPackets]{};
        for (unsigned i = 0; i < batchPackets; ++i) {
            headers[i][0] = 'S'; headers[i][1] = 'G'; headers[i][2] = 1; headers[i][3] = 1;
            vectors[i][0].iov_base = headers[i];
            vectors[i][0].iov_len = sizeof(headers[i]);
            messages[i].msg_hdr.msg_name = &target;
            messages[i].msg_hdr.msg_namelen = sizeof(target);
            messages[i].msg_hdr.msg_iov = vectors[i];
            messages[i].msg_hdr.msg_iovlen = 2;
        }
        unsigned frameId = 0, lastSequence = initialSequence;
        auto nextSend = std::chrono::steady_clock::now();
        auto nextUdpError = nextSend;
        auto nextDiagnostic = nextSend;
        auto nextModeCheck = nextSend;
        bool sendUdp = true;
        bool modeReported = false;
        while (networkRunning.load(std::memory_order_relaxed)) {
            std::this_thread::sleep_until(nextSend);
            if (!networkRunning.load(std::memory_order_relaxed)) break;
            const auto now = std::chrono::steady_clock::now();
            if (now >= nextModeCheck) {
                const bool enabled = qgetenv("MEDCOMM_NETWORK_STREAM") != "0" &&
                    access("/etc/medcomm/camera-local-only", F_OK) != 0;
                if (enabled != sendUdp || !modeReported) {
                    std::fprintf(stderr, "CAMERA_OUTPUT_MODE udp=%d local_preview=1 diagnostic_fps=1\n", int(enabled));
                    std::fflush(stderr);
                    modeReported = true;
                }
                sendUdp = enabled;
                nextModeCheck = now + std::chrono::seconds(1);
            }
            // Missed deadlines are discarded, never replayed in a burst.
            do { nextSend += streamPeriod; } while (nextSend <= now);
            // On-board inference reads the local shared frames, so it does not
            // require a second raw-video stream to the PC. Keep only a 1 Hz
            // diagnostic snapshot when the explicitly selected mode is local.
            if (!sendUdp && now < nextDiagnostic) continue;
            const unsigned sequence = __atomic_load_n(&previewHeader->sequence, __ATOMIC_ACQUIRE);
            if (!sequence || sequence == lastSequence) continue;
            const unsigned slot = sequence % 3;
            const unsigned before = __atomic_load_n(&previewHeader->slotSequence[slot], __ATOMIC_ACQUIRE);
            if (before != sequence * 2) { ++copyMisses; continue; }
            const auto *pixels = reinterpret_cast<const unsigned char *>(previewHeader + 1) + slot * CameraBytes;
            if (streamWidth == width) std::memcpy(raw.data(), pixels, raw.size());
            else for (unsigned y = 0; y < streamHeight; ++y)
                for (unsigned x = 0; x < streamWidth; ++x)
                    std::memcpy(&raw[(y * streamWidth + x) * 3], pixels + y * 2 * width * 3 + x * 6, 3);
            __atomic_thread_fence(__ATOMIC_ACQUIRE);
            if (before != __atomic_load_n(&previewHeader->slotSequence[slot], __ATOMIC_ACQUIRE)) {
                ++copyMisses;
                continue;
            }
            lastSequence = sequence;
            ++frameId;
            const unsigned total = (raw.size() + 1399) / 1400;
            bool complete = true;
            const uint32_t id = htonl(frameId);
            // Gather header + existing payload in the kernel, and amortize
            // syscall overhead across 32 unchanged SG datagrams. There is no
            // per-packet payload copy or scheduler sleep between batches.
            for (unsigned first = 0; sendUdp && first < total && complete; first += batchPackets) {
                const unsigned count = std::min(batchPackets, total - first);
                for (unsigned j = 0; j < count; ++j) {
                    const unsigned index = first + j;
                    const unsigned n = std::min<unsigned>(1400, raw.size() - index * 1400);
                    const uint16_t fields[] = {htons(index), htons(total), htons(streamWidth), htons(streamHeight), htons(n)};
                    std::memcpy(headers[j] + 4, &id, sizeof(id));
                    std::memcpy(headers[j] + 8, fields, sizeof(fields));
                    vectors[j][1].iov_base = raw.data() + index * 1400;
                    vectors[j][1].iov_len = n;
                    messages[j].msg_len = 0;
                }
                unsigned sent = 0;
                while (sent < count) {
                    if (!networkRunning.load(std::memory_order_relaxed)) { complete = false; break; }
                    const int result = sendmmsg(sock, messages + sent, count - sent, 0);
                    if (result > 0) {
                        // A partial success consumed exactly this prefix; send
                        // only the remaining datagrams, never duplicate it.
                        sent += static_cast<unsigned>(result);
                        continue;
                    }
                    if (result < 0 && errno == EINTR) continue;
                    const int error = result < 0 ? errno : EIO;
                    const auto failedAt = std::chrono::steady_clock::now();
                    if (failedAt >= nextUdpError) {
                        std::fprintf(stderr, "CAMERA_UDP_ERROR frame=%u packet=%u: %s\n", frameId, first + sent, std::strerror(error));
                        std::fflush(stderr);
                        nextUdpError = failedAt + std::chrono::seconds(2);
                    }
                    // Discard the rest of a damaged frame; next iteration takes
                    // a fresh camera snapshot instead of queuing a retry.
                    complete = false;
                    break;
                }
            }
            if (sendUdp && complete) ++networkFrames;
            if (now >= nextDiagnostic) {
                QImage image(raw.data(), streamWidth, streamHeight, streamWidth * 3, QImage::Format_RGB888);
                QSaveFile out("/run/medcomm/camera.bmp");
                if (out.open(QIODevice::WriteOnly) && image.rgbSwapped().save(&out, "BMP")) out.commit();
                nextDiagnostic = now + std::chrono::seconds(1);
            }
            if (frameId == 1 || frameId % 100 == 0) { std::fprintf(stderr, "CAMERA_FRAME %u\n", frameId); std::fflush(stderr); }
        }
    });
    int captureExit = 0;
    for (;;) {
        fd_set ready; FD_ZERO(&ready); FD_SET(fd, &ready); timeval tv{3, 0};
        if (select(fd + 1, &ready, nullptr, nullptr, &tv) <= 0) { std::fprintf(stderr, "CAMERA_NO_FRAMES\n"); captureExit = 2; break; }
        v4l2_plane plane{}; v4l2_buffer b{};
        b.type = fmt.type; b.memory = V4L2_MEMORY_MMAP; b.length = 1; b.m.planes = &plane;
        if (ioctl(fd, VIDIOC_DQBUF, &b) < 0) { if (errno == EAGAIN || errno == EINTR) continue; std::perror("camera dequeue"); captureExit = 1; break; }
        if (b.index >= buffers.size() || plane.data_offset + stride * height > buffers[b.index].size) { captureExit = 1; break; }
        const auto now = std::chrono::steady_clock::now();
        timespec dequeued{};
        clock_gettime(CLOCK_MONOTONIC, &dequeued);
        const std::uint64_t dequeueNs = std::uint64_t(dequeued.tv_sec) * 1000000000ull + dequeued.tv_nsec;
        const bool validTimeval = b.timestamp.tv_sec >= 0 && b.timestamp.tv_usec >= 0 && b.timestamp.tv_usec < 1000000;
        const std::uint64_t driverNs = validTimeval
            ? std::uint64_t(b.timestamp.tv_sec) * 1000000000ull + std::uint64_t(b.timestamp.tv_usec) * 1000ull : 0;
        // EOF is encoded as zero: compare the masked value, never test it as a bit.
        const bool monotonic = (b.flags & V4L2_BUF_FLAG_TIMESTAMP_MASK) == V4L2_BUF_FLAG_TIMESTAMP_MONOTONIC;
        const bool eof = (b.flags & V4L2_BUF_FLAG_TSTAMP_SRC_MASK) == V4L2_BUF_FLAG_TSTAMP_SRC_EOF;
        const unsigned reason = !monotonic ? 1 : !eof ? 2 : !driverNs ? 3 : driverNs > dequeueNs ? 4 : 0;
        const std::uint32_t timestampKind = reason ? CameraTimingTIM8 : CameraTimingTIM9;
        const std::uint64_t capturedNs = reason ? dequeueNs : driverNs;
        const auto *src = static_cast<unsigned char *>(buffers[b.index].data) + plane.data_offset;
        ++previewSequence;
        if (!previewSequence) ++previewSequence;
        const unsigned slot = previewSequence % 3;
        __atomic_store_n(&previewHeader->slotSequence[slot], previewSequence * 2 + 1, __ATOMIC_SEQ_CST);
        // Protected by this slot's existing sequence lock; header stays 64 bytes.
        previewHeader->reserved[slot * 2] = std::uint32_t(capturedNs);
        previewHeader->reserved[slot * 2 + 1] = std::uint32_t(std::uint64_t(capturedNs) >> 32);
        auto *pixels = reinterpret_cast<unsigned char *>(previewHeader + 1) + slot * CameraBytes;
        for (unsigned y = 0; y < height; ++y)
            std::memcpy(pixels + y * width * 3, src + y * stride, width * 3);
        __atomic_store_n(&previewHeader->slotSequence[slot], previewSequence * 2, __ATOMIC_RELEASE);
        auto &timing = timingMap->entries[slot];
        __atomic_store_n(&timing.guard, previewSequence * 2 + 1, __ATOMIC_SEQ_CST);
        timing.previewSequence = previewSequence; timing.driverSequence = b.sequence;
        timing.flags = b.flags; timing.timestampKind = timestampKind; timing.selectionReason = reason;
        timing.dequeueObservedNs = dequeueNs; timing.driverTimestampNs = driverNs; timing.captureSelectedNs = capturedNs;
        __atomic_store_n(&timing.guard, previewSequence * 2, __ATOMIC_RELEASE);
        __atomic_store_n(&timingMap->latestSequence, previewSequence, __ATOMIC_RELEASE);
        __atomic_store_n(&previewHeader->reserved[6], timestampKind, __ATOMIC_RELAXED);
        if (lastTimingFlags != b.flags || lastTimingKind != timestampKind) {
            std::fprintf(stderr, "CAMERA_TIMESTAMP flags=0x%08x driver_sequence=%u kind=TIM%u reason=%u driver_to_dq_us=%lld\n",
                         b.flags, b.sequence, reason ? 8u : 9u, reason,
                         driverNs && driverNs <= dequeueNs ? static_cast<long long>((dequeueNs-driverNs)/1000) : -1ll);
            std::fflush(stderr); lastTimingFlags = b.flags; lastTimingKind = timestampKind;
        }
        __atomic_store_n(&previewHeader->reserved[7], previewSequence, __ATOMIC_RELEASE);
        __atomic_store_n(&previewHeader->sequence, previewSequence, __ATOMIC_RELEASE);
        // Release the V4L2 buffer immediately; network/BMP reads use the stable,
        // cached preview copy, never a buffer the camera is filling again.
        checked(fd, VIDIOC_QBUF, &b);
        const unsigned captureCount = ++captures;
        if (captureCount % 15 == 1) futimens(previewFd, nullptr);
        if (now - statsTime >= std::chrono::seconds(5)) {
            const double seconds = std::chrono::duration<double>(now - statsTime).count();
            std::fprintf(stderr, "CAMERA_FPS capture=%.2f network=%.2f copy_miss=%u\n",
                         captures.exchange(0) / seconds, networkFrames.exchange(0) / seconds, copyMisses.exchange(0));
            std::fflush(stderr);
            statsTime = now;
        }
    }
    networkRunning.store(false, std::memory_order_relaxed);
    networkThread.join();
    close(sock);
    return captureExit;
}
