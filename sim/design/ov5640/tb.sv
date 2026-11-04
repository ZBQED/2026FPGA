`timescale 1ns/1ps
module tb;
reg cam_pclk=0; always #20 cam_pclk=~cam_pclk;
reg rst_n=0,cam_vsync=0,cam_href=0;reg[7:0]cam_data=0;
wire cam_rst_n,cam_pwdn,cmos_frame_clk,cmos_frame_ce,data_ready,cmos_frame_vsync,cmos_active_video;
wire[23:0]cmos_frame_data;
ov5640_capture_data dut(.*);
reg[23:0]expected[0:71];integer sent=0,received=0,frame_id=0,row_id=0,pixel=0;
reg[15:0]rgb565;reg passed=0;
always @(posedge cam_pclk) if(data_ready&&cmos_frame_ce&&cmos_active_video)begin
 if(received>=sent||cmos_frame_data!==expected[received])$fatal(1,"PIXEL_MISMATCH n=%0d got=%h expected=%h",received,cmos_frame_data,expected[received]);
 received=received+1;
end
initial begin
 repeat(5)@(negedge cam_pclk);rst_n=1;repeat(5)@(negedge cam_pclk);
 for(frame_id=0;frame_id<13;frame_id=frame_id+1)begin
  cam_vsync=1;repeat(4)@(negedge cam_pclk);cam_vsync=0;repeat(4)@(negedge cam_pclk);
  if(data_ready!==(frame_id>=10))$fatal(1,"WAIT_FRAME_WRONG frame=%0d ready=%b",frame_id,data_ready);
  for(row_id=0;row_id<3;row_id=row_id+1)begin
   for(pixel=0;pixel<8;pixel=pixel+1)begin
    rgb565=16'h2104^(frame_id*97+row_id*1024+pixel*157);
    if(frame_id>=10)begin expected[sent]={rgb565[15:11],3'b0,rgb565[10:5],2'b0,rgb565[4:0],3'b0};sent=sent+1;end
    cam_href=1;cam_data=rgb565[15:8];@(negedge cam_pclk);cam_data=rgb565[7:0];@(negedge cam_pclk);
   end
   cam_href=0;cam_data=0;repeat(6)@(negedge cam_pclk);
  end
  repeat(6)@(negedge cam_pclk);
 end
 if(sent!=72||received!=72||!cam_rst_n||cam_pwdn)$fatal(1,"COUNT_OR_PIN_FAILURE %0d %0d",sent,received);
 @(negedge cam_pclk);#7;rst_n=0;#1;
 if(dut.rst_n_d0!==0||dut.rst_n_syn!==0||data_ready!==0)$fatal(1,"ASYNC_RESET_ASSERTION");
 #5;rst_n=1;
 @(posedge cam_pclk);#1;if(dut.rst_n_syn!==0||dut.rst_n_d0!==1)$fatal(1,"RESET_RELEASE_FIRST_STAGE");
 @(posedge cam_pclk);#1;if(dut.rst_n_syn!==1||data_ready!==0)$fatal(1,"RESET_RELEASE_SECOND_STAGE");
 passed=1;$display("OV5640_RTL_PASS warmup_frames=10 valid_frames=3 lines=9 pixels=72 rgb565_to_rgb888_exact=1 reset_sync_checked=1");#200;$finish;
end
initial begin #100000;$fatal(1,"TIMEOUT");end
endmodule
