# vivado -mode batch -source build/create_project.tcl -tclargs q output_directory
set release_root [file normalize [file join [file dirname [info script]] ..]]
if {$argc < 2} {error "Usage: q|p|nav output_directory"}
set target_board [lindex $argv 0]
if {$target_board ni {q p nav}} {error "Unknown board"}
if {[string first 2024.2 [version -short]] != 0} {error "Vivado 2024.2 is required"}
set output_dir [file normalize [lindex $argv 1]]
if {[file exists [file join $output_dir ${target_board}.xpr]]} {error "Use a new output directory"}
set part [expr {$target_board eq "p" ? "xc7z020clg400-1" : "xc7z020clg400-2"}]
create_project $target_board $output_dir -part $part
set_property target_language Verilog [current_project]
set repositories {}
foreach name {conv_i8 audio_codec_ctrl keypoint_conv_f32 gmii2rgmii ov5640_capture_data pwm dvi_transmitter rgb2lcd interfaces} {
 lappend repositories [file join $release_root src rtl ip $name]
}
set_property ip_repo_paths $repositories [current_project]
update_ip_catalog -rebuild
if {$target_board eq "q"} {add_files -norecurse [glob [file join $release_root src rtl q *.v]]}
source -encoding utf-8 [file join $release_root build ${target_board}_bd.tcl]
if {[llength [get_bd_cells -quiet]] == 0} {error "BD was not reconstructed"}
validate_bd_design
save_bd_design
set bd [get_files -quiet *.bd]
if {[llength $bd] != 1} {error "Expected one block design"}
set_property SYNTH_CHECKPOINT_MODE None $bd
generate_target all $bd
add_files -norecurse [make_wrapper -files $bd -top]
set bd_name [file rootname [file tail $bd]]
set_property top ${bd_name}_wrapper [current_fileset]
add_files -fileset constrs_1 -norecurse [glob [file join $release_root src constraints $target_board *.xdc]]
if {$target_board eq "q"} {set_property PROCESSING_ORDER LATE [get_files *fclk0_150mhz.xdc]}
set_property strategy Flow_PerfOptimized_high [get_runs synth_1]
if {$target_board ne "q"} {set_property STEPS.SYNTH_DESIGN.ARGS.NO_LC false [get_runs synth_1]}
set_property strategy Performance_Explore [get_runs impl_1]
set_property STEPS.POST_ROUTE_PHYS_OPT_DESIGN.IS_ENABLED false [get_runs impl_1]
if {$target_board in {q p}} {
 set ram_init [glob [file join $release_root src rtl ip conv_i8 hdl verilog *.mem]]
 add_files -norecurse $ram_init
}
update_compile_order -fileset sources_1
puts "SOURCE_PROJECT_READY board=$target_board file=[get_property DIRECTORY [current_project]]/${target_board}.xpr"
