# TEMPLATE: intended routed design must already be open in Vivado.
# Before source: set skill_report_dir ./reports_run
# Does not build or program hardware. Choose a NEW output directory.
if {![info exists skill_report_dir]} { error "Set skill_report_dir explicitly" }
if {[file exists $skill_report_dir]} { error "Choose a new report directory" }
if {[current_design -quiet] eq ""} { error "Open the intended routed design first" }
file mkdir $skill_report_dir
report_utilization -file [file join $skill_report_dir utilization.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $skill_report_dir timing.rpt]
report_drc -file [file join $skill_report_dir drc.rpt]
report_route_status -file [file join $skill_report_dir route_status.rpt]
puts "Review DRC, route status, constraints and build provenance separately."
