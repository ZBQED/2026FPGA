# Correct stale static analysis to the clock actually running on the board.
# This file never changes PS7 configuration or hardware clock registers.
set v11_clock [get_clocks clk_fpga_0]
set v11_sources [get_property SOURCE_PINS $v11_clock]
create_clock -name clk_fpga_0 -period 6.667 -waveform {0 3.334} [get_pins $v11_sources]
