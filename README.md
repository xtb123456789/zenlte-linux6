# zenlte-linux6 — Samsung Galaxy S6 Edge+ (SM-G9280) on mainline Linux 6.6

Running mainline Linux 6.6 + Ubuntu 24.04 (arm64) + GNOME 46 on a
**Samsung Galaxy S6 Edge+ (SM-G9280, codename zenlte, Exynos7420)**.
This repo focuses on the **display IOMMU/SYSMMU**, **GPU (Panfrost / Mali-T760)
hardware acceleration** and **touch input** work.

> Mainline does not support this device out of the box.  This repository
> contains all the kernel changes, packaging tools, flashable images and
> technical documentation needed to make it usable.

![SM-G9280 running Ubuntu 24.04.5 LTS / GNOME 46 / Wayland / Linux 6.6.0 / Mali-T760 (Panfrost)](docs/screenshots/ubuntu-24.04-gnome46-mali-t760.jpg)

*SM-G9280 (Exynos7420) running Ubuntu 24.04.5 LTS + GNOME 46 (Wayland) +
Linux 6.6.0; the GPU is detected as Mali-T760 (Panfrost); 8 cores
(4× Cortex-A53 + 4× Cortex-A57).*

---

## Milestones (achieved)

| Feature | Status | Notes |
|---|---|---|
| Boot (Exynos7420, 8 CPUs) | ✅ | mainline 6.6.0 + Ubuntu 24.04 arm64 |
| Wi-Fi (BCM4359 PCIe) | ✅ | `exynos7420-pcie` + brcmfmac |
| Bluetooth (BCM4349B1) | ✅ | UART4/LPASS + AUD pad retention |
| Touch (stmfts) | ✅ | taps / gestures / 2x scaling |
| **Display IOMMU/SYSMMU** | ✅ | DECON `13930000.decon` → SYSMMU `13a00000`/`13a10000` |
| **GPU acceleration (Panfrost)** | ✅ | Mali-T760, Mutter GPU-composited, `glmark2` 900+ FPS |
| GNOME desktop | ✅ | Wayland, `gnome-shell --display-server` |
| Browser / desktop apps | ✅ | see "Known limitations" |
| Audio | ⚠️ | see `docs/HANDOVER-audio.md` |

## Key breakthroughs

### 1. Display IOMMU/SYSMMU (`exynos-iommu.c`, `exynos7.dtsi` in `patches/`)
The Exynos7420 DECON is wired to SYSMMU v6.  The mainline driver cannot work
as-is; the fixes are:

- **Do not read the version register at probe** (it wedges the bus while the
  DISP power domain is off) → static `MAKE_MMU_VER(6,0)` + `sysmmu_v5_variant`.
- **Deferred enable via `owner->ready`**: do not enable the SYSMMU on the
  DECON runtime-resume path; wait until the DECON driver has programmed an
  IOVA-mapped framebuffer, then call `exynos_iommu_master_ready()`.
- **Identity-map the bootloader framebuffer** (vendor `iovmm_map_oto`
  semantics) via `exynos_iommu_map_identity()`, so the DECON can keep scanning
  its old physical framebuffer once the SYSMMU starts translating.
- **Wire the SYSMMU `master` clock** (= DECON aclk); otherwise the CCF hangs
  when enabling the SYSMMU `pclk`.
- **Make SYSMMU faults non-fatal** (match the vendor `disp_driver_fault_handler`).
- **Remove the conflicting simpledrm** in the DECON driver
  (`drm_aperture_remove_framebuffers()`); otherwise GNOME sees two display
  devices and touch mapping / scaling break.

### 2. DECON triple buffering (`exynos7_drm_decon.c`)
The driver sets `WINCONx_TRIPLE_BUF_MODE` but only writes `VIDW_BUF_START`
(0x80), not `BUF_START1/2` (0x84/0x88) → stale frames on every repaint
(flicker).  Writing the same address to all three fixes it.

### 3. GPU (`clk-exynos7.c`, `exynos7.dtsi`, Mesa)
Mali-T760 r0p1 on mainline hits `gpu sched timeout` / `js fault`
(fragment jobs hang, tile ghosting):

- **GPU `bus` clock**: add `clock-names = "core","bus"` to `gpu@14ac0000`
  where `bus = CLK_PCLK_SYSREG_G3D` (the vendor enables it; mainline never did).
- **GPU async-bridge clocks**: add `aclk_lh_g3d0/1` (CMU_CCORE
  `ENABLE_ACLK_CCORE0` bits 22/23, `CLK_IS_CRITICAL`).
- **Mesa side**: `PAN_MESA_DEBUG=noafbc,nocrc` (disable AFBC and
  transaction-elimination/CRC).
- The compositor (Mutter) uses the GPU; GTK4/WebKit apps currently use
  `GSK_RENDERER=cairo` (software) to guarantee artifact-free rendering.

### 4. Misc
- Touch: disable the `scale-monitor-framebuffer` experimental feature
  (touch mapping breaks at 2x scale).
- `pd_disp` is a landmine: the mainline genpd lacks the vendor TZPC SMC, so do
  not attach `power-domains`.
- The DT must be packed as a **DTBH container** (`tools/mkdtbh.py`).

## Repository layout

```
patches/    Kernel changes vs v6.6 + device defconfig
artifacts/  Flashable images (boot_bt_iommu*.img) and kernel modules (.ko)
tools/      mkbootimg/mkdtbh (packaging), acm.py/send_b64.py (serial)
docs/       Handover docs, progress notes, technical analysis
rootfs/     On-device config (.bash_profile, monitors.xml, ...)
```

## Build / flash

```bash
# Build (needs an aarch64 toolchain; paths must not contain spaces)
T=/path/to/linux-6.6
export HOSTCFLAGS="-I.../hostinclude -I.../openssl@3/include"
export HOSTLDFLAGS="-L.../openssl@3/lib"
cd $T && gmake ARCH=arm64 CROSS_COMPILE=<toolchain>/bin/aarch64-linux-gnu- -j8 Image modules dtbs

# Package (DT changes must be converted to a DTBH first)
python3 tools/mkdtbh.py $T/arch/arm64/boot/dts/exynos/exynos7420-zenlte.dtb new_dt.img
python3 tools/mkbootimg_7420.py $T/arch/arm64/boot/Image <ramdisk.cpio.gz> new_dt.img boot.img

# Flash (TWRP + adb)
adb push boot.img /tmp/boot.img
adb shell "dd if=/tmp/boot.img of=/dev/block/sda7 bs=4096; sync"
```

## Known limitations

- **Panfrost (Mali-T760 r0p1)** still has deep issues on mainline:
  GPU-rendered GTK4/WebKit surfaces can show ghosting/stacking when composited
  in windowed mode.  Currently those toolkits are software-rendered
  (`GSK_RENDERER=cairo`) while the compositor stays on the GPU, which is
  artifact-free.  `patches/` already contains the GPU bus/async-bridge clock
  fixes; further work could add the full G3D power-domain sequence.
- `boot_bt_iommu19.img` contains the async-bridge clock fix and has not been
  tested on hardware yet.
- The device does not auto-connect to a network; transferring large files over
  the serial console is slow.

## Hardware

- SoC: Samsung Exynos7420 (4× Cortex-A57 + 4× Cortex-A53)
- GPU: ARM Mali-T760 MP8
- Display: 1440×2560 MIPI-DSI command mode (i80), DECON `13930000`,
  SYSMMU `13a00000`/`13a10000`
- Touch: STMicroelectronics stmfts (i2c-2 @0x49)
- Wi-Fi/BT: Broadcom BCM4359 (PCIe) / BCM4349B1 (UART4)

## Contact

- Email: **1018514521@qq.com**

Feedback and discussion about Exynos7420 / mainline Linux / Panfrost are welcome.
