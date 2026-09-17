# 交接文档：显示 IOMMU + GPU 加速 + 触摸（zenlte mainline 6.6）

> 承接 `HANDOVER-IOMMU-NEXT-AGENT.md`。本文件记录显示 IOMMU 攻坚**完成**后的
> 完整状态，以及随后解决的 simpledrm / 三缓冲 / GPU / 触摸问题。

## 0. 一句话现状

**显示 IOMMU/SYSMMU、GPU 合成、触摸点击、2x 缩放、单显示器全部正常。**
GTK4/WebKit 应用当前走软件渲染（`GSK_RENDERER=cairo`）以规避 Panfrost T760 的
深层渲染问题；合成器（Mutter）走 GPU 加速。

## 1. 最终生效配置

### 1.1 内核 patch（见 `patches/zenlte-mainline-6.6.patch`）

**`drivers/iommu/exynos-iommu.c`**
- probe 静态 `MAKE_MMU_VER(6,0)` + `sysmmu_v5_variant`，不读版本寄存器
- `struct exynos_iommu_owner` 加 `bool ready`
- `exynos_sysmmu_resume()`：仅当 `owner->ready && !data->active` 才 `__sysmmu_enable()`
- `exynos_sysmmu_suspend()`：仅当 `data->active` 才 `__sysmmu_disable()`
- 新增导出 `exynos_iommu_master_ready()` / `exynos_iommu_map_identity()`
- SYSMMU fault 不再 `panic()`（对齐原厂）

**`arch/arm64/boot/dts/exynos/exynos7.dtsi`**
- `sysmmu_disp_ro/rw`：`clock-names = "aclk","pclk","master"`，`master = CLK_ACLK_DECON0`
- DECON `iommus = <&sysmmu_disp_ro>, <&sysmmu_disp_rw>`，无 `power-domains`
- `gpu@14ac0000`：`clock-names = "core","bus"`，`bus = CLK_PCLK_SYSREG_G3D`

**`drivers/clk/samsung/clk-exynos7.c`**
- CMU_DISP 4 个 SYSMMU 门控（`0x0804/0808/0904/0908` bit0）
- CMU_CCORE 补 `aclk_lh_g3d0/1`（`ENABLE_ACLK_CCORE0` bit22/23，`CLK_IS_CRITICAL`）

**`drivers/gpu/drm/exynos/`**
- `exynos7_drm_decon.c`：`decon_atomic_enable()` 里对 bootloader fb 调
  `exynos_iommu_map_identity()` + `exynos_iommu_master_ready()`；
  `decon_update_plane()` 补写 `VIDW_BUF_START1/2`（三缓冲）
- `exynos_drm_drv.c`：`exynos_drm_bind()` 开头 `drm_aperture_remove_framebuffers()`
- `exynos_drm_dma.c`：IOMMU 未就绪且有 `iommus` 时 `-EPROBE_DEFER`

**`drivers/pmdomain/samsung/exynos-pm-domains.c`**：`samsung,exynos7420-pd`（**缺 TZPC SMC，勿真用**）

### 1.2 设备侧 rootfs

**`/root/.bash_profile`**（见 `rootfs/bash_profile`）
```
GSK_RENDERER=cairo
WEBKIT_DISABLE_DMABUF_RENDERER=1
WEBKIT_DISABLE_COMPOSITING_MODE=1
PAN_MESA_DEBUG=noafbc,nocrc
```
启动 `gnome-shell --wayland --display-server --no-x11`（`dbus-run-session`）。

**`/root/.config/monitors.xml`**：`VGA-1`（exynos）`scale=2`，`1440x2560@59.8`

**`gsettings`**：`org.gnome.mutter experimental-features = []`（关 `scale-monitor-framebuffer`）

**systemd**：`exynos7420-gpu-pm.service`（GPU `power/control=on`，缓解 panfrost 超时）

## 2. 镜像

| 镜像 | 内容 | 状态 |
|---|---|---|
| `boot_bt_iommu17.img` | IOMMU + master 时钟 + 恒等映射 + 非致命 fault | ✅ 可用 |
| `boot_bt_iommu18.img` | + GPU `bus` 时钟（DTS） | ✅ 可用 |
| `boot_bt_iommu19.img` | + `aclk_lh_g3d0/1`（Image） | 未实测 |
| `boot_bt_iommu_mod2.img` | 旧的软件渲染稳定版 | ✅ 回退用 |

DRM 模块：`exynosdrm-simpledrm-fix.ko`（含 simpledrm 移除 + 三缓冲修复）
装入 `/lib/modules/6.6.0/extra/exynosdrm.ko`。

## 3. 关键结论 / 踩坑

1. **SYSMMU 使能时机**：DECON runtime-resume 时 DECON 还在扫 bootloader 物理 fb，
   此时使能 SYSMMU → fault/挂总线。必须先恒等映射旧 fb（或 mask trigger 等帧结束），
   再使能。
2. **master 时钟必需**：SYSMMU 节点缺 `master`（DECON aclk）时，CCF 使能 pclk 会挂。
3. **simpledrm 必须移除**：否则 GNOME 看到 2 个显示设备 → 触摸自动映射/缩放错乱
   （`drm_aperture_remove_framebuffers()`）。
4. **`scale-monitor-framebuffer` 实验特性**：开启时 2x 缩放触摸映射错乱，必须关闭。
5. **三缓冲**：`WINCONx_TRIPLE_BUF_MODE` 必须同时写 `BUF_START/START1/START2`。
6. **GPU `bus` 时钟**：`pclk_sysreg_g3d` mainline 从不使能 → panfrost 超时。
7. **Panfrost T760 r0p1**：AFBC/CRC/tiling 路径会导致 fragment job 卡死 / tile 重影，
   用 `PAN_MESA_DEBUG=noafbc,nocrc` 缓解；彻底修复需补全 G3D 电源域序列
   （原厂 `save_list_g3d`、`aclk_lh_g3d0/1`）或 Mesa 侧改动。
8. **DTBH**：DT 改动必须 `mkdtbh.py` 重新打包，否则不生效。
9. **串口**：大文件用 gzip + base64 传（`send_b64.py`），否则很慢。

## 4. 建议下一步

1. 刷 `boot_bt_iommu19.img`，验证 `aclk_lh_g3d0/1` 是否让 GPU 更稳（配合 Mesa 选项）。
2. 若仍重影：实现完整 `exynos7420_g3d_cfg` 电源域序列（top/local 时钟、sys_pwr、
   save/restore），参考 `kernel/arch/arm64/mach-exynos/pm_domains-exynos7420*.{c,h}`。
3. 修正 `pd_g3d` 基址（mainline `0x105c4060` 实为 CAM1，原厂 G3D 为 `0x105c4100`）。
4. 音频（见 `HANDOVER-audio.md`）。

## 5. 环境

- 内核树 `/Volumes/kernel_build/linux-6.6`（sparseimage：
  `~/.gemini/antigravity/scratch/kernel_build.sparseimage`，**不是** xtb 里的备份）
- 厂商树 `/Volumes/kernel_build/kernel`（3.10.61）
- 构建：`gmake ARCH=arm64 CROSS_COMPILE=<aarch64-toolchain>/bin/aarch64-linux-gnu- -j8 Image modules dtbs`
- 串口 `/dev/cu.usbmodem2301`（系统）/ `2302`（TWRP）
- 刷机 TWRP：`adb push ...; adb shell "dd if=/tmp/boot.img of=/dev/block/sda7 bs=4096; sync"`
