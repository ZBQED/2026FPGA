#pragma once
#include <cstdint>

// Triple buffering keeps readers off the slot currently being captured.
// Each slot has a sequence lock; sequence publishes the latest completed slot.
struct CameraFrameHeader {
    std::uint32_t magic;
    std::uint32_t sequence;
    std::uint32_t width;
    std::uint32_t height;
    std::uint32_t stride;
    std::uint32_t slotSequence[3];
    std::uint32_t reserved[8];
};
constexpr std::uint32_t CameraFrameMagic = 0x4d43414d;
constexpr unsigned CameraWidth = 800, CameraHeight = 480;
constexpr unsigned CameraBytes = CameraWidth * CameraHeight * 3;
constexpr unsigned CameraMapBytes = sizeof(CameraFrameHeader) + CameraBytes * 3;
