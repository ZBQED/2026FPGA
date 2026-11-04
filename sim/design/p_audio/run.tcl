log_wave /tb/clk /tb/resetn /tb/bclk /tb/lrclk /tb/sdata /tb/wr_ce /tb/rd_ce /tb/bus_data /tb/bus_result /tb/rd_ack /tb/wr_ack /tb/ref_left /tb/ref_right /tb/rx_left /tb/rx_right /tb/serial_last /tb/serial_checked /tb/received /tb/passed
open_vcd p_audio.vcd
log_vcd /tb/clk /tb/resetn /tb/bclk /tb/lrclk /tb/sdata /tb/wr_ce /tb/rd_ce /tb/bus_data /tb/bus_result /tb/rd_ack /tb/wr_ack /tb/ref_left /tb/ref_right /tb/rx_left /tb/rx_right /tb/serial_last /tb/serial_checked /tb/received /tb/passed
run all
close_vcd
quit
