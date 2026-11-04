// No transaction can occur: all VALID outputs are permanently low.
// Preserve enabled PS AXI3 HP port configuration while removing video masters.
module axi3_idle(
 (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK", X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF M_AXI" *) input wire aclk,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI AWID", X_INTERFACE_PARAMETER = "PROTOCOL AXI3, DATA_WIDTH 64, ADDR_WIDTH 32, ID_WIDTH 6, HAS_BURST 1, HAS_LOCK 1, HAS_CACHE 1, HAS_PROT 1, HAS_QOS 1, SUPPORTS_NARROW_BURST 1" *)
 output wire [5:0] m_axi_awid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI AWADDR" *)
 output wire [31:0] m_axi_awaddr,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI AWLEN" *)
 output wire [3:0] m_axi_awlen,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI AWSIZE" *)
 output wire [2:0] m_axi_awsize,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI AWBURST" *)
 output wire [1:0] m_axi_awburst,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI AWLOCK" *)
 output wire [1:0] m_axi_awlock,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI AWCACHE" *)
 output wire [3:0] m_axi_awcache,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI AWPROT" *)
 output wire [2:0] m_axi_awprot,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI AWQOS" *)
 output wire [3:0] m_axi_awqos,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI AWVALID" *)
 output wire m_axi_awvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI AWREADY" *)
 input wire m_axi_awready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI ARID" *)
 output wire [5:0] m_axi_arid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI ARADDR" *)
 output wire [31:0] m_axi_araddr,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI ARLEN" *)
 output wire [3:0] m_axi_arlen,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI ARSIZE" *)
 output wire [2:0] m_axi_arsize,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI ARBURST" *)
 output wire [1:0] m_axi_arburst,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI ARLOCK" *)
 output wire [1:0] m_axi_arlock,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI ARCACHE" *)
 output wire [3:0] m_axi_arcache,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI ARPROT" *)
 output wire [2:0] m_axi_arprot,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI ARQOS" *)
 output wire [3:0] m_axi_arqos,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI ARVALID" *)
 output wire m_axi_arvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI ARREADY" *)
 input wire m_axi_arready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI WID" *)
 output wire [5:0] m_axi_wid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI WDATA" *)
 output wire [63:0] m_axi_wdata,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI WSTRB" *)
 output wire [7:0] m_axi_wstrb,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI WLAST" *)
 output wire m_axi_wlast,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI WVALID" *)
 output wire m_axi_wvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI WREADY" *)
 input wire m_axi_wready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI BID" *)
 input wire [5:0] m_axi_bid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI BRESP" *)
 input wire [1:0] m_axi_bresp,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI BVALID" *)
 input wire m_axi_bvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI BREADY" *)
 output wire m_axi_bready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI RID" *)
 input wire [5:0] m_axi_rid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI RDATA" *)
 input wire [63:0] m_axi_rdata,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI RRESP" *)
 input wire [1:0] m_axi_rresp,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI RLAST" *)
 input wire m_axi_rlast,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI RVALID" *)
 input wire m_axi_rvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI RREADY" *)
 output wire m_axi_rready
);
 assign m_axi_awid = 6'b0;
 assign m_axi_awaddr = 32'b0;
 assign m_axi_awlen = 4'b0;
 assign m_axi_awsize = 3'b0;
 assign m_axi_awburst = 2'b0;
 assign m_axi_awlock = 2'b0;
 assign m_axi_awcache = 4'b0;
 assign m_axi_awprot = 3'b0;
 assign m_axi_awqos = 4'b0;
 assign m_axi_awvalid = 1'b0;
 assign m_axi_arid = 6'b0;
 assign m_axi_araddr = 32'b0;
 assign m_axi_arlen = 4'b0;
 assign m_axi_arsize = 3'b0;
 assign m_axi_arburst = 2'b0;
 assign m_axi_arlock = 2'b0;
 assign m_axi_arcache = 4'b0;
 assign m_axi_arprot = 3'b0;
 assign m_axi_arqos = 4'b0;
 assign m_axi_arvalid = 1'b0;
 assign m_axi_wid = 6'b0;
 assign m_axi_wdata = 64'b0;
 assign m_axi_wstrb = 8'b0;
 assign m_axi_wlast = 1'b0;
 assign m_axi_wvalid = 1'b0;
 assign m_axi_bready = 1'b0;
 assign m_axi_rready = 1'b0;
endmodule
