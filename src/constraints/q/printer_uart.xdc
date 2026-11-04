# J3 pin 2 = M15 TX and pin 4 = L16 RX, verified Phosphor 7020 mapping.
# FPGA 3.3-V UART logic only: external MAX3232 required for RS232 voltage levels.
set_property -dict {PACKAGE_PIN M15 IOSTANDARD LVCMOS33 DRIVE 8 SLEW SLOW} [get_ports printer_uart_tx]
set_property -dict {PACKAGE_PIN L16 IOSTANDARD LVCMOS33 PULLUP TRUE} [get_ports printer_uart_rx]
# UART has no external synchronous clock. Constrain only the asynchronous I/O
# paths; internal sampling pipeline and AXI paths retain their normal timing.
set_false_path -from [get_ports printer_uart_rx]
set_false_path -to [get_ports printer_uart_tx]
