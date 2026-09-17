# 上下文压缩 — S6 Edge+ (SM-G9280/zenlte) mainline Linux 6.6

## 环境/工具
- 设备 SM-G9280 (zenlte, Exynos7420)，mainline 6.6.0 + Ubuntu 24.04 arm64；串口 `/dev/cu.usbmodem2301`
- 工具 `WORKING-66gpu/tools/{acm.py,send_b64.py}`（acm.py 单次写会截断，长命令用 send_b64）
- 内核树 **`/Volumes/kernel_build/linux-6.6`**（内盘 `scratch/kernel_build.sparseimage` 挂载；路径不能含空格）
  厂商树 `/Volumes/kernel_build/kernel`（同一 sparseimage）
- 构建：`gmake ARCH=arm64 CROSS_COMPILE=<toolchain-aarch64>/bin/aarch64-linux-gnu-` +
  `HOSTCFLAGS="-I.../scratch/hostinclude -I.../openssl@3/3.6.4/include" HOSTLDFLAGS="-L.../openssl@3/3.6.4/lib"`
- 打包：`brain/1aa1eae7-.../scratch/mkbootimg_7420.py` + **`mkdtbh.py`（DT 必须 DTBH 容器）**；输出在 `WORKING-66bt/`
- 分区 sda7=BOOT(28M)、sda18=rootfs；**好镜像 `WORKING-66bt/boot_bt_lpo.img`**；旧模块 `/root/exynosdrm.ko.bak`
- 刷机：优先 WiFi HTTP（Mac `python3 -m http.server`，设备 curl -4）；WiFi 不稳时 **TWRP adb**
- 备份：`adb exec-out "dd if=/dev/block/sda18 bs=4M | gzip -1" > file`（设备无 nc）

## 已完成 ✅
- **WiFi** BCM4359 PCIe：PMU `0x105c071c=1` + CMU_FSYS1 gate + MSI 内联派发；`pci-exynos.ko`
- **蓝牙** BCM4349B1（三根因）：
  ① BT 在 **UART4/AUD/LPASS (0x11460000, gpz1)**，非 UART1（厂商 serial_1=调试口）
  ② `aclk_peric1_66` 加 `CLK_IS_CRITICAL`（否则关 UART 时钟锁死 CMU_PERIC1）
  ③ **AUD pad retention**（PMU `0x105c3028 bit28`、`0x105c1340=1`）+ **LPASS UART IRQ**（`0x11400058=0xff`）
  → `exynos7420-bt-power.service`；`hci0 UP RUNNING`，BD 43:49:B1:00:1F:AC
- **桌面**：gsd-rfkill（须起在 `dbus-run-session` 私有总线，写 `.bash_profile`）、Ubuntu Dock、
  Nautilus、时区 Asia/Shanghai、Epiphany（+GStreamer libav/bad/ugly 解码器；软件渲染 `GSK_RENDERER=cairo` 等）
- **备份**：`sda18-rootfs-20260915.img.gz`（5.98G，sha256 `61a13cd02d8dc50c7a1188045f883f85f0af4ebdc088344352efdb57a044d456`）
- **文档**：`HANDOVER-audio.md` §30（蓝牙）/§31（浏览器）、`PROGRESS-20260913-bt-browser.md`

## 当前任务：恢复 GPU 加速（IOMMU）
**问题**：Exynos 显示控制器只接受连续 dma-buf（`exynos_drm_gem.c:436`），Panfrost(shmem) 非连续 →
窗口花屏；现用软件渲染绕过（功能正常，滑动卡）。
**尝试**：sysmmu_disp_ro/rw 节点 + `CONFIG_EXYNOS_IOMMU=y` + `power-domains=<&pd_disp>` + 改 pd_disp 地址 →
**仍卡 logo**。
**根因（4 个 subagent 定论）**：
- mainline `exynos-iommu.c` **probe 时读 `REG_MMU_VERSION`**（`:774/:518`），要求 DISP 域/总线已上电；
  mainline 的 7420 域上电序列不完整 → 读寄存器挂总线。
- 厂商 probe **不碰寄存器**（延迟到 display master 使能时访问）→ 稳。
- 厂商 **pd_disp = `0x105c4080`**（mainline 用 0x105c4120 是 Exynos7/5433 地址，错）；
  `LOCAL_PWR_CFG=0xf`；**OPTION 寄存器 `base+0x8 = 0x0102`（mainline 从不写）**。
- 厂商 DISP `on_pre`：TOP0 `0x105d080c` bit28 + `0x105d0a20` bits28/24/20/16/12；
  VPP `0x13ed0800` bits0-3；PMU `0x1450/1490/14d0/1510/1550/1590` **清位**；
  `on_post` 的 `save_list_disp` 仅 resume 需要（冷启动写零有害）。
- 替代路线（agent 评估）：**Mesa kmsro**（Panfrost 把 SCANOUT 分配交给 KMS/exynos → CMA 连续，
  无需 IOMMU）性价比最高；Panfrost CMA 改动过大（~300-600 行 core DRM）；bounce buffer 每帧 ~28MiB 不可行。

## 推荐下一步（按性价比）
1. **Mesa kmsro**：确认设备 `exynos_dri.so` 存在、KMS 节点 GBM 走 exynos/kmsro；试
   `MUTTER_DEBUG_USE_KMS_MODIFIERS=0`。若生效 → scanout 用 exynos CMA，无需 IOMMU。
2. **exynos-iommu 懒读版本**（厂商做法）：把 `__sysmmu_get_version` 从 probe 移到首次 enable。
3. 给 `top_aclk_disp_400`/`aclk_smmu_disp_ro`/`pclk_smmu_disp_ro` 加 `CLK_IS_CRITICAL` + 保留 `power-domains`（便宜诊断）。
4. 把厂商 7420 DISP `on_pre` 序列移植进 mainline genpd（`exynos-pm-domains.c`，工作量大）。

## 关键改动位置
- `clk-exynos7.c`：已加 SYSMMU gates（CMU_DISP 0x0804/0808/0904/0908）；CMU_DISP 0x0800/TOP0 0x080c/0x0a20 是 CCF 拥有
- `exynos7.dtsi`：sysmmu_disp_ro/rw@13a00000/13a10000、decon `iommus`、pd_disp（已改 reg=0x105c4080, okay）
- `exynos-iommu.c`（mainline）：probe 读版本是挂死点
- 产物镜像：`WORKING-66bt/boot_bt_iommu{,2,3,4}.img`（均卡 logo）、`boot_bt_lpo.img`（好）
