log_wave /tb/clk /tb/resetn /tb/case_id /tb/ap_start /tb/weights_done /tb/compute_start /tb/compute_done /tb/writeback_done /tb/ap_done /tb/ap_return /tb/arvalid /tb/arready /tb/araddr /tb/arlen /tb/rvalid /tb/rready /tb/rdata /tb/rlast /tb/awvalid /tb/awready /tb/awaddr /tb/wvalid /tb/wready /tb/wdata /tb/wstrb /tb/wlast /tb/bvalid /tb/bready /tb/read_beats /tb/write_beats /tb/passed
open_vcd core.vcd
log_vcd /tb/clk /tb/resetn /tb/case_id /tb/ap_start /tb/weights_done /tb/compute_start /tb/compute_done /tb/writeback_done /tb/ap_done /tb/ap_return /tb/arvalid /tb/arready /tb/araddr /tb/arlen /tb/rvalid /tb/rready /tb/rdata /tb/rlast /tb/awvalid /tb/awready /tb/awaddr /tb/wvalid /tb/wready /tb/wdata /tb/wstrb /tb/wlast /tb/bvalid /tb/bready /tb/read_beats /tb/write_beats /tb/passed
run all
close_vcd
quit
