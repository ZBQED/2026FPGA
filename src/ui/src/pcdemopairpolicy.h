#pragma once
#include <cstdint>
namespace pc_demo_pair_policy {
constexpr std::uint64_t SourceFreshNs = 750000000ULL;
constexpr std::uint64_t PairHoldNs = 1000000000ULL;
constexpr std::uint64_t AbsoluteSourceNs = 2000000000ULL;
struct Decision {
    bool drawable = false;
    bool sourceFresh = false;
    bool currentSourceValid = false;
    bool retained = false;
    const char *reason = "NO_AUTHENTICATED_PAIR";
};
inline Decision evaluate(bool authenticatedPair, bool inputReadOk, std::uint64_t capture,
                         std::uint64_t firstRead, std::uint64_t now) {
    Decision d;
    if (!authenticatedPair) return d;
    if (!capture || !firstRead || capture > firstRead || firstRead > now) {
        d.reason = "CLOCK_INVALID"; return d;
    }
    const std::uint64_t sourceAge = now - capture;
    d.sourceFresh = sourceAge <= SourceFreshNs;
    if (sourceAge > AbsoluteSourceNs) {
        d.reason = "SOURCE_ABSOLUTE_EXPIRED"; return d;
    }
    if (now - firstRead > PairHoldNs) {
        d.reason = "PAIR_HOLD_EXPIRED"; return d;
    }
    d.drawable = true;
    d.currentSourceValid = inputReadOk && d.sourceFresh;
    d.retained = !d.currentSourceValid;
    d.reason = d.currentSourceValid ? "CURRENT_SOURCE" :
               !inputReadOk ? "RETAINED_READ_FAILURE" : "RETAINED_SOURCE_AGE";
    return d;
}
}
