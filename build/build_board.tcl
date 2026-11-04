# Rebuild one board; do not program it. Outputs remain in the given directory.
source -encoding utf-8 [file join [file dirname [info script]] create_project.tcl]
# An optional routed reference accelerates implementation; synthesis still uses source.
if {$argc >= 3} {
 set reference [file normalize [lindex $argv 2]]
 if {![file isfile $reference]} {error "Incremental reference not found"}
 set_property INCREMENTAL_CHECKPOINT $reference [get_runs impl_1]
}
set_param general.maxThreads 4
launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {error "Synthesis failed"}
launch_runs impl_1 -to_step route_design -jobs 4
wait_on_run impl_1
if {![string match {*route_design Complete*} [get_property STATUS [get_runs impl_1]]]} {error "Routing failed"}
open_run impl_1
update_timing -full
set summary [report_timing_summary -delay_type min_max -report_unconstrained -return_string -file [file join $output_dir timing.rpt]]
report_pulse_width -file [file join $output_dir pulse_width.rpt]
report_cdc -file [file join $output_dir cdc.rpt]
report_utilization -file [file join $output_dir utilization.rpt]
report_drc -file [file join $output_dir drc.rpt]
report_route_status -file [file join $output_dir route.rpt]
foreach delay {max min} {
 set worst [get_timing_paths -delay_type $delay -max_paths 1]
 if {![llength $worst] || [get_property SLACK $worst] < 0} {error "Timing gate failed: $delay"}
}
if {[llength [get_drc_violations -quiet -filter {SEVERITY == Error}]]} {error "DRC gate failed"}
# Setup, hold and pulse width must all pass; positive WNS alone is insufficient.
set values [regexp -inline -line {^\s*(-?[0-9]+\.[0-9]+)\s+(-?[0-9]+\.[0-9]+)\s+([0-9]+)\s+([0-9]+)\s+(-?[0-9]+\.[0-9]+)\s+(-?[0-9]+\.[0-9]+)\s+([0-9]+)\s+([0-9]+)\s+(-?[0-9]+\.[0-9]+)\s+(-?[0-9]+\.[0-9]+)\s+([0-9]+)\s+([0-9]+)\s*$} $summary]
if {[llength $values] != 13} {error "Cannot parse the design timing summary"}
foreach index {1 5 9} {
 if {[lindex $values $index] < 0} {error "Setup/hold/pulse-width slack gate failed"}
}
foreach index {3 7 11} {
 if {[lindex $values $index] != 0} {error "Timing violation endpoint gate failed"}
}
close_design
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
if {![string match {*write_bitstream Complete*} [get_property STATUS [get_runs impl_1]]]} {error "Bitstream generation failed"}
open_run impl_1
set bitfile [file join [get_property DIRECTORY [get_runs impl_1]] ${bd_name}_wrapper.bit]
file copy -force $bitfile [file join $output_dir ${target_board}.bit]
set handoff [file join $output_dir ${target_board}.gen sources_1 bd $bd_name hw_handoff ${bd_name}.hwh]
if {![file isfile $handoff]} {error "Generated HWH missing: $handoff"}
file copy -force $handoff [file join $output_dir ${target_board}.hwh]
write_hw_platform -fixed -include_bit -force -file [file join $output_dir ${target_board}.xsa]
puts "BOARD_BUILD_COMPLETE $target_board"
