obj-m += gesture_pynq_hand_i8.o
all:
	$(MAKE) -C $(kernel_src) M=$(CURDIR) ARCH=arm CROSS_COMPILE=$(cross_compile) modules
