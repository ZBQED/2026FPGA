`timescale 1ns/1ps
module tb;
reg clk=0;always #3.333 clk=~clk;reg resetn=0;
wire arvalid,rready,awvalid,wvalid,wlast,bready;wire[63:0]araddr,awaddr,wdata;wire[7:0]arlen,awlen,wstrb;wire[2:0]arsize,awsize;wire arid,awid;
reg arready=0,rvalid=0,rlast=0,awready=0,wready=0,bvalid=0;reg[63:0]rdata=0;
reg ctrl_av=0,ctrl_wv=0;reg[6:0]ctrl_addr=0;reg[31:0]ctrl_data=0;wire ctrl_ar,ctrl_wr,ctrl_bv;wire[1:0]ctrl_br;
keypoint_conv_i8 dut(
 .ap_clk(clk),.ap_rst_n(resetn),
 .m_axi_gmem_ARVALID(arvalid),.m_axi_gmem_ARREADY(arready),.m_axi_gmem_ARADDR(araddr),.m_axi_gmem_ARLEN(arlen),.m_axi_gmem_ARSIZE(arsize),.m_axi_gmem_ARID(arid),
 .m_axi_gmem_RVALID(rvalid),.m_axi_gmem_RREADY(rready),.m_axi_gmem_RDATA(rdata),.m_axi_gmem_RLAST(rlast),.m_axi_gmem_RID(1'b0),.m_axi_gmem_RUSER(1'b0),.m_axi_gmem_RRESP(2'b0),
 .m_axi_gmem_AWVALID(awvalid),.m_axi_gmem_AWREADY(awready),.m_axi_gmem_AWADDR(awaddr),.m_axi_gmem_AWLEN(awlen),.m_axi_gmem_AWSIZE(awsize),.m_axi_gmem_AWID(awid),
 .m_axi_gmem_WVALID(wvalid),.m_axi_gmem_WREADY(wready),.m_axi_gmem_WDATA(wdata),.m_axi_gmem_WSTRB(wstrb),.m_axi_gmem_WLAST(wlast),
 .m_axi_gmem_BVALID(bvalid),.m_axi_gmem_BREADY(bready),.m_axi_gmem_BRESP(2'b0),.m_axi_gmem_BID(1'b0),.m_axi_gmem_BUSER(1'b0),
 .s_axi_control_AWVALID(ctrl_av),.s_axi_control_AWREADY(ctrl_ar),.s_axi_control_AWADDR(ctrl_addr),.s_axi_control_WVALID(ctrl_wv),.s_axi_control_WREADY(ctrl_wr),.s_axi_control_WDATA(ctrl_data),.s_axi_control_WSTRB(4'hf),
 .s_axi_control_ARVALID(1'b0),.s_axi_control_ARADDR(7'b0),.s_axi_control_RREADY(1'b1),.s_axi_control_BVALID(ctrl_bv),.s_axi_control_BREADY(1'b1),.s_axi_control_BRESP(ctrl_br));
wire ap_start=dut.ap_start,ap_done=dut.ap_done;wire[31:0]ap_return=dut.ap_return;
wire compute_start=dut.grp_p_anonymous_namespace_compute_tile_fu_1328_ap_start;
wire compute_done=dut.grp_p_anonymous_namespace_compute_tile_fu_1328_ap_done;
wire weights_done=dut.grp_p_anonymous_namespace_load_weights_fu_1264_ap_done;
wire writeback_done=dut.grp_p_anonymous_namespace_store_tile_fu_1431_ap_done;
reg[63:0]mem[0:8191],expected[0:255];integer rq_addr[0:63],rq_len[0:63],wq_addr[0:63],wq_len[0:63];
integer rh=0,rt=0,rn=0,wh=0,wt=0,wn=0,responses=0,cycle=0,case_id=0,out_words=0,read_beats=0,write_beats=0,held_ar_cycles=0;
reg r_taken=0,b_taken=0,held_ar=0;reg[63:0]held_araddr;reg[7:0]held_arlen;
reg passed=0;integer i,j;time started;
always @(posedge clk)begin
 if(!resetn)begin rh=0;rt=0;rn=0;wh=0;wt=0;wn=0;responses=0;r_taken=0;b_taken=0;cycle=0;read_beats=0;write_beats=0;held_ar=0;held_ar_cycles=0;end
 else begin
  cycle=cycle+1;r_taken=rvalid&&rready;b_taken=bvalid&&bready;
  if(held_ar&&(!arvalid||araddr!==held_araddr||arlen!==held_arlen))$fatal(1,"AR_NOT_STABLE");
  held_ar=arvalid&&!arready;held_araddr=araddr;held_arlen=arlen;if(held_ar)held_ar_cycles=held_ar_cycles+1;
  if(r_taken)begin
   if(rn==0||rlast!==(rq_len[rh]==1))$fatal(1,"R_QUEUE_OR_LAST");
   read_beats=read_beats+1;
   if(rq_len[rh]==1)begin rh=(rh+1)%64;rn=rn-1;end else begin rq_addr[rh]=rq_addr[rh]+1;rq_len[rh]=rq_len[rh]-1;end
  end
  if(arvalid&&arready)begin
   if(araddr[2:0]!=0||arsize!=3||arid!=0||araddr+8*(arlen+1)>65536)$fatal(1,"AR_RANGE_OR_SIZE");
   rq_addr[rt]=araddr/8;rq_len[rt]=int'(arlen)+1;rt=(rt+1)%64;rn=rn+1;
  end
  if(b_taken)responses=responses-1;
  if(wvalid&&wready)begin
   if(wn==0||wlast!==(wq_len[wh]==1))$fatal(1,"W_QUEUE_OR_LAST");
   if(wq_addr[wh]<2048||wq_addr[wh]>=2048+out_words)$fatal(1,"WRITE_OUTSIDE_OUTPUT");
   for(integer b=0;b<8;b=b+1)if(wstrb[b])mem[wq_addr[wh]][b*8+:8]=wdata[b*8+:8];
   write_beats=write_beats+1;
   if(wq_len[wh]==1)begin wh=(wh+1)%64;wn=wn-1;responses=responses+1;end else begin wq_addr[wh]=wq_addr[wh]+1;wq_len[wh]=wq_len[wh]-1;end
  end
  if(awvalid&&awready)begin
   if(awaddr[2:0]!=0||awsize!=3||awid!=0)$fatal(1,"AW_ALIGNMENT");
   wq_addr[wt]=awaddr/8;wq_len[wt]=int'(awlen)+1;wt=(wt+1)%64;wn=wn+1;
  end
  if(rn>63||wn>63||responses<0)$fatal(1,"QUEUE_OVERFLOW");
 end
end
always @(negedge clk)begin
 if(!resetn)begin arready=0;rvalid=0;awready=0;wready=0;bvalid=0;end
 else begin
  arready=rn<60&&(cycle%7!=0);awready=wn<60&&(cycle%5!=0);wready=wn>0&&(cycle%5!=2);
  if(!rvalid||r_taken)begin
   rvalid=rn>0&&(cycle%5!=1);
   if(rvalid)begin rdata=mem[rq_addr[rh]];rlast=rq_len[rh]==1;end
  end
  if(!bvalid||b_taken)bvalid=responses>0;
 end
end
task wr(input[6:0]a,input[31:0]v);
begin
 @(negedge clk);ctrl_addr=a;ctrl_av=1;
 do @(posedge clk);while(!ctrl_ar);
 @(negedge clk);ctrl_av=0;ctrl_data=v;ctrl_wv=1;
 do @(posedge clk);while(!ctrl_wr);
 @(negedge clk);ctrl_wv=0;wait(ctrl_bv);if(ctrl_br)$fatal(1,"AXIL_BRESP");@(negedge clk);
end endtask
initial begin
 for(case_id=0;case_id<3;case_id=case_id+1)begin
  resetn=0;repeat(8)@(negedge clk);
  out_words=(case_id==0)?10:((case_id==1)?15:((case_id==2)?14:11));
  $readmemh($sformatf("case%0d_mem.hex",case_id),mem);
  $readmemh($sformatf("case%0d_expected.hex",case_id),expected,0,out_words-1);
  resetn=1;repeat(8)@(negedge clk);
  wr('h18,'h1000);wr('h1c,0);wr('h24,'h2000);wr('h28,0);wr('h30,'h3000);wr('h34,0);wr('h3c,'h4000);wr('h40,0);wr('h48,'h5000);wr('h4c,0);
  started=$time;wr(0,1);wait(ap_done);@(negedge clk);
  if(ap_return!=0||rn!=0||wn!=0||responses!=0)$fatal(1,"BAD_COMPLETION status=%0d readQ=%0d writeQ=%0d responses=%0d",ap_return,rn,wn,responses);
  for(i=0;i<out_words;i=i+1)if(mem[2048+i]!==expected[i])$fatal(1,"VALUE_MISMATCH case=%0d word=%0d got=%h want=%h",case_id,i,mem[2048+i],expected[i]);
  if(mem[2047]!==64'ha5a5a5a5a5a5a5a5||mem[2048+out_words]!==64'ha5a5a5a5a5a5a5a5)$fatal(1,"OUTPUT_GUARD");
  $display("CORE_CASE_PASS case=%0d words=%0d read_beats=%0d write_beats=%0d AR_stall=%0d start_ns=%0t end_ns=%0t",case_id,out_words,read_beats,write_beats,held_ar_cycles,started,$time);
  repeat(8)@(negedge clk);
 end
 passed=1;$display("CURRENT_CORE_RTL_PASS cases=3 output_bytes=312 int8_reference_exact=1 output_guards=1");#100;$finish;
end
initial begin #100000;$fatal(1,"CORE_TIMEOUT case=%0d",case_id);end
endmodule
