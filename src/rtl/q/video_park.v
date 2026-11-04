// Explicit idle physical interfaces for a compute-only Qiming candidate.
// LCD reset is ACTIVE_LOW in the official BD, sourced by peripheral_aresetn.
// LCD backlight PWM reset disables the output (POLARITY=1 -> output 0).
// RGB remains high impedance, matching official lcd_id GPIO reset input mode;
// the external LCD ID straps must not be driven. No video clocks are generated.
module video_idle_pins(
    (* X_INTERFACE_IGNORE = "true" *) input wire [7:0] pin0,
    (* X_INTERFACE_IGNORE = "true" *) input wire pin1, pin2, pin3,
    (* X_INTERFACE_IGNORE = "true" *) output wire pin4, pin5, pin6, pin7,
    (* X_INTERFACE_IGNORE = "true" *) output wire [0:0] pin8, pin9,
    (* X_INTERFACE_IGNORE = "true" *) inout wire [23:0] pin10,
    (* X_INTERFACE_IGNORE = "true" *) output wire pin11, pin12,
    (* X_INTERFACE_IGNORE = "true" *) output wire [2:0] pin13, pin14
);
    assign pin4 = 1'b0;
    assign pin5 = 1'b0;
    assign pin6 = 1'b0;
    assign pin7 = 1'b0;
    assign pin8 = 1'b0;
    assign pin9 = 1'b0;
    genvar i;
    generate for (i=0; i<24; i=i+1) begin: rgb_input_mode
        wire ignored;
        IOBUF rgb_pad(.IO(pin10[i]), .I(1'b0), .T(1'b1), .O(ignored));
    end endgenerate
    // Differential output buffers preserve TMDS_33 electrical pairing. A static
    // signal has no pixel clock and therefore cannot advertise a video stream.
    OBUFDS clk_park(.I(1'b0), .O(pin11), .OB(pin12));
    generate for (i=0; i<3; i=i+1) begin: tmds_idle
        OBUFDS data_park(.I(1'b0), .O(pin13[i]), .OB(pin14[i]));
    end endgenerate
endmodule
