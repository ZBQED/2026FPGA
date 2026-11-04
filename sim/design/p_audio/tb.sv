`timescale 1ns/1ps
module tb;
reg clk=0;always #5 clk=~clk;reg resetn=0;
wire bclk,lrclk,sdata;reg[4:0]wr_ce=0,rd_ce=0;reg[31:0]bus_data=0;wire[31:0]bus_result;wire rd_ack,wr_ack,bus_error;
user_logic #(.C_NUM_REG(5),.C_SLV_DWIDTH(32)) dut(.BCLK(bclk),.LRCLK(lrclk),.SDATA_I(sdata),.SDATA_O(sdata),.Bus2IP_Clk(clk),.Bus2IP_Resetn(resetn),.Bus2IP_Data(bus_data),.Bus2IP_BE(4'hf),.Bus2IP_RdCE(rd_ce),.Bus2IP_WrCE(wr_ce),.IP2Bus_Data(bus_result),.IP2Bus_RdAck(rd_ack),.IP2Bus_WrAck(wr_ack),.IP2Bus_Error(bus_error));
reg[23:0]ref_left=0,ref_right=0,rx_left=0,rx_right=0,serial_last=0,shift=0;
reg armed=0,prev_lr=1,passed=0;integer bit_index=0,serial_checked=0,received=0,case_id=0;reg[31:0]status_word,read_word;
function[23:0]pattern(input integer id);
 case(id)
  0:pattern=24'h123456;1:pattern=24'h800000;2:pattern=24'h7fffff;3:pattern=24'hffffff;
  4:pattern=24'h000000;5:pattern=24'ha5a55a;6:pattern=24'h000001;default:pattern=24'hfedcba;
 endcase
endfunction
task wr(input integer idx,input[31:0]value);
 begin @(negedge clk);wr_ce=5'b10000>>idx;bus_data=value;@(posedge clk);#1;if(!wr_ack||bus_error)$fatal(1,"P_AUDIO_WRITE_ACK");@(negedge clk);wr_ce=0;end
endtask
task rd(input integer idx,output[31:0]value);
 begin @(negedge clk);rd_ce=5'b10000>>idx;@(posedge clk);#1;if(!rd_ack||bus_error)$fatal(1,"P_AUDIO_READ_ACK");value=bus_result;@(negedge clk);rd_ce=0;end
endtask
always @(posedge bclk)begin
 #1;
 if(lrclk!=prev_lr)begin prev_lr=lrclk;bit_index=0;shift=0;end
 else if(bit_index<24)begin
  shift={shift[22:0],sdata};bit_index=bit_index+1;
  if(bit_index==24&&armed)begin
   if(shift!==(lrclk?ref_right:ref_left))$fatal(1,"P_AUDIO_SERIAL_MISMATCH lr=%b got=%h L=%h R=%h",lrclk,shift,ref_left,ref_right);
   serial_last=shift;serial_checked=serial_checked+1;
  end
 end
end
initial begin
 #500;@(negedge clk);resetn=1;
 for(case_id=0;case_id<8;case_id=case_id+1)begin
  @(posedge lrclk);wr(2,{8'b0,pattern(case_id)});wr(3,{8'b0,pattern(7-case_id)});
  @(negedge lrclk);ref_left=pattern(case_id);ref_right=pattern(7-case_id);armed=1;wr(4,0);
  status_word=0;
  while(!status_word[0])begin #200;rd(4,status_word);end
  rd(0,read_word);rx_left=read_word[23:0];if(read_word!=={8'b0,ref_left})$fatal(1,"P_AUDIO_LEFT_MISMATCH");
  rd(1,read_word);rx_right=read_word[23:0];if(read_word!=={8'b0,ref_right})$fatal(1,"P_AUDIO_RIGHT_MISMATCH");
  received=received+2;armed=0;
  if(serial_checked!=received)$fatal(1,"P_AUDIO_SERIAL_COUNT");
  wr(4,0);rd(4,status_word);if(status_word[0])$fatal(1,"P_AUDIO_READY_CLEAR");
  $display("P_AUDIO_PAIR_PASS case=%0d L=%h R=%h samples=%0d",case_id,rx_left,rx_right,received);
 end
 passed=1;$display("P_AUDIO_RTL_PASS stereo_pairs=8 rx_samples=16 independently_decoded=16 ready_clear_checks=8");#500;$finish;
end
initial begin #400000;$fatal(1,"P_AUDIO_TIMEOUT case=%0d",case_id);end
endmodule
