# 进度存档 — 2026-09-13（蓝牙 + 浏览器）

设备：SM-G9280 (S6 Edge+ / Exynos7420 "zenlte")，mainline Linux 6.6.0 (Ubuntu 24.04 arm64)。
详细内容见 `HANDOVER-audio.md` §30（蓝牙）、§31（浏览器）。

## 已完成（重启自动生效）
### 蓝牙 BCM4349B1（BCM4359 combo，UART4/AUD/LPASS）
- `hci0` UP RUNNING，BD `43:49:B1:00:1F:AC`，HCI 4.2，固件 `BCM4359B1 ... build 0370`。
- 三个根因与修复：
  1. 蓝牙在 **UART4 (0x11460000, gpz1, AUD/LPASS)**，非 UART1。
  2. `samsung_tty` 挂死：`aclk_peric1_66` 加 `CLK_IS_CRITICAL`（`clk-exynos7.c`）。
  3. AUD Pad Retention + LPASS UART 中断屏蔽：`exynos7420-bt-power.service` 写 PMU `0x105c3028/0x105c1340` + LPASS `0x11400058`。
- 内核/DT 改动：`exynos7.dtsi`（`pinctrl_aud@114b0000` + `serial_4@11460000`）、`exynos7-clk.h`（AUD UART clk ID）、
  `exynos7420-zenlte.dts`（蓝牙移到 `&serial_4` + LPO `<&s2mps13_osc S2MPS11_CLK_BT>`）。
- 模块依赖：ecc → ecdh_generic → bluetooth → btbcm/btqca → hci_uart。

### GNOME 顶栏 WiFi/蓝牙开关
- 会话为定制直启（只起 gsd-power）→ 补 `gsd-rfkill` 到 `/root/.bash_profile`
  （须起在 `dbus-run-session` 的**私有总线**上）。

### 浏览器 Epiphany (GNOME Web)
- `apt install epiphany-browser`（WebKitGTK 2.52）。
- 修 IPv6 卡死：`/etc/gai.conf` 加 `precedence ::ffff:0:0/96 100`（iPhone 热点无 IPv6）。
- 修窗口化花屏（GTK4/WebKit）：会话级 `WEBKIT_DISABLE_DMABUF_RENDERER=1`、
  `WEBKIT_DISABLE_COMPOSITING_MODE=1`、`GSK_RENDERER=cairo`（根因：Exynos DRM 无 IOMMU 拒收非连续 dma-buf）。

## 关键文件（设备）
- `/root/.bash_profile`（含 gsd-rfkill + 上述渲染 env）、`/root/.bash_profile.bak-bt`（旧备份）
- `/root/Music/SoundHelix-Song-1.mp3`
- `/root/launch-epiphany.sh`、`/root/launch-epiphany-soft.sh`
- `/usr/local/bin/exynos7420-bt-power.sh` + `/etc/systemd/system/exynos7420-bt-power.service`
- `/etc/gai.conf`、`/lib/firmware/brcm/BCM4349B1.hcd`、`/lib/modules/6.6.0/{bluetooth,hci_uart,btbcm,btqca,ecc,ecdh_generic}.ko`

## 备份位置（xtb，最后同步时）
`/Volumes/xtb/linux-backup-20260912/`
- `status/HANDOVER-audio.md`、`vendor1to1/HANDOVER-audio.md`（含 §30/§31）
- `backup-20260913/bt/`：`sda7_boot_bt_20260913.img`、`clk-exynos7.c`、`exynos7.dtsi`、`exynos7420-zenlte.dts`、
  `exynos7-clk.h`、`exynos7420-bt-power.{sh,service}`、`bash_profile*.{bt,mutter,final-browser}`、
  `launch-epiphany*.sh`、`start-gsd-rfkill.sh`

## 后续追加（2026-09-15）
- **时区**：`timedatectl set-timezone Asia/Shanghai`（CST +0800，持久）。
- **GNOME Dock 侧边栏**：`apt install gnome-shell-extension-ubuntu-dock`（90ubuntu3）；
  `gsettings` 的 `enabled-extensions` 已含 `ubuntu-dock@ubuntu.com`，重启后自动加载
  （注：`gnome-extensions list` 查不到是 `--display-server` 会话不导出 `org.gnome.Shell.Extensions`，
  但扩展实际已运行，见 `/root/gnome.log`）。`/root/enable-dock.sh` 为启用脚本。
- **HTML5 视频**：装 `gstreamer1.0-libav` / `gstreamer1.0-plugins-bad` / `gstreamer1.0-plugins-ugly`
  （此前只有 good/base，缺 H.264/AAC → WebKit 视频放不了）。
- **浏览器渲染**：会话级软件渲染（`WEBKIT_DISABLE_DMABUF_RENDERER=1`、
  `WEBKIT_DISABLE_COMPOSITING_MODE=1`、`GSK_RENDERER=cairo`）。功能正常但**滑动卡**（CPU 重绘）；
  拖动窗口流畅（合成器平移缓存）。折中（仅禁 DMA-BUF）会**花屏**。要流畅需 IOMMU（见待办2）。
- **文件管理器**：`apt install nautilus`（GNOME Files 46.4，GTK4，随会话软件渲染正常）。
- **通用 GUI 启动脚本**：`/root/launch-gui.sh <app>`（注入会话总线/Wayland + 软件渲染 env 后 setsid 启动）。

## IOMMU 尝试（2026-09-15，未成功，已恢复）
- 目标：给显示控制器(DECON)接 Exynos SYSMMU，让导入的非连续 dma-buf 得到连续 IOVA，恢复 GPU 加速。
- 已做（工作树 `/Volumes/kernel_build/linux-6.6`，来自内盘 `kernel_build.sparseimage`）：
  - `exynos7-clk.h`：CMU_DISP 增加 `CLK_ACLK/PCLK_DISP_RO/RW_SYSMMU`(12..15)，`DISP_NR_CLK=16`。
  - `clk-exynos7.c`：CMU_DISP 增加 4 个门控寄存器 `0x0804/0x0808/0x0904/0x0908` bit0 + 4 个 GATE + 加入 clk_regs。
  - `exynos7.dtsi`：新增 `sysmmu_disp_ro@13a00000`(SPI 176) / `sysmmu_disp_rw@13a10000`(SPI 179)，compatible `samsung,exynos-sysmmu`，`#iommu-cells=<0>`；decon 加 `iommus=<&sysmmu_disp_ro>,<&sysmmu_disp_rw>`。
  - `.config`：`CONFIG_EXYNOS_IOMMU=y`。
  - 重编 Image+dtb+exynosdrm.ko，打包 `boot_bt_iommu.img`。
- **结果：卡三星 logo（极早期挂死）**。
- 恢复：TWRP 刷回 `boot_bt_lpo.img`（sda7）+ 还原旧 `exynosdrm.ko`（`/root/exynosdrm.ko.bak`）→ 已正常。
- 分析：`exynos_sysmmu_probe → __sysmmu_get_version` 虽先 `__sysmmu_enable_clocks`，但 **SYSMMU 的电源域(pd_disp)可能未上电** → 读版本寄存器挂总线。
- 下次可试：给两个 SYSMMU 节点加 `power-domains = <&pd_disp>;`（并确认 DISP SYSMMU 时钟父链）。风险：仍可能卡 logo（需 TWRP 恢复）。

## 备份（2026-09-15）
- `sda18-rootfs-20260915.img.gz`（5.98 GB，`gzip -t` 通过），
  sha256 `61a13cd02d8dc50c7a1188045f883f85f0af4ebdc088344352efdb57a044d456`
  （`/Volumes/xtb/linux-backup-20260912/backup-20260913/`）。
  经 TWRP `adb exec-out "dd if=/dev/block/sda18 bs=4M | gzip -1"` 流式传输（设备无 nc；WiFi 当时无 IP）。

## 待办
1. **重存 sda18 rootfs 镜像**（本轮 apt/服务/配置文件改动多）。设备重连后执行：
   ```
   # 设备端（建议 nc 流式，避免写回同一分区）
   dd if=/dev/sda18 bs=4M status=progress | gzip -1 | nc 172.20.10.12 9000
   # Mac 端
   nc -l 9000 > sda18-rootfs-20260913-bt.img.gz
   shasum -a 256 sda18-rootfs-20260913-bt.img.gz > ....sha256
   ```
   （若无 `nc`，退回 dd→/tmp→python http.server→Mac curl。）
2. **恢复 GPU 加速**：启用 Exynos SYSMMU/IOMMU（`CONFIG_EXYNOS_IOMMU=y` + DECON 的 SYSMMU DT 节点），
   替代当前 GTK4/WebKit 软件渲染。
3. 音频（WM1840/CS47L85 + I2S）继续。
4. 可选：`gnome-keyring`、蓝牙配对/音频实测。
