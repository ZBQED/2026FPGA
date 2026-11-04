`timescale 1ns/1ps
module tb;
reg clk=0;always #5 clk=~clk;
reg rst=1,start=0,valid=0,sof=0,eol=0,full_n=1;
reg[23:0] data=0;wire ready,done,idle,ap_ready,write;
wire[23:0] dout;
integer frame=0,sent=0,received=0,cycle=0,stalls=0,paused=0;
reg held=0;reg[25:0] held_data;
system_v_frmbuf_wr_0_0_AXIvideo2MultiPixStream dut(
.ap_clk(clk),.ap_rst(rst),.ap_start(start),.ap_done(done),.ap_continue(1'b1),.ap_idle(idle),.ap_ready(ap_ready),
.s_axis_video_TDATA(data),.s_axis_video_TVALID(valid),.s_axis_video_TREADY(ready),.s_axis_video_TKEEP(3'b111),.s_axis_video_TSTRB(3'b111),
.s_axis_video_TUSER(sof),.s_axis_video_TLAST(eol),.s_axis_video_TID(1'b0),.s_axis_video_TDEST(1'b0),
.img_din(dout),.img_full_n(full_n),.img_write(write),.img_num_data_valid(3'b0),.img_fifo_cap(3'd7),
.Height_val(11'd3),.WidthIn_val(11'd8),.colorFormat_val(3'd0));
function[23:0] pixel(input integer n,input integer f);
begin pixel={8'(f+16),8'(n+32),8'(n*3+7)};end
endfunction
function[23:0] expected(input integer n,input integer f);
reg[23:0] p;begin p=pixel(n,f);expected={p[15:8],p[7:0],p[23:16]};end
endfunction
always @(posedge clk)begin
 cycle=cycle+1;
 if(cycle>10000)$fatal(1,"VIDEO_TIMEOUT");
 if(!rst)begin
  if(held && (!valid||{sof,eol,data}!==held_data))$fatal(1,"INPUT_CHANGED_DURING_STALL");
  held=valid&&!ready;held_data={sof,eol,data};
  if(valid&&!ready)stalls=stalls+1;
  if(valid&&ready)sent=sent+1;
  if(write)begin
   if(!full_n)$fatal(1,"WRITE_WHEN_FULL");
   if(dout!==expected(received,frame))$fatal(1,"PIXEL_MISMATCH f%0d n%0d got%h expected%h",frame,received,dout,expected(received,frame));
   received=received+1;
  end
 end
end
always @(negedge clk)begin
 full_n=(cycle%17<11);if(!full_n)paused=paused+1;
end
initial begin
 repeat(5)@(negedge clk);rst=0;
 for(frame=0;frame<3;frame=frame+1)begin
  sent=0;received=0;start=1;
  for(integer n=0;n<24;n=n+1)begin
   @(negedge clk);valid=1;data=pixel(n,frame);sof=(n==0);eol=(n%8==7);
   do begin @(posedge clk);end while(!ready);
   @(negedge clk);valid=0;sof=0;eol=0;
   if(n==11)repeat(7)@(negedge clk);
  end
  wait(done);@(negedge clk);start=0;
  if(sent!=24||received!=24)$fatal(1,"FRAME_COUNTS");
  $display("VIDEO_FRAME_PASS frame=%0d sent=%0d received=%0d",frame,sent,received);
  repeat(5)@(negedge clk);
 end
 if(stalls==0||paused==0)$fatal(1,"NO_BACKPRESSURE_EXERCISED");
 $display("VIDEO_RTL_PASS frames=3 pixels=72 stalls=%0d downstream_pause_cycles=%0d",stalls,paused);$finish;
end
endmodule
