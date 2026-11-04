set root [file normalize [file join [file dirname [info script]] ..]]
if {[llength $argv] != 2} { error "Usage: open_wave.tcl <core|ov5640|ethernet|p_audio> <overview|detail>" }
lassign $argv kind level
set choices [dict create core {core_full_final core_detail} ov5640 {ov_overview ov_detail} ethernet {eth_overview eth_detail} p_audio {audio_pair_final audio_detail}]
if {![dict exists $choices $kind] || $level ni {overview detail}} { error "Unsupported case or view" }
set index [expr {$level eq "detail" ? 1 : 0}]
set config [lindex [dict get $choices $kind] $index]
open_wave_database [file join $root sim results $kind ${kind}.wdb]
open_wave_config [file join $root sim wave_config ${config}.wcfg]
