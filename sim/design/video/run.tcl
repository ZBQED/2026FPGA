log_wave /tb/*
open_vcd video.vcd
log_vcd /tb/*
log_vcd /tb/dut/*
run all
close_vcd
quit
