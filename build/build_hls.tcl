# Set HLS_OUT to a fresh absolute output directory before invoking Vitis HLS.
set release_root [file normalize [file join [file dirname [info script]] ..]]
if {![info exists ::env(HLS_OUT)]} {error "Set HLS_OUT to a fresh output directory"}
set output_dir [file normalize $::env(HLS_OUT)]
if {[file exists [file join $output_dir hls.app]]} {error "Use a fresh HLS_OUT directory"}
open_project $output_dir
set_top keypoint_conv_i8
add_files [file join $release_root src hls conv_i8 keypoint_conv_i8.cpp] -cflags "-std=c++14"
open_solution solution -flow_target vivado
set_part xc7z020clg400-2
create_clock -period 6.667 -name default
config_compile -pipeline_loops 0
config_interface -m_axi_addr64=true
csynth_design
exit
