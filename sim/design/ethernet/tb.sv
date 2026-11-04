`timescale 1ns/1ps
module tb;
reg idelay_clk=0;always #2.5 idelay_clk=~idelay_clk;
reg rgmii_rxc=0;always #4 rgmii_rxc=~rgmii_rxc;
reg rgmii_rx_ctl=0,gmii_tx_en=0;reg[3:0]rgmii_rxd=0;reg[7:0]gmii_txd=0;
wire gmii_rx_clk,gmii_rx_dv,gmii_rx_er,gmii_tx_clk,rgmii_txc,rgmii_tx_ctl;
wire[7:0]gmii_rxd;wire[3:0]rgmii_txd;
gmii_to_rgmii dut(.*);
reg[7:0]expected[0:103];integer sent=0,received=0,tx_checks=0,frame_id=0,byte_id=0,n=0;
reg passed=0;
always @(posedge gmii_rx_clk)begin
 #1;
 if(gmii_rx_dv)begin
  if(received>=sent||gmii_rxd!==expected[received])$fatal(1,"RX_MISMATCH n=%0d got=%h want=%h",received,gmii_rxd,expected[received]);
  received=received+1;
 end
end
task beat(input bit en,input[7:0]value);
 begin
  gmii_tx_en=en;gmii_txd=value;rgmii_rx_ctl=en;rgmii_rxd=value[3:0];
  if(en)begin expected[sent]=value;sent=sent+1;end
  #3;
  if(rgmii_tx_ctl!==en||rgmii_txd!==value[3:0])$fatal(1,"TX_LOW_NIBBLE");
  #1;rgmii_rxd=value[7:4];#3;
  if(rgmii_tx_ctl!==en||rgmii_txd!==value[7:4])$fatal(1,"TX_HIGH_NIBBLE");
  if(en)tx_checks=tx_checks+1;#1;
 end
endtask
initial begin
 #250;@(negedge rgmii_rxc);#2;
 for(frame_id=0;frame_id<3;frame_id=frame_id+1)begin
  n=(frame_id==0)?8:((frame_id==1)?32:64);
  for(byte_id=0;byte_id<n;byte_id=byte_id+1)beat(1,(byte_id*37)^(frame_id*8'h5a));
  repeat(12)beat(0,0);
 end
 #32;if(sent!=104||received!=104||tx_checks!=104||gmii_rx_er!==0)$fatal(1,"COUNTS %0d %0d %0d",sent,received,tx_checks);
 passed=1;$display("RGMII_RTL_PASS frames=3 rx_bytes=104 tx_bytes=104 ddr_nibbles=208 interpacket_idle_cycles=12");#40;$finish;
end
initial begin #10000;$fatal(1,"TIMEOUT");end
endmodule
