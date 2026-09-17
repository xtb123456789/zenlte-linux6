# Handover: display IOMMU + GPU acceleration + touch (zenlte mainline 6.6)

> Follows on from `HANDOVER-IOMMU-NEXT-AGENT.md`.  This document records the
> complete state after the display IOMMU work **finished**, plus the
> simpledrm / triple-buffer / GPU / touch issues solved afterwards.

## 0. One-line status

**Display IOMMU/SYSMMU, GPU compositing, touch taps, 2x scaling and the
single-display setup all work.**  GTK4/WebKit apps currently use software
rendering (`GSK_RENDERER=cairo`) to avoid the deeper Panfrost T760 rendering
issues; the compositor (Mutter) is GPU-accelerated.

## 1. Final working configuration

### 1.1 Kernel patches (see `patches/zenlte-mainline-6.6.patch`)

**`drivers/iommu/exynos-iommu.c`**
- probe uses a static `MAKE_MMU_VER(6,0)` + `sysmmu_v5_variant`; no version
  register read
- `struct exynos_iommu_owner` gains `bool ready`
- `exynos_sysmmu_resume()`: only `__sysmmu_enable()` when
  `owner->ready && !data->active`
- `exynos_sysmmu_suspend()`: only `__sysmmu_disable()` when `data->active`
- exports `exynos_iommu_master_ready()` / `exynos_iommu_map_identity()`
- SYSMMU faults no longer `panic()` (match vendor)

**`arch/arm64/boot/dts/exynos/exynos7.dtsi`**
- `sysmmu_disp_ro/rw`: `clock-names = "aclk","pclk","master"`, with
  `master = CLK_ACLK_DECON0`
- DECON `iommus = <&sysmmu_disp_ro>, <&sysmmu_disp_rw>`, no `power-domains`
- `gpu@14ac0000`: `clock-names = "core","bus"`, `bus = CLK_PCLK_SYSREG_G3D`

**`drivers/clk/samsung/clk-exynos7.c`**
- four CMU_DISP SYSMMU gates (`0x0804/0808/0904/0908` bit0)
- CMU_CCORE: add `aclk_lh_g3d0/1` (`ENABLE_ACLK_CCORE0` bits 22/23,
  `CLK_IS_CRITICAL`)

**`drivers/gpu/drm/exynos/`**
- `exynos7_drm_decon.c`: in `decon_atomic_enable()` call
  `exynos_iommu_map_identity()` + `exynos_iommu_master_ready()` for the
  bootloader fb; in `decon_update_plane()` also write `VIDW_BUF_START1/2`
  (triple buffering)
- `exynos_drm_drv.c`: `drm_aperture_remove_framebuffers()` at the start of
  `exynos_drm_bind()`
- `exynos_drm_dma.c`: return `-EPROBE_DEFER` when the IOMMU is not ready but
  `iommus` is present

**`drivers/pmdomain/samsung/exynos-pm-domains.c`**: `samsung,exynos7420-pd`
(**missing the TZPC SMC — do not actually use it**)

### 1.2 On-device rootfs

**`/root/.bash_profile`** (see `rootfs/bash_profile`)
```
GSK_RENDERER=cairo
WEBKIT_DISABLE_DMABUF_RENDERER=1
WEBKIT_DISABLE_COMPOSITING_MODE=1
PAN_MESA_DEBUG=noafbc,nocrc
```
starts `gnome-shell --wayland --display-server --no-x11` (via `dbus-run-session`).

**`/root/.config/monitors.xml`**: `VGA-1` (exynos) `scale=2`, `1440x2560@59.8`

**`gsettings`**: `org.gnome.mutter experimental-features = []`
(disables `scale-monitor-framebuffer`)

**systemd**: `exynos7420-gpu-pm.service` (GPU `power/control=on`, mitigates
panfrost timeouts)

## 2. Images

| Image | Contents | Status |
|---|---|---|
| `boot_bt_iommu17.img` | IOMMU + master clock + identity map + non-fatal faults | ✅ works |
| `boot_bt_iommu18.img` | + GPU `bus` clock (DTS) | ✅ works |
| `boot_bt_iommu19.img` | + `aclk_lh_g3d0/1` (Image) | untested |
| `boot_bt_iommu_mod2.img` | older software-render stable build | ✅ fallback |

DRM module: `exynosdrm-simpledrm-fix.ko` (simpledrm removal + triple-buffer
fix), installed as `/lib/modules/6.6.0/extra/exynosdrm.ko`.

## 3. Key findings / pitfalls

1. **SYSMMU enable timing**: at DECON runtime-resume the DECON is still
   scanning the bootloader's physical fb; enabling the SYSMMU then faults /
   wedges the bus.  Identity-map the old fb first (or mask the trigger and wait
   for the frame to finish) before enabling.
2. **The `master` clock is required**: without `master` (= DECON aclk) on the
   SYSMMU node, the CCF hangs when enabling `pclk`.
3. **simpledrm must be removed**: otherwise GNOME sees two display devices and
   touch auto-mapping / scaling break
   (`drm_aperture_remove_framebuffers()`).
4. **`scale-monitor-framebuffer` experimental feature**: with it enabled, touch
   mapping breaks at 2x scale; disable it.
5. **Triple buffering**: `WINCONx_TRIPLE_BUF_MODE` requires writing
   `BUF_START/START1/START2`.
6. **GPU `bus` clock**: `pclk_sysreg_g3d` is never enabled by mainline →
   panfrost timeouts.
7. **Panfrost T760 r0p1**: AFBC/CRC/tiling paths make fragment jobs hang and
   tiles ghost; mitigate with `PAN_MESA_DEBUG=noafbc,nocrc`.  A full fix needs
   the complete G3D power-domain sequence (vendor `save_list_g3d`,
   `aclk_lh_g3d0/1`) or a Mesa change.
8. **DTBH**: DT changes must be repacked with `mkdtbh.py` or they will not take
   effect.
9. **Serial**: transfer large files with gzip + base64 (`send_b64.py`),
   otherwise it is very slow.

## 4. Suggested next steps

1. Flash `boot_bt_iommu19.img` and check whether `aclk_lh_g3d0/1` makes the GPU
   more stable (together with the Mesa options).
2. If ghosting persists: implement the full `exynos7420_g3d_cfg` power-domain
   sequence (top/local clocks, sys_pwr, save/restore), referencing
   `kernel/arch/arm64/mach-exynos/pm_domains-exynos7420*.{c,h}`.
3. Fix the `pd_g3d` base address (mainline `0x105c4060` is actually CAM1; the
   vendor G3D is `0x105c4100`).
4. Audio (see `HANDOVER-audio.md`).

## 5. Environment

- Kernel tree `/Volumes/kernel_build/linux-6.6` (sparseimage:
  `~/.gemini/antigravity/scratch/kernel_build.sparseimage`, **not** the backup
  under `xtb/`)
- Vendor tree `/Volumes/kernel_build/kernel` (3.10.61)
- Build: `gmake ARCH=arm64 CROSS_COMPILE=<aarch64-toolchain>/bin/aarch64-linux-gnu- -j8 Image modules dtbs`
- Serial `/dev/cu.usbmodem2301` (system) / `2302` (TWRP)
- Flashing via TWRP: `adb push ...; adb shell "dd if=/tmp/boot.img of=/dev/block/sda7 bs=4096; sync"`
