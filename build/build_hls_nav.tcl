# Rebuild and numerically check the recovered FP32 source; never program hardware.
set root [file normalize [file join [file dirname [info script]] ..]]
if {![info exists ::env(HLS_OUT_NAV)]} {error "Set HLS_OUT_NAV to a fresh directory"}
set output [file normalize $::env(HLS_OUT_NAV)]
if {[file exists [file join $output hls.app]]} {error "Use a fresh output directory"}
open_project $output
set_top keypoint_conv_f32
add_files [file join $root src hls nav_fp32 keypoint_conv.cpp] -cflags "-std=c++14 -ffp-contract=off"
add_files -tb [file join $root src hls nav_fp32 reference_v1.cpp] -cflags "-std=c++14 -ffp-contract=off"
add_files -tb [file join $root src hls nav_fp32 test_keypoint_conv.cpp] -cflags "-std=c++14 -ffp-contract=off"
open_solution solution -flow_target vivado
set_part xc7z020clg400-2
create_clock -period 10.000 -name default
config_compile -pipeline_loops 0
config_interface -m_axi_addr64=true
set fixtures [file join $output solution csim build fixtures]
file mkdir $fixtures
foreach id {000 018 046} {
 file copy -force [file join $root data test_inputs nav_fp32 case_${id}.bin] $fixtures
}
csim_design -argv "--smoke"
csynth_design
exit
