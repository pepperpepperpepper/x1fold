=== META ===============================================================
Tue Oct 28 04:22:28 AM UTC 2025
Kernel: Linux archlinux-opcode-sniffer-b025 6.16.10-custom #1 SMP PREEMPT_DYNAMIC Tue Oct 28 03:32:37 UTC 2025 x86_64 GNU/Linux
DMI:
  product_name: 21ETS1JM00
  product_version: ThinkPad X1 Fold 16 Gen 1
  board_name: 21ETS1JM00
  bios_vendor: LENOVO
  bios_version: N3LET38W (1.19 )
  bios_date: 05/06/2024

=== SECURE BOOT / MOK ==================================================

=== PCI ENUMERATION SNAPSHOT ===========================================
egrep: warning: egrep is obsolescent; using grep -E
00:12.0 Serial controller [0700]: Intel Corporation Alder Lake-P Integrated Sensor Hub [8086:51fc] (rev 01)
00:15.0 Serial bus controller [0c80]: Intel Corporation Alder Lake PCH Serial IO I2C Controller #0 [8086:51e8] (rev 01)
00:15.1 Serial bus controller [0c80]: Intel Corporation Alder Lake PCH Serial IO I2C Controller #1 [8086:51e9] (rev 01)
00:19.0 Serial bus controller [0c80]: Intel Corporation Alder Lake-P Serial IO I2C Controller #0 [8086:51c5] (rev 01)
00:1e.2 Serial bus controller [0c80]: Intel Corporation Alder Lake SPI Controller [8086:51aa] (rev 01)
00:1e.3 Serial bus controller [0c80]: Intel Corporation Alder Lake SPI Controller [8086:51ab] (rev 01)
00:1f.5 Serial bus controller [0c80]: Intel Corporation Alder Lake-P PCH SPI Controller [8086:51a4] (rev 01)
--- 00:15.0 ---------------------------------------------------------
00:15.0 Serial bus controller [0c80]: Intel Corporation Alder Lake PCH Serial IO I2C Controller #0 [8086:51e8] (rev 01)
	Subsystem: Lenovo Device [17aa:2301]
	Control: I/O- Mem+ BusMaster+ SpecCycle- MemWINV- VGASnoop- ParErr- Stepping- SERR- FastB2B- DisINTx-
	Status: Cap+ 66MHz- UDF- FastB2B- ParErr- DEVSEL=fast >TAbort- <TAbort- <MAbort- >SERR- <PERR- INTx-
	Latency: 0, Cache Line Size: 64 bytes
	Interrupt: pin A routed to IRQ 27
	IOMMU group: 12
	Region 0: Memory at 4017000000 (64-bit, non-prefetchable) [size=4K]
	Capabilities: [80] Power Management version 3
		Flags: PMEClk- DSI- D1- D2- AuxCurrent=0mA PME(D0-,D1-,D2-,D3hot-,D3cold-)
		Status: D3 NoSoftRst+ PME-Enable- DSel=0 DScale=0 PME-
	Capabilities: [90] Vendor Specific Information: Intel <unknown>
	Kernel driver in use: intel-lpss

--- 00:15.1 ---------------------------------------------------------
00:15.1 Serial bus controller [0c80]: Intel Corporation Alder Lake PCH Serial IO I2C Controller #1 [8086:51e9] (rev 01)
	Subsystem: Lenovo Device [17aa:2301]
	Control: I/O- Mem+ BusMaster+ SpecCycle- MemWINV- VGASnoop- ParErr- Stepping- SERR- FastB2B- DisINTx-
	Status: Cap+ 66MHz- UDF- FastB2B- ParErr- DEVSEL=fast >TAbort- <TAbort- <MAbort- >SERR- <PERR- INTx-
	Latency: 0, Cache Line Size: 64 bytes
	Interrupt: pin B routed to IRQ 40
	IOMMU group: 12
	Region 0: Memory at 4017001000 (64-bit, non-prefetchable) [size=4K]
	Capabilities: [80] Power Management version 3
		Flags: PMEClk- DSI- D1- D2- AuxCurrent=0mA PME(D0-,D1-,D2-,D3hot-,D3cold-)
		Status: D3 NoSoftRst+ PME-Enable- DSel=0 DScale=0 PME-
	Capabilities: [90] Vendor Specific Information: Intel <unknown>
	Kernel driver in use: intel-lpss

--- 00:15.2 ---------------------------------------------------------
--- 00:15.3 ---------------------------------------------------------
--- 00:19.0 -----------------------------------------------------------
00:19.0 Serial bus controller [0c80]: Intel Corporation Alder Lake-P Serial IO I2C Controller #0 [8086:51c5] (rev 01)
	Subsystem: Lenovo Device [17aa:2301]
	Control: I/O- Mem+ BusMaster+ SpecCycle- MemWINV- VGASnoop- ParErr- Stepping- SERR- FastB2B- DisINTx-
	Status: Cap+ 66MHz- UDF- FastB2B- ParErr- DEVSEL=fast >TAbort- <TAbort- <MAbort- >SERR- <PERR- INTx-
	Latency: 0, Cache Line Size: 64 bytes
	Interrupt: pin A routed to IRQ 31
	IOMMU group: 14
	Region 0: Memory at 4017002000 (64-bit, non-prefetchable) [size=4K]
	Capabilities: [80] Power Management version 3
		Flags: PMEClk- DSI- D1- D2- AuxCurrent=0mA PME(D0-,D1-,D2-,D3hot-,D3cold-)
		Status: D3 NoSoftRst+ PME-Enable- DSel=0 DScale=0 PME-
	Capabilities: [90] Vendor Specific Information: Intel <unknown>
	Kernel driver in use: intel-lpss


=== ACPI DUMP / I2C3 MAPPING ===========================================
[grep] I2C3 device blocks, _ADR, _STA:
egrep: warning: egrep is obsolescent; using grep -E
[grep] All I2cSerialBus() references:

=== PINMUX / LPSS POWER STATE ==========================================
--- /sys/kernel/debug/pinctrl/INTC1055:00 pins (grep i2c) -----------------------------------------------
pin 5 (ISH_I2C0_SDA) 5:INTC1055:00 mode 1 0x44000702 0x0003c01d 0x00000100 [ACPI]
pin 6 (ISH_I2C0_SCL) 6:INTC1055:00 mode 1 0x44000702 0x0003c01e 0x00000100 [ACPI]
pin 7 (ISH_I2C1_SDA) 7:INTC1055:00 mode 1 0x44000702 0x0003c01f 0x00000000 [ACPI]
pin 8 (ISH_I2C1_SCL) 8:INTC1055:00 mode 1 0x44000702 0x0003c020 0x00000000 [ACPI]
pin 9 (I2C5_SDA) 9:INTC1055:00 GPIO 0x44000300 0x00000021 0x00000000 [LOCKED full, ACPI]
pin 10 (I2C5_SCL) 10:INTC1055:00 GPIO 0x44000300 0x00000022 0x00000000 [LOCKED full, ACPI]
pin 26 (I2C6_SDA) 32:INTC1055:00 GPIO 0x44000300 0x00000030 0x00000000 [LOCKED full, ACPI]
pin 27 (I2C6_SCL) 33:INTC1055:00 GPIO 0x44000300 0x00000031 0x00000000 [LOCKED full, ACPI]
pin 28 (I2C7_SDA) 34:INTC1055:00 mode 2 0x44000b00 0x00001032 0x00000000 [LOCKED full, ACPI]
pin 29 (I2C7_SCL) 35:INTC1055:00 mode 2 0x44000b00 0x00001033 0x00000000 [LOCKED full, ACPI]
pin 53 (PMC_I2C_SDA) 75:INTC1055:00 GPIO 0x44000102 0x0000304b 0x00000100 [ACPI]
pin 55 (PMC_I2C_SCL) 77:INTC1055:00 GPIO 0x44000201 0x0000004d 0x00000100 [ACPI]
pin 79 (I2C2_SDA) 132:INTC1055:00 mode 1 0x44000702 0x00000018 0x00000000 [ACPI]
pin 80 (I2C2_SCL) 133:INTC1055:00 mode 1 0x44000702 0x00000019 0x00000000 [ACPI]
pin 81 (I2C3_SDA) 134:INTC1055:00 mode 1 0x44000702 0x0000001a 0x00000000 [ACPI]
pin 82 (I2C3_SCL) 135:INTC1055:00 mode 1 0x44000702 0x0000001b 0x00000000 [ACPI]
pin 83 (I2C4_SDA) 136:INTC1055:00 mode 1 0x44000700 0x0000001c 0x00000000 [ACPI]
pin 84 (I2C4_SCL) 137:INTC1055:00 mode 1 0x44000700 0x0000001d 0x00000000 [ACPI]
pin 187 (I2C0_SDA) 272:INTC1055:00 GPIO 0x44000300 0x0000001e 0x00000000 [LOCKED full, ACPI]
pin 188 (I2C0_SCL) 273:INTC1055:00 GPIO 0x44000300 0x0000001f 0x00000000 [LOCKED full, ACPI]
pin 189 (I2C1_SDA) 274:INTC1055:00 GPIO 0x44000300 0x00000020 0x00000000 [LOCKED full, ACPI]
pin 190 (I2C1_SCL) 275:INTC1055:00 GPIO 0x44000300 0x00000021 0x00000000 [LOCKED full, ACPI]
--- /sys/kernel/debug/pinctrl/INTC1055:00 pinmux-pins (grep i2c) ----------------------------------------
pin 5 (ISH_I2C0_SDA): (MUX UNCLAIMED) (GPIO UNCLAIMED)
pin 6 (ISH_I2C0_SCL): (MUX UNCLAIMED) (GPIO UNCLAIMED)
pin 7 (ISH_I2C1_SDA): (MUX UNCLAIMED) (GPIO UNCLAIMED)
pin 8 (ISH_I2C1_SCL): (MUX UNCLAIMED) (GPIO UNCLAIMED)
pin 9 (I2C5_SDA): (MUX UNCLAIMED) (GPIO UNCLAIMED)
pin 10 (I2C5_SCL): (MUX UNCLAIMED) (GPIO UNCLAIMED)
pin 26 (I2C6_SDA): (MUX UNCLAIMED) (GPIO UNCLAIMED)
pin 27 (I2C6_SCL): (MUX UNCLAIMED) (GPIO UNCLAIMED)
pin 28 (I2C7_SDA): (MUX UNCLAIMED) (GPIO UNCLAIMED)
pin 29 (I2C7_SCL): (MUX UNCLAIMED) (GPIO UNCLAIMED)
pin 53 (PMC_I2C_SDA): (MUX UNCLAIMED) (GPIO UNCLAIMED)
pin 55 (PMC_I2C_SCL): (MUX UNCLAIMED) (GPIO UNCLAIMED)
pin 79 (I2C2_SDA): (MUX UNCLAIMED) (GPIO UNCLAIMED)
pin 80 (I2C2_SCL): (MUX UNCLAIMED) (GPIO UNCLAIMED)
pin 81 (I2C3_SDA): (MUX UNCLAIMED) (GPIO UNCLAIMED)
pin 82 (I2C3_SCL): (MUX UNCLAIMED) (GPIO UNCLAIMED)
pin 83 (I2C4_SDA): (MUX UNCLAIMED) (GPIO UNCLAIMED)
pin 84 (I2C4_SCL): (MUX UNCLAIMED) (GPIO UNCLAIMED)
pin 187 (I2C0_SDA): (MUX UNCLAIMED) (GPIO UNCLAIMED)
pin 188 (I2C0_SCL): (MUX UNCLAIMED) (GPIO UNCLAIMED)
pin 189 (I2C1_SDA): (MUX UNCLAIMED) (GPIO UNCLAIMED)
pin 190 (I2C1_SCL): (MUX UNCLAIMED) (GPIO UNCLAIMED)

=== RUNTIME POWER / PM FOR 00:15.X =====================================
--- /sys/bus/pci/devices/0000:00:15.0 --------------------------------------------------------------
power/control                    : auto
power/runtime_status             : suspended
power/runtime_suspended_time     : 1652250
power/runtime_active_time        : 2491
--- /sys/bus/pci/devices/0000:00:15.1 --------------------------------------------------------------
power/control                    : auto
power/runtime_status             : suspended
power/runtime_suspended_time     : 1650611
power/runtime_active_time        : 4121

=== PSF/P2SB / SBREG QUICK CHECKS ======================================
[mmio_rw] SBREG @ 0xFD000000 (32-bit r32):
0xffffffff

=== CHIPSEC MSG BUS (if available) =====================================
chipsec not available (import failed); skipping IOSF PSF reads.

=== TRACEPOINT HOOK (optional, current session) ========================
ftrace not available; skipping PCI tracepoints.

=== PSTORE (persistent crash/early logs) ===============================
total 0

=== SUMMARY HINT =======================================================
Log saved to: /tmp/x1fold_i2c3_20251028T042228Z.log
Key checks:
 - lspci shows which 00:15.x functions enumerate (expect .0/.1 present, .3 missing).
 - AML grep confirms I2C3 _ADR 0x00150003 and _STA.
 - Pinctrl grep hints if I2C3 pins are muxed to GPIO.
 - SBREG probe/Chipsec reads hint whether IOSF/PSF is accessible in-OS.
 - Power/PM shows if LPSS slices are in D3/auto.

