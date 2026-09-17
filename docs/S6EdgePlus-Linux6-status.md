# Samsung Galaxy S6 Edge+ (SM-G9280 / Exynos 7420 "zenlte") — Linux 6.6 LTS 移植状态与技术交接

> **更新时间**: 2026-09-13 03:06
> **★★★ 音频突破镜像(2026-09-13 03:05)**: `WORKING-66gnome/smp8_audio4_rev1fix.img` —— 修复 **S2MPS15 Rev1 LDO25/LDO26 寄存器地址互换**(codec DCVDD 1.2V 从未上电的根因),**codec (WM1840/CS47L85) 已在 mainline 首次应答 `ID=0x6338`**。详见 §18.16。
> **最新可开机验证镜像**: `WORKING-66gnome/smp8_auto_boot.img`(物理 arch timer tick + **CNTPCT clocksource 修复** + **cpufeature 异构 erratum 修复** + **`maxcpus=8`**)。**开机即 8 核(4×A53 + 4×A57)**;8 核负载压测 0 stall。桌面 exynos DRM + Mali 56fps、触摸、GNOME 均可用;已离线安装基础软件(设置/监视器/常用 CLI,§12)。
> **SMP/多核**:**★ 全部解决(2026-09-12 04:30)**:**8 核(4×A53 + 4×A57)全部上线稳定**。两个根因:① clocksource 在非 hyp(`EL1`)下强制用 **CNTVCT**,而固件 **CNTVOFF 每核不一致** → 跨核 timekeeping 爆炸(修复:改用 **CNTPCT + 关 vDSO**,`arm_arch_timer.c`);② big.LITTLE 下 A57 触发 **Spectre-v2 能力冲突**,`verify_local_cpu_caps()` 直接 `cpu_die_early()`(修复:`ARM64_CPUCAP_LOCAL_CPU_ERRATUM` 加 `PERMITTED_FOR_LATE_CPU` 允许异构 late CPU,`cpufeature.h`)。详见 §11.9 / §11.10。
> **当前内核树状态**: systemd 当 PID1、GNOME 跑在 tty1;**触摸已打通并修复「点击变长按」(§4.9.2)**;**exynos DRM(命令模式 DECON)已打通并 GPU 加速**;**SMP 8 核已打通**(§11);**桌面图标(SVG loader)与壁纸已修(§4.10)**;**电池/电量/充放电检测已上(MAX77833 FG,§13)**;**USB 拔线死机已修(§14)**;**温度检测已开(TMU,§15.1)、磁盘容量已修(udisks2,§15.2)**;**htop 真实 freq/temp 已通:自写 `exynos7420_dvfs.ko` 真·双簇 DVFS(§15.4)、hwmon 温度桥接(§15.5)**;**电源菜单已通(自写 SessionManager shim + UFS shutdown workaround + PMU/PSCI reboot,§15.3)**;**屏幕亮度已通(自写 DSIM `0x53/0x51` + backlight + gsd-power,§15.6)**;**音频(WM1840/CS47L85 + MAX98505)**:★ **根因与修复完成(§18.16)**——S2MPS15 **Rev1** 芯片把 **LDO25/LDO26 寄存器地址对调**,mainline `s2mps11.c` 按 Rev0 算错 → codec **DCVDD(1.2V) 从未上电**;(此前误判为"SPI 挂死/缺 MCLK")。已在 `s2mps11.c` 加 Rev1 检测 + 寄存器交换,重编刷入后 **codec 在 mainline 首次应答 `ID=0x6338`**。后续:加载 `madera`/`cs47l85` + 机器驱动 + I2S 出声。详见 §15.7 / §18.15 / §18.16。**✅ 设备现状(2026-09-12 23:00):CROM 已解锁;刷 CRF2(Android 7) 新 BL 后 Linux 一度**卡死在 UFS 初始化**,已通过**移植 6.10 的 SMC 版 `exynos_ufs_config_smu`** 解决(§17);sda18 rootfs 已从备份流式恢复;最新镜像 `WORKING-66gnome/smp8_ufssmc8.img`(8 核 + UFS SMC 修复 + 无 ttyGS0)正常启动,systemd `running`、0 failed;TWRP 可用(`twrp-3.1.1-0-zenlte.img`)。详见 §16/§17。**
> **文档目的**: 全面记录本轮(systemd / GNOME / 显示 / 触摸 / exynos DRM / SMP)进展与下一步,交给下一个模型继续。

---

## 0. TL;DR（给下一个模型）

- **已完成**:主线 6.6 → console、UFS、USB CDC ACM 串口、**s2mps15 PMIC**、**Mali-T760 GPU(Panfrost+ES3.1)**、**CMU_DISP 显示时钟**、**kmscube(Mali 渲染+PRIME 上屏 ~29.5fps)**、**systemd 当 PID1 引导**、**GNOME Shell/gnome-session 完整会话跑在 tty1 并显示在屏上**、**离线侧载链路**。
- **GNOME 关键结论(§4.7/§4.8)**:GNOME/Mutter **需要 logind**(Mutter 46 无 logind 直接 `Failed to setup: Could not get session ID`),所以必须 **systemd 当 PID1**;用自写 init `switch_root` 到 sda18 后 exec systemd,`getty@tty1` autologin → `/root/.bash_profile` 里 `dbus-run-session -- gnome-shell --wayland --display-server` 起会话。Mutter 把 `card0(simpledrm)` 当 primary 做了 modeset。
- **显示「闪一下就没了」的两个根因(§4.8)**:① patched simpledrm 只 blit「damage」区域 → 改成**每帧整帧 blit**;② 它有**每 100ms 把 fbdev 控制台缓冲覆盖回 `screen_base` 的刷新 work** → **删掉**。修完后 GNOME 稳定上屏。
- **当前 GNOME 是软件渲染(llvmpipe)**(framebuffer `imported=no`+`libLLVM`);kmscube 才是 Mali。性能最好应走 **exynos DRM(真 KMS)**(§5)。
- **触摸(§4.9)— 已完成 ✅**:STM FTS(`st,stmfts`,i2c 0x49)。供电 `tsp_io`=**s2mps15 LDO15**(CHN 版,不是 max77838!)、`tsp_avdd`=**s2mpb02 LDO17**;IRQ bank = **gpa1-6**。**不用移植 vendor 驱动**——只需把 mainline `stmfts.c` 的初始化/协议改成 S6 固件版本:①复位用寄存器写 `B6 00 23 01`(不是 `0xA0`);②轮询 `0x85` 等 `CONTROLLER_READY`;③中断使能 `B6 00 1C **41**`(不是 `01`);④事件读要先读计数 `B6 00 45` 再读 `count*8`(否则 IRQ 风暴)。改完 probe 成功、IRQ 正常(~65/s)、GNOME 已接管 `event0`,**触摸可操作桌面**。
- **下一步**:**★ 多核 SMP — ✅ 全部解决(§11.9/§11.10)**:8 核(4×A53+4×A57)稳定。两处修复:clocksource 改用 **CNTPCT + 关 vDSO**;`ARM64_CPUCAP_LOCAL_CPU_ERRATUM` 允许异构 late CPU(A57 的 Spectre-v2 冲突)。可选后续:开机自动起 8 核、CMU_CPU/DVFS、WiFi BCM4359;① ~~触摸~~ ✅ ② ~~exynos DRM 真 KMS~~ ✅ ③ WiFi(未开垦);**④ 音频:★ 阻塞已除(§18.16,codec 已在 mainline 应答 `ID=0x6338`),下一步 `madera`/`cs47l85` + 机器驱动 + I2S 出声**;⑤ 清理(simpledrm 双输出、prime 连续内存、G3D 真 PLL)。

---

## 1. 核心目标

在 Samsung Galaxy S6 Edge+（国行公开版 `SM-G9280`,代号 `zenlte` / `zenltechn`,SoC `Exynos 7420`,硬件版本 `hw_rev=9`）上运行现代**主线 Linux 6.6 LTS**：
1. USB CDC ACM 虚拟串口 Root Shell（**已达成**）
2. UFS 挂载 Ubuntu 24.04 ARM64 根文件系统（**已达成**，自动 chroot）
3. 显示 / GPU / WiFi / 最终 GNOME 桌面（**GPU 已达成；显示 = 当前攻关点；WiFi 未通**）

---

## 2. 硬件拓扑与关键事实

### 引导链
- S-Boot 4.0 → `boot.img` → 末尾 `dt.img`(Samsung DTBH v2)→ 内核。
- 加载物理地址：内核 `0x40205000`(text_offset=0x00205000)、Initrd `0x43000000`、FDT `0x4a000000`(经 `x0` 传入)。
- `dt.img` 头部校验字段必须:`chip_id=0x1cfc`, `plat_id=0x50a6`, `sub_id=0x217584da`, `hw_rev=9`。

### 存储与安全红线
- UFS 2.0(`sda`)。`sda7=BOOT(28MB)`、`sda8=RECOVERY/TWRP(34MB)`、`sda18=USERDATA(27GB ext4)`。
- **绝不动 `/dev/block/sda8`**(TWRP 救砖后盾);只刷 `sda7`。
- 内置 cmdline(必须 `CONFIG_CMDLINE_FORCE=y` 强制):
  `console=tty0 console=ttyGS0,115200 maxcpus=1 loglevel=8 init=/init rw clk_ignore_unused pd_ignore_unused fw_devlink=permissive`

### 显示子系统
- 面板 2K Super AMOLED 1440×2560，**命令模式(command mode / PSR)**。
- 现状:SimpleDRM 用物理显存 `0xe2a00000`(16MB,`display_reserved` 为 `no-map`);S-Boot 已初始化好 DSI+panel，并让 DECON 持续扫描该内存,Linux 只写内存即可。**注意 `display_reserved` 是 no-map，不能 `phys_to_virt` 访问，只能用 DMA/预留地址。**
- 硬件寄存器(来自 vendor 3.10):
  | 模块 | 地址 | 中断 | 说明 |
  |---|---|---|---|
  | DECON0 | `0x13930000` | SPI 190 / 188 / 189 | `psr_mode=2`(MIPI 命令模式)、`trig_mode=0`(hw)、`ip_ver=2` |
  | DSI0 | `0x13900000` | SPI 196 | 4 lane,`samsung,exynos5-mipi-dsi` |
  | CMU_DISP | `0x13AD0000` | | 需新增时钟控制器 |
  | pd_disp | PMU 约 `0x105c4120` | | 电源域 |

### USB 物理链路
`Micro-USB` → `MAX77833 MUIC(I2C-1, 0x25)` → `USBDRD PHY(0x15500000)` → `DWC3(0x15400000)`。
由于 hsi2c 控制器一读寄存器就总线挂死(见 §7),主线里改用 **第二条 i2c-gpio(gpg3-0/1)** 或既有 i2c-gpio(gpd2-2/3) 驱动 MUIC。

### WiFi
- 芯片 **BCM4359**，挂 `dwmmc2@15560000`(SDIO, 4bit)，使能脚 `gpf4-6`。
- 现状:SDIO 主控已 probe、WLAN_EN 已拉高，但 **chip 不响应(CARD 枚举失败)**。vendor 的 `clk_pin/clk_val/clk_str_num` 经查是 SDMMC 时钟脚**驱动强度调优**(`dw_mmc-exynos.c:855`)不是参考时钟源;BCM4359 的 26M/供电是硬件默认。参考树 6.10 **没有 WiFi**,所以这是未开垦区域。

### PMIC（s2mps15）
- 挂 `hsi2c@13660000`(引脚 gpg3-0/1)，主线用 **i2c-gpio-pmic** 绕开挂死的 hsi2c。
- 提供 RTC、`s2mps13-clk`(32.768kHz)、37 路 regulator（含 `VDD_G3D_0P9`、UFS/显示轨）。

### GPU
- **Mali-T760** `gpu@14ac0000`，IRQ JOB=241 / MMU=242 / GPU=240。
- 电源域 `pd_g3d`(PMU `0x105c4060`)，时钟控制器 `CMU_G3D`(`0x14AA0000`)。
- Panfrost 支持 `arm,mali-t760`。

---

## 3. 已完全跑通的模块（100% 实测）

| 模块 | 驱动 / 机制 | 状态 | 实测表现 |
|---|---|---|---|
| CPU/架构 | 4×Cortex-A57 + 4×Cortex-A53 | **正常** | **8 核 SMP 稳定**(§11);启动核 A53(MPIDR 0x100) |
| 时钟/中断 | Exynos MCT `0x101c0000` | 正常 | jiffies 正常;需 `arm,cpu-registers-not-fw-configured` + `clock-frequency=<24000000>` |
| 显示 console | SimpleDRM + S-Boot DECON 扫描 | 正常 | 企鹅 + 终端控制台清晰 |
| 存储 | UFS 2.0 `exynos7-ufs` | 正常 | `sda1~sda18` 全部识别 |
| USB 串口 | DWC3 + `g_serial`(CDC ACM) | 正常 | Mac 侧 `/dev/cu.usbmodem2401`,内核 cmdline `console=ttyGS0` |
| 用户空间 | 静态 `/init`(PID 1) | 正常 | 自动 `mount /dev/sda18` → `chroot /mnt/ubuntu` → Ubuntu 24.04.5 shell |
| PMIC | s2mps15 (i2c-gpio) | **正常** | RTC0 + s2mps13-clk + 37 regulator 全注册(43 个 `/sys/class/regulator`) |
| GPU | Panfrost(内核)+ Mesa(用户态) | **正常** | `mali-t760 id 0x750`;`/dev/dri/renderD128`;Mesa panfrost `OpenGL ES 3.1` |

### 关键修复(踩过的坑)
1. **built-in cmdline 加 `clk_ignore_unused pd_ignore_unused`**(否则因 `CONFIG_CMDLINE_FORCE=y` 被 DTS bootargs 忽略 → 时钟被关)。
2. **timer 节点加 `arm,cpu-registers-not-fw-configured; clock-frequency=<24000000>`**(否则 sched_clock 不走、jiffies 不涨、所有超时/kthread 卡死)。
3. **hsi2c 一读寄存器就总线挂死** → PERIC0 IP 时钟实际未跑(主线 6.6/6.10 时钟代码相同,不是名字 bug)→ 用 i2c-gpio 绕开。
4. **s2mps15 `s2mps15_ldo_voltage_ranges3`**:6.6 的 `max_sel=0x34` 会导致 LDO26 `-EINVAL`,套用 6.10 的 `0x3f` 后 PMIC 全绿。
5. `dw_mci_exynos_parse_dt` 强制要求 `samsung,dw-mshc-sdr-timing`;fixed-regulator 必须写 `regulator-min/max-microvolt`。

---

## 4. GPU(`clk-exynos7.c` CMU_G3D + pd_g3d）— 已完成

**改动**:
1. `include/dt-bindings/clock/exynos7-clk.h`:新增 G3D block(`CLK_FOUT_G3D_PLL`, `CLK_MOUT_ACLK_G3D_400`, `CLK_DIV_ACLK_G3D`, `CLK_DIV_PCLK_G3D`, `CLK_ACLK_G3D`, `CLK_PCLK_SYSREG_G3D`, `CLK_PCLK_PMU_G3D`, `G3D_NR_CLK`)。
2. `drivers/clk/samsung/clk-exynos7.c`:新增 CMU_G3D(reg 0x0000 PLL / 0x0200 MUX_SEL / 0x0600 DIV / 0x0800 ACLK gate / 0x0900 PCLK / 0x0A00 SCLK),`FRATE` 一个 700MHz 的 `fout_g3d_pll`,`CLK_OF_DECLARE("samsung,exynos7-clock-g3d")`。
3. `exynos7.dtsi`:`cmu_g3d@14aa0000` + `pd_g3d@105c4060`(`samsung,exynos5433-pd`);`gpu@14ac0000` 接 `clocks=<&cmu_g3d CLK_ACLK_G3D>`、`clock-names="core"`、`power-domains=<&pd_g3d>`。
4. `exynos7420-zenlte.dts`:`&gpu { status="okay"; mali-supply = <&buck6_reg>; };`
5. `.config`:`CONFIG_DRM_PANFROST=y`。

**实测 dmesg**:
```
panfrost 14ac0000.gpu: clock rate = 700000000
panfrost 14ac0000.gpu: mali-t760 id 0x750 major 0x0 minor 0x1 status 0x1
panfrost 14ac0000.gpu: shader_present=0xff l2_present=0x1
[drm] Initialized panfrost 1.2.0 for 14ac0000.gpu on minor 1
```
**实测 eglinfo**(`EGL_PLATFORM=surfaceless eglinfo`):
```
EGL driver name: panfrost
OpenGL ES profile renderer: Mali-T760 (Panfrost)
OpenGL ES profile version: OpenGL ES 3.1 Mesa 25.2.8
```

> 注:G3D PLL 目前用 **700MHz 固定桩**(真实 PLL 是 `pll_1452x`+`table_g3d[]`,最高 772MHz,S-Boot 已配好;后续若需 DVFS 再补真 PLL)。

---

## 4.5 CMU_DISP 显示时钟（已完成，开机实测通过）

**改动**（`WORKING-66gpu/` 没存新 copy，当前树即最新）：
1. `include/dt-bindings/clock/exynos7-clk.h`
   - TOP0 追加：`CLK_MOUT/D_OUT_ACLK_DISP_400`、`CLK_ACLK_DISP_400`、`CLK_MOUT/D_OUT/SCLK_DECON_INT_ECLK`、`CLK_MOUT/D_OUT/SCLK_DECON_VCLK`，`TOP0_NR_CLK=26`。
   - 新增 DISP block：`CLK_FOUT_DISP_PLL`(1) … `CLK_MOUT_SUB_SCLK_DECON_INT_ECLK`(2) / `..._VCLK`(3) / `CLK_DOUT_PCLK_DISP`(4) / `CLK_DOUT_SUB_*`(5/6) / `CLK_ACLK_DECON0`(7) / `CLK_PCLK_DECON0`(8) / `CLK_SCLK_DECON0_ECLK`(9) / `CLK_SCLK_DECON0_VCLK`(10) / `CLK_PCLK_DSIM0`(11)，`DISP_NR_CLK=12`。
2. `drivers/clk/samsung/clk-exynos7.c`
   - CMU_TOP0：新增 `MUX_SEL_TOP0_DISP(0x0220)` / `DIV_TOP0_DISP(0x0620)` / `ENABLE_SCLK_TOP0_DISP(0x0A20)` 偏移；`mout/dout/top_aclk_disp_400`、`mout/dout/top_sclk_decon_int_eclk`、`mout/dout/top_sclk_decon_vclk`；`ENABLE_ACLK_TOP03` 也加进了 `top0_clk_regs`。
   - 新增 `exynos7_clk_disp`（`CLK_OF_DECLARE("samsung,exynos7-clock-disp")` @ `0x13AD0000`）：真实 `pll_1460x` `disp_pll`（table `disp_pll_tbl`，24M 基准，**注意 vendor 列序是 {rate,p,m,s,k}，主线 `PLL_36XX_RATE` 是 (m,p,s,k)，要交换**）、`m_decon0_eclk/vclk`、`d_pclk_disp`、`d_decon0_eclk/vclk`、`aclk_decon0`/`pclk_decon0`/`pclk_dsim0`/`decon0_eclk`/`decon0_vclk`（后 5 个 gate 加了 `CLK_IGNORE_UNUSED`）。
   - **跨 CMU 父子靠时钟名字符串**：DISP 里的 `top_aclk_disp_400` / `top_sclk_decon_*_eclk` 指向 CMU_TOP0 注册的 gate。
3. `exynos7.dtsi`：新增 `cmu_disp@13ad0000`；`decon` 的 4 个 clocks 从 `fin_pll` 桩换成 `&cmu_disp` ID；`pd_disp` 置 `status="disabled"`；decon 仍 `disabled`。

**开机实测 `clk_summary`**（`direct_boot_66disp3.img`）：
```
disp_pll                                252000000  Y
mout_sub_sclk_decon_int_eclk/vclk       252000000  Y
  dout_sub_sclk_decon_int_eclk/vclk     126000000  Y
    decon0_eclk / decon0_vclk           126000000  Y
top_sclk_decon_int_eclk/vclk             50000000  Y   (TOP0, 800M/16)
top_aclk_disp_400                       800000000  Y
dout_pclk_disp / pclk_decon0 / pclk_dsim0  266666667  Y
aclk_decon0                             800000000  Y
```
> 注:`mout_sub_sclk_decon_*` 当前 mux 选的是 **disp_pll(1)**（S-Boot 设的），不是 TOP0 那路 50MHz；即 DECON 的 vclk/eclk 实际 126MHz。后续面板时序按此对齐。

---

## 4.6 GPU + 显示打通（kmscube）— 已完成，实测出画面 ✅

**结论:不需要 exynos DRM 也能拿到「Mali 渲染 + KMS scanout」组合。**

- `card0` = patched `simple-framebuffer`(KMS,且支持 **PRIME import**;这份 simpledrm 被魔改过,见下)
- `card1`/`renderD128` = panfrost(GPU)
- `kmscube` 用 `-D /dev/dri/card0`(默认)时,Mesa 的 GBM 会自动选到 **Panfrost render node** 做 GL,再用 `gbm_bo_get_fd` + `drmModeAddFB2` 经 **PRIME** 把 buffer 导入 simpledrm scanout。

**实测(设备上 `/root/kmscube`)**:
```sh
timeout 25 /root/kmscube -c 150
# EGL 1.5 / Mesa Project
# OpenGL ES 3.1 Mesa 25.2.8 ; renderer "Mali-T760 (Panfrost)"
# Rendered 149 frames in 5.04 sec (29.56 fps)   @1440x2560
```
目视:屏幕上出现旋转方块(已确认)。

**关键前置**(全是已有资产):
- patched `drivers/gpu/drm/tiny/simpledrm.c`:ioremaps DECON `0x13930000`,写 `0x00/0x30/0x50/0x80/0x6b0/0x710` 推命令模式面板;有 10Hz 刷新 work + panic notifier(把 panic 打到屏上)。`DRM_GEM_SHMEM_DRIVER_OPS` 提供 `gem_prime_import_sg_table`,所以能 PRIME 导入。
- panfrost + Mesa(`panfrost_dri.so` / `exynos_dri.so` 都在 `/usr/lib/aarch64-linux-gnu/dri/`)。
- ramdisk 用的是 `lean_ramdisk_wifi.cpio.gz`。

**构建/侧载 kmscube**:
- 本机 arm64 Docker(Colima)`ubuntu:24.04` 里 `meson+ninja` 编译 `gitlab.freedesktop.org/mesa/kmscube`,动态链 libdrm/libgbm/libEGL/libGLESv2(设备上都有)。
- 产物备份:`WORKING-66gpu/kmscube/{kmscube,kmscube.gz,libdrm-tests_*.deb}`。
- **传输法(重要):勿用 raw `dd`**!串口 shell 是 **bash PID1**,raw 二进制会被 bash 当命令解析(上次因此把 shell 卡进未闭合引号、最后 PID1 退出导致内核 panic 卡死)。改用 **base64 heredoc 纯文本**:`base64 -d > /root/kmscube.gz << 'B64ZZEND' ... B64ZZEND`,`base64` 字符集对 shell 无害;本地脚本 `/tmp/send_b64.py`。传完 `sha256sum` 校验。

---

## 4.7 systemd 当 PID1 + GNOME 上屏 — 已完成 ✅

**为什么非 systemd 不可**:Mutter 46 的 `libmutter` 字符串里有 `Can't take control without logind session`;实测无 logind 时直接 `Failed to setup: Could not get session ID: User 0 has no sessions`。logind 创建会话要 systemd 开 `session-*.scope`,而 logind 又是 Mutter 拿 DRM master / seat 的前提。**所以 GNOME 必须 systemd 为 PID1。**(Ubuntu 24.04 源里没有 elogind。)

**init(`init_sd2.c`,随 ramdisk)**:基于原 `init_static.c` 最小改动,由 sda18 上的 `/etc/zenlte-init-mode` 选择模式:
- `shell`(默认/回退):老流程(绑定挂载 proc/sys/dev → chroot `/mnt/ubuntu` → bash)。
- `systemd`:先在 `/mnt`(=sda18)里把 `/mnt/ubuntu` **self-bind 成挂载点**(否则 `MS_MOVE` 必失败,因为 rootfs 是 `/mnt` 下子目录)、`mount --make-rprivate /`、把 `/proc /sys /dev` move 进去、`mount(".", "/", MS_MOVE)` + `chroot(".")` + `exec /lib/systemd/systemd`。
- 日志同时写 tty0/`/dev/kmsg`/ttyGS0,并落盘 `/mnt/ubuntu/sd-boot.log`(重启后可从 TWRP 读)。
- `MS_MOVE` 失败的三个已解决坑:`/mnt/ubuntu` 非挂载点(需 self-bind)、`/` 是 shared mount(需 `MS_REC|MS_PRIVATE`)、早前误用 `/mnt/etc/...`(rootfs 在 `/mnt/ubuntu`)。

**启动后配置(rootfs 内,持久)**:
- `/etc/systemd/system/serial-getty@ttyGS0.service.d/autologin.conf`:`ExecStart=-/sbin/agetty --autologin root --noclear %I $TERM`(串口自动登录,保证不失联)。
- `/root/.bash_profile`:tty1 上自动 `dbus-run-session -- gnome-shell --wayland --display-server --no-x11`(即 autologin 即进 GNOME)。
- 实测 `loginctl list-sessions`:session `root seat0 tty1 active`;`systemctl is-system-running` = running;`grep Name= /proc/bus/input/devices` 为空。
- **注意 `system.conf` 的 `LogLevel=debug` 会把串口刷爆**,调试时 `systemctl log-level info`。

**GNOME 依赖闭包**:见 §6。用 arm64 Docker 按设备 `dpkg status` 算闭包,共 **360 个 .deb / 168MB**,TWRP `adb push` 后 `dpkg --unpack` + `dpkg --configure -a`(一次 unpack 处理不了 Pre-Depends,需再跑 `dpkg -i *.deb`)。设备上还缺 polkit/ibus/gnome-settings-daemon 等,`gnome-shell` 会警告但能起。

---

## 4.8 显示「闪一下就没了」的根因与修复 ✅

`simpledrm.c`(被魔改的版本)里有两处会把 Mutter 画面冲掉:
1. **只 blit damage**:原 `drm_atomic_helper_damage_iter` 逻辑对 Mutter「复用同一 buffer、提交无 damage」的情况不会拷贝 → 整帧没进 `screen_base`。**改成每帧无脑整帧 `drm_fb_blit`。**
2. **100ms 周期刷新 work**(`simpledrm_refresh_work_fn`):每 100ms 把 **fbdev 控制台缓冲** `memcpy` 回 `sdev->screen_base` 并 push DECON → **GNOME 每 100ms 被控制台覆盖一次**,表现为「闪一下就没」。**删掉 `schedule_delayed_work`。**

修完(`direct_boot_66gnome2.img` 起)GNOME 稳定显示。DECON push 仍由 atomic_update 每次 commit 完成。
> 现状:`Mutter` 选 `card0(simpledrm)` 为 primary(Mutter 日志 `Added device '/dev/dri/card0' (simpledrm) using atomic mode setting` + `Integrated GPU /dev/dri/card0 selected as primary`);scanout buffer `imported=no`、进程加载 `libLLVM` → 是 **llvmpipe 软件渲染**。

---

## 4.9 触摸 STM FTS — 已完全打通 ✅（无需移植 vendor 驱动）

**硬件事实(来自设备 stock.dts + TWRP last_kmsg)**:
- 控制器:**STMicroelectronics FTS**,`compatible="st,stmfts"`,`i2c addr=0x49`(节点名 @20 是旧的)。
- I2C:`hsi2c@14E10000` = `gpj1-0/1`(我们用 **i2c-gpio-tsp**)。
- **IRQ:`gpa1-6`**(phandle 0x56 是 gpa1!**不是 gpa0**;vendor pinctrl `attn-irq` = gpa1-6 func 0x0f)。**写错成 gpa0-6 会导致 IRQ 风暴把单核占满、开机卡死。**
- 供电(关键):`tsp_io`(dvdd 1.85V)与本机名无关——**CHN 版 `SM-G9280` 是 s2mps15 的 `LDO15`(`VDD_TSP_1P8`),不是 max77838**(max77838 被 zenlte 变体 `/delete-node/`);`tsp_avdd`(3.3V)= **s2mpb02 `LDO17`**。

**我们做的(DTS + init)**:
- `exynos7420-zenlte.dts`:`ldo15_reg` 加 `regulator-always-on`;新增两条 **i2c-gpio**(`gpb0-0/1`=max77838、`gpd2-6/7`=s2mpb02)+ 触摸节点(`st,stmfts`, `vdd=<&ldo15_reg>`, `avdd=<&tsp_avdd>`(fixed), `interrupts=<gpa1 6 LEVEL_LOW>`, i2c-gpio-tsp on gpj1)。
- `init_sd2.c` 里 `setup_touch_power()`:扫 `/dev/i2c-*`,对 **s2mpb02@0x59 写 `0x2E=0xEC`**(LDO17=3.3V+使能)。max77838 在本机不存在(扫不到,无妨)。
- `.config`:`CONFIG_TOUCHSCREEN_STMFTS=m`(改成模块以便串口手动加载调试;rootfs 无 kmod,用自编 `loadko`(调 `finit_module`)加载)。
- **实测**:`i2cscan` 在 `i2c-2(tsp)` 看到 `0x49` 应答;`VDD_TSP_1P8 state=enabled 1850mV`。

**旧卡点**:加载 `stmfts.ko` 后不再卡死(IRQ bank 修好后),但 probe 失败:
```
stmfts 2-0049: error code: 0x000003
stmfts: probe of 2-0049 failed with error -110     # ETIMEDOUT
```

### 4.9.1 根因与修复（最终方案：改造 mainline `stmfts.c`，**不**移植 vendor 驱动）

对照 vendor 3.10 `drivers/input/touchscreen/stm/fts_ts.c` 逐条定位,S6 vendor 固件与通用 STM FTS 协议有 4 处关键差异,全部在 `stmfts.c` 内适配:

1. **复位命令不同**:vendor `fts_systemreset()` 写 4 字节寄存器 `B6 00 23 01`;mainline 发单字节 `STMFTS_SYSTEM_RESET=0xA0`,S6 固件不认识 → 回 `EV_ERROR`,`cmd_done` 永不 complete → probe `-110`。
   → 改为 `stmfts_write_reg(sdata, {0xb6,0x00,0x23,0x01}, 4)`。
2. **ready 握手方式不同**:vendor 复位后**轮询** `READ_ONE_EVENT(0x85)` 直到 `EVENTID_CONTROLLER_READY(0x10)`(此时中断还没使能);mainline 靠 IRQ+completion。
   → 新增 `stmfts_wait_for_ready()`:读 `0x85` 8 字节轮询,忽略 `EV_ERROR`(最多 32 次),20 次约 20ms 超时。
3. **中断使能值不同（IRQ 完全不动的原因）**:vendor `fts_interrupt_set(info, INT_ENABLE)`,`INT_ENABLE=0x41`,即写 `B6 00 1C 41`;误写成 `01` 时 attention 线始终高电平(`GPA1DAT bit6=1`)、IRQ 计数恒为 0。
   → 改为 `B6 00 1C 41`。写入后 IRQ 立即开始计数。**这是让触摸真正“活”过来的关键。**
4. **事件读取方式不同（会导致 IRQ 风暴）**:vendor 先读计数寄存器 `B6 00 45`(2 字节,`>>10` 得待处理数,FIFO 上限 32),再读 `0x86` 恰好 `count*8` 字节;mainline 盲读固定 256 字节,S6 固件不会因此清 FIFO,attention 线一直拉低 → **IRQ 风暴**(实测 3 秒 1671 次、`error code` 刷屏)。
   → 重写 `stmfts_read_events()`:先 `stmfts_read_reg({0xb6,0x00,0x45},3,cnt,2)`,`count=(cnt[0]|cnt[1]<<8)>>10`,`memset(data,0)` 后只读 `count*8`。改后空闲 ~0 中断、触摸 ~65/s。
5. (附带) `gpa1-6` 的 EINT 复用:vendor `attn-irq` 设 `pin-function=<0xf>`;实测 S-Boot 已把 `GPA1CON[27:24]` 留成 `0xf`,不是必需,但已在 DTS 补 `tsp_attn_irq` 组并挂到触摸节点。

> 结论:**完全不用移植 2900 行的 vendor `fts_touch`**。mainline 的事件解析(`EVENTID_ENTER/MOTION/LEAVE`、`x=data[1]|((data[2]&0xf)<<8)`、`y=(data[2]>>4)|(data[3]<<4)`)与 S6 固件一致,只需替换上面 4 点初始化/中断/读取逻辑,即得标准多点触控。

**实测证据**(`WORKING-66gnome/stmfts.ko`,sha256 `221fb241659c9ffa9ef385a84f698ed12806ccf0ecc43ef9323df26ba90d09dd`):
```
input: stmfts as /devices/platform/i2c-gpio-tsp/i2c-2/2-0049/input/input2
/proc/interrupts: 59:  <计数>  gpa1 6 Level  stmfts_irq     # 空闲不动、触摸 ~65/s
/dev/input/event0 → GNOME gnome-shell(PID 211) 已打开(libinput 接管)
事件样例: EV_ABS ABS_MT_TRACKING_ID / POSITION_X=880 / POSITION_Y=1398
          / TOUCH_MAJOR / PRESSURE / ORIENTATION + SYN_REPORT
```
init 时有 3 条无害的 `stmfts 2-0049: error code: 0x100003`(vendor 布局 `EVENTID_ERROR, data[1]=0x03`,vendor 自己也忽略)。

**持久化(已完成,无需重刷)**:
- `cp stmfts.ko /lib/modules/6.6.0/extra/stmfts.ko`(sda18 持久)、`cp loadko /usr/local/bin/loadko`
- `/etc/systemd/system/stmfts-load.service`(`ExecStart=/usr/local/bin/loadko /lib/modules/6.6.0/extra/stmfts.ko`,`After=systemd-modules-load.service`)→ `systemctl enable stmfts-load.service`
- 已验证:卸载后 `systemctl start stmfts-load.service` 能重新 probe 出 `inputN`。
> DTS 的 `tsp_attn_irq` 改动在源码树里,但**当前运行镜像 DTB 是旧的**(未重刷);因 S-Boot 已设引脚为 EINT,功能不受影响,下次重刷完整镜像会带上。

**调试工具(已放设备 `/root/`)**:`i2cscan`(扫 i2c)、`loadko`(finit_module)、`i2cread.py`(Python 经 `/dev/i2c-2` 任意寄存器读写 + `/dev/mem` 读 `GPA1CON/DAT`)、`kmscube`。

### 4.9.2 触摸「点击变长按」修复（2026-09-12 05:10）✅

**现象**:能拖动窗口,但点应用有时不响应/像长按。
**定位**:
- `/dev/input/event0` 原始事件、`libinput debug-events` 都正常(完整 `TOUCH_DOWN/MOTION/UP`);libinput `list-devices` 识别为 touchscreen(identity 校准)→ 不是丢原始事件、不是 libinput、坐标也对。
- 统计 down→up 时长:修复前 **10ms ~ 2600ms**(大量 >500ms),正好落进 GNOME 长按阈值 → 抬起被延迟。
**根因**:`stmfts.c: stmfts_parse_events()` 按批解析时,遇到 `STMFTS_EV_STATUS(0x16)` / `STMFTS_EV_DEBUG(0xdb)` / `CONTROLLER_READY(0x10)` 就直接 `return`,**把同一批里后面的事件(包括 `STMFTS_EV_MULTI_TOUCH_LEAVE`)整批丢掉了**。vendor 驱动是逐条处理、不中断。S6 固件会把 status/debug 与触摸事件混在同一批 → LEAVE 常被丢,抬起要等下一次触摸才补上 → "长按"。
**修复**:
1. `stmfts_parse_events()`:`STATUS/DEBUG/CONTROLLER_READY/SLEEP_OUT` 改为 `continue`(只对 `NO_EVENT` 结束解析),不再丢后续事件。
2. 按 vendor 补 `BTN_TOUCH` 上报(`input_set_capability(EV_KEY, BTN_TOUCH)`;ENTER/MOTION 报 1,LEAVE 报 0)。
**实测**:修复后 down→up 分布 **11ms ~ 225ms(AVG ~105ms)**,不再有 >500ms 的"长按";点击正常。
产物:`WORKING-66gnome/stmfts.c.touchworking`、`stmfts.ko`(设备 `/lib/modules/6.6.0/extra/stmfts.ko`,开机 `stmfts-load.service` 自动加载)。

### 4.10 桌面完善：SVG 图标 / 渲染器 / 壁纸（2026-09-12 05:40）✅

- **图标缺失(模糊占位)根因**:`/root/gnome.log` 报 `St-WARNING: Failed to load image: Unrecognized image file format`;设备**缺 `librsvg2-common`**(提供 gdk-pixbuf 的 SVG loader),而 Adwaita 图标大多是 SVG → 加载失败显示成模糊占位。装 `librsvg2-common` 后 `loaders.cache` 有 6 条 SVG,重启后 `gnome.log` 的 `Failed to load image` 计数 **0**,图标正常。也顺带修了"设置/监视器打开渲染异常"(它们大量用 SVG 图标)。
- **渲染器更正(重要)**:GNOME Shell **确实在用 Mali GPU**:`gnome-shell` 打开了 `/dev/dri/renderD128`(panfrost)并出现在 panfrost clients;`kmscube -D /dev/dri/card2` 报 `renderer: "Mali-T760 (Panfrost)"`。之前用 `/proc/<pid>/maps` 里有 `libLLVM` 推断 llvmpipe **是误判**——Mesa 25 的 `libgallium` 会无条件链接 LLVM。Mutter 日志 `GPU /dev/dri/card2 selected primary given udev rule`。
- **壁纸**:`/usr/share/backgrounds/gnome/` 不存在(`gnome-backgrounds` 未装),默认 `adwaita-l.jpg` 指向空文件 → 无壁纸。已把壁纸设为 Ubuntu 24.04 默认 `Numbat_wallpaper_light_3480x2160.png`(`picture-options=zoom`;深色模式用 dimmed 版)。`ubuntu-wallpapers`/`ubuntu-wallpapers-noble` 本就已装。
  - **要点**:在 root(串口)shell 里改 GNOME 设置必须用**运行中会话的 D-Bus**,否则不生效:
    ```sh
    P=$(pidof gnome-shell)
    export DBUS_SESSION_BUS_ADDRESS=$(tr '\0' '\n' < /proc/$P/environ | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')
    gsettings set org.gnome.desktop.background picture-uri 'file:///usr/share/backgrounds/Numbat_wallpaper_light_3480x2160.png'
    ```

---

## 5. 显示 port — 已完成 ✅（exynos DRM 真 KMS + Mali）

> **结论(2026-09-11 23:50)**:exynos DRM(EXYNOS7 DECON,命令模式)已打通并被 Mutter 选为 primary。**关键洞察**:Mesa 的 `exynos_dri.so` 内建 **kmsro + panfrost**,所以 EGL 在 exynos 卡上会自动用 **Mali T760 渲染、exynos DECON 扫描输出**。kmscube 实测 **56fps @1440x2560**(旧 simpledrm 路径 31.6fps)。**不再需要移植 DSI/panel**——保留 S-Boot 已初始化的 DSI/panel,只让 exynos DECON 接管扫描。
>
> **实现要点(全在 `exynos7_drm_decon.c` / `regs-decon7.h` / DTS)**:
> 1. **i80 不做 `VIDCON0_SWRESET`**:命令模式下 bootloader 已把 DSI/panel/DECON 触发全部配好;复位会丢状态导致不再发帧 → `decon_init()` 对 i80 直接 return,保留 S-Boot 配置。`decon_commit()` 的 `VIDCON0` 写改为读-改-写(避免清掉其它位)。
> 2. **补 I80 中断/触发**:`regs-decon7.h` 加 `VIDINTCON0_INT_I80_EN=(1<<17)` 和 `TRIGCON(0x6B0)` 位定义;`decon_enable_vblank` 对 i80 置 `INT_I80_EN`;`decon_irq_handler` 对 i80 也调 `drm_crtc_handle_vblank()`(否则 atomic commit 永远 `flip_done` 超时)。
> 3. **SW 触发照抄 simpledrm 的可用序列**(`decon_atomic_flush`,i80):`TRIGCON=(v&~0x3c)|0x7b` → `DECON_UPDATE|=1` → `TRIGCON|=2`。
> 4. **修 mainline bug**:`decon_ctx_initialize()` 在 `ctx->crtc` 创建前调 `decon_clear_channels(ctx->crtc)` → 空指针(上游同样存在,因上游从无板子启用 exynos7-decon)。改成传 `ctx`。
> 5. **连接器**:启用 `CONFIG_DRM_EXYNOS_FIMD=y` + `CONFIG_DRM_EXYNOS_DPI=y`,复用 `exynos_dpi`(用 decon 节点的 `display-timings` 造 encoder/connector,不碰 DSI)。
> 6. **DTS**:decon 加第二个中断 `lcd_sys`(SPI 188)、去 `power-domains`、`i80-if-timings` + `display-timings`;`reserved-memory` 加 **256MB `linux,cma`**(否则 2K framebuffer 分配失败)+ `alloc-ranges` 限制在低 2GB(32 位 DMA 掩码)。
> 7. **Mutter 选卡**:udev tag `mutter-device-preferred-primary` 打在 exynos 卡(`ID_PATH=platform-exynos-drm`)上 → Mutter 日志 `GPU /dev/dri/card2 selected primary given udev rule`。
>
> **开机自动加载**:`/lib/modules/6.6.0/extra/exynosdrm.ko` + `exynosdrm-load.service`(`Before=getty@tty1.service`)。
>
> **遗留**:GNOME 主路径已走 Mali;但 dmesg 仍有 `exynos_drm_gem_prime_import_sg_table: buffer chunks must be mapped contiguously`(某些非连续 dma-buf import 失败,可能让个别缓冲回退;不影响主渲染)。simpledrm(card0)仍在,理论上双输出,可后续在 DTS 里禁用 `simple-framebuffer` 彻底去掉。
>
> **调试法(本轮踩坑)**:DTS 改动可**只刷 dt 区域**(`dt.img` 仅 ~36KB),用设备上的 `/root/dtflash.py` 直接改 `/dev/sda7` 的 dt 段并重算 SHA-1(免传 27MB boot.img)。命令模式调试务必串口 + `sh /root/diag.sh`(用脚本,不要发多行命令会把 shell 卡在续行)。

### 5.0 旧记录(保留下方细节)



### 5.1 现状与阻塞
- `card0 = simple-framebuffer`(patched;能 KMS,且**实际可用 GBM+Mali 渲染**,见 §4.6)
- `card1`/`renderD128` = panfrost(**GPU 渲染节点**)
- **原判断「必须上 exynos DRM」已被 §4.6 推翻**:kmscube 已在 simpledrm 上出画面。exynos DRM 现在只是「更规范的 KMS/atomic、可能 Mutter 更认」的备选。
- **显示时钟已就绪(§4.5)**;`decon` 可随时置 `okay`,`DRM_EXYNOS=m` 保证开机不自动 probe。

### 5.2 主线相关代码位置
- DECON:`drivers/gpu/drm/exynos/exynos7_drm_decon.c`(compatible `samsung,exynos7-decon`,**已在组件表且 `CONFIG_DRM_EXYNOS7_DECON=y`**)。需要的时钟名:**`pclk_decon0`、`aclk_decon0`、`decon0_eclk`、`decon0_vclk`**;IRQ 名 `vsync`(视频)或 `lcd_sys`(i80);命令模式靠 DT 子节点 `i80-if-timings` 判定。
- DSI:`drivers/gpu/drm/exynos/exynos_drm_dsi.c` **只支持 3250/4210/5410/5422/5433**,**无 exynos7**;7420 是命令模式,需要新增数据类型(参考 5433 + vendor `dsim_0` 时钟)。
- panel:`drivers/gpu/drm/panel/` 有 `panel-samsung-s6e3ha2.c`(命令模式,可参考),但无 S6E3FA3/AMS 系列精确匹配。

### 5.3 实验 1（失败，已回滚）
- 加了 `pd_disp@105c4120` + `decon@13930000`(时钟先用 `fin_pll` 桩)+ `CONFIG_DRM_EXYNOS=y` + `&decon{okay}`。
- 结果:**开机卡 Samsung Logo,无串口输出**(极早挂死)。
- 结论:**DECON 开机自动 probe 会 `VIDCON0_SWRESET`/写寄存器,破坏 S-Boot 正在驱动的 DSI/panel → 总线/显示挂死**。DECON 不能单独上、更不能开机自动 probe。
- 产物备份:`WORKING-66gpu/disp-experiment1/`(失败的 `direct_boot_66disp.img` + 当时的 `exynos7.dtsi` + `exynos7420-disp-clocks.txt`)。

### 5.3b 实验 2（CMU_DISP 上线后又卡 Logo → 定位到 `pd_disp`，已解决）
- 加上 CMU_DISP 后(`direct_boot_66disp2.img`,含 `pd_disp` + `cmu_disp`,decon 仍 disabled、DRM=m)仍**卡 Logo**。
- 用 dtb 差分法隔离:把 `pd_disp` 设 `status="disabled"`、`cmu_disp` 保持 enable → `direct_boot_66disp3.img` **正常开机**,且 `clk_summary` 显示 CMU_DISP 全部时钟注册成功(§4.5)。
- **结论:`pd_disp`(exynos5433-pd) 是早挂元凶**,与 CMU_DISP 无关。当前做法:`pd_disp` 永久 disabled,DISP 供电沿用 S-Boot 已开的电源域;`decon` 暂时**不要写 `power-domains`**。
- 差分救砖流程:卡 Logo 后设备仍能进 TWRP(adb `recovery`),`/proc/last_kmsg` 可确认是否早挂(日志停在 `Starting kernel`);直接 `dd` 回好镜像即可。

### 5.4 CMU_DISP port 配方（vendor `drivers/clk/samsung/clk-exynos7420.c` 已抽出）
寄存器偏移(`0x13AD0000` 基址):
```
DISP_LOCK 0x0000 / DISP_CON 0x0100(disp_pll pll_1460x)
MUX_SEL_DISP0-3 0x0200/204/208/20C, MUX_EN 0x0300.., MUX_STAT 0x0400..
DIV_DISP 0x0600, DIV_STAT_DISP 0x0700
ENABLE_ACLK_DISP 0x0800, ENABLE_PCLK_DISP 0x0900,
ENABLE_SCLK_DISP1 0x0A04, ENABLE_SCLK_DISP2 0x0A08
```
关键时钟映射(vendor):
```
disp_pll = pll_1460x @DISP_CON, table_disp, CLK_IGNORE_UNUSED
m_decon0_eclk = MUX(MUX_SEL_DISP3 bit20, parents {usermux_sclk_decon_int_eclk, disp_pll})
m_decon0_vclk = MUX(MUX_SEL_DISP3 bit12, parents {usermux_sclk_decon_vclk, disp_pll})
d_decon0_eclk = DIV(DIV_DISP bit20 w3, parent mout_sub_sclk_decon_int_eclk)
d_decon0_vclk = DIV(DIV_DISP bit12 w3, parent mout_sub_sclk_decon_int_vclk)
d_pclk_disp   = DIV(DIV_DISP bit0 w2, parent usermux_aclk_disp_400)  -> "dout_pclk_disp"
aclk_decon0 = GATE "aclk_decon_int"  parent "aclk_xiu_disp_ro" (ENABLE_ACLK_DISP)
pclk_decon0 = GATE "pclk_decon_int"  parent "dout_pclk_disp" (ENABLE_PCLK_DISP bit31)
decon0_eclk = GATE                    parent "dout_sub_sclk_decon_int_eclk" (ENABLE_SCLK_DISP1)
decon0_vclk = GATE                    parent "dout_sub_sclk_decon_int_vclk"
pclk_dsim0  = GATE "pclk_dsim0"       parent "dout_pclk_disp" (ENABLE_PCLK_DISP bit29)
mipi0_rx/bit, rgb_vclk0(FRATE 300MHz), sclk_dsd, usermux_sclk_dsd ...
```
> 完整提取见 `WORKING-66gpu/disp-experiment1/exynos7420-disp-clocks.txt`(130 行)。
> 还需 CMU_TOP0 的显示 mux(`mout_sclk_decon_int_eclk/ext/vclk` @MUX_SEL_TOP0_DISP bit28/24/20/16/12)` 与 user mux(`um_decon0_eclk` 等 @MUX_SEL_DISP1/DISP3)。

### 5.5 建议的安全调试法
1. `.config` 保持 **`CONFIG_DRM_EXYNOS=m`**(不要 `=y`),开机不自动 probe;`Image` 里不含 exynos DRM。
2. `decon` 节点设 `status="okay"`(让 platform device 建出来),但**不要写 `power-domains=<&pd_disp>`**(pd_disp 一 enable 就早挂);`pd_disp` 永久 disabled。
3. 把 `exynosdrm.ko`(及依赖模块)塞进 rootfs/ramdisk;开机进 Ubuntu shell 后从串口 `insmod`/`modprobe` 手动触发 → 看最后一条 dmesg;挂了直接重启,**不必每次进 TWRP 重刷**。
4. 逐步放开:先只 DECON 无 encoder(应能建 card、CRTC,无 connector)→ 再加 DSI+panel。
5. **每次改动前先备份当前可开机镜像**;串口辅助脚本 `/tmp/acm.py`(发送+回显)/`/tmp/raw_send.py`。

---

## 6. 离线侧载链路（已验证，用来装 GNOME）

设备无网络(只有 `lo`),根文件系统是 96 包的裸 Ubuntu base。用容器离线解析依赖再 TWRP 推包:

```sh
# Mac 侧（Apple Silicon，Docker/Colima 原生 arm64）
# 1) 拉取设备已装包清单（TWRP 下）
adb pull /data/ubuntu/var/lib/dpkg/status ~/.gemini/antigravity/scratch/sideload/target-status
# 2) 容器里用该 status 精确算缺失闭包并下载 .deb
docker run --rm -v "$HOME/.gemini/antigravity/scratch/sideload:/out" ubuntu:24.04 bash -c '
  export DEBIAN_FRONTEND=noninteractive
  cp /out/target-status /var/lib/dpkg/status; mkdir -p /var/lib/dpkg/info
  apt-get update -qq
  apt-get install -y --download-only --no-install-recommends -o Dir::Cache::archives=/out \
    <包名...> '
# 3) 推到 rootfs 内的路径（关键：init 把 sda18 挂到 /mnt 再 chroot 到 /mnt/ubuntu，
#    所以必须放进 /data/ubuntu/... 而不是 /data/...）
adb shell "mkdir -p /data/ubuntu/root/sideload"
adb push ./*.deb /data/ubuntu/root/sideload/
# 4) 重启进 Linux，在 Ubuntu shell 里
cd /root/sideload && dpkg -i *.deb
```

Mesa 包集(51 个,76MB)已备份在 `WORKING-66gpu/mesa-sideload/`;设备上已 `dpkg -i` 安装成功。

---

## 7. 构建 / 打包 / 刷机 速查

- 内核树:`~/.gemini/antigravity/scratch/build/linux-6.6`
- 工具链:`toolchain-aarch64/aarch64-unknown-linux-gnu/bin`;GNU 工具在 `/opt/homebrew/bin`;OpenSSL `/opt/homebrew/var/homebrew/tmp/.cellar/openssl@3/3.6.4`;hostinclude `~/.gemini/antigravity/scratch/hostinclude`。
- **构建**:
  ```sh
  cd ~/.gemini/antigravity/scratch/build/linux-6.6
  OSSL=/opt/homebrew/var/homebrew/tmp/.cellar/openssl@3/3.6.4
  export PATH="/opt/homebrew/bin:$HOME/.gemini/antigravity/scratch/toolchain-aarch64/aarch64-unknown-linux-gnu/bin:$PATH"
  export LC_ALL=C
  gmake ARCH=arm64 CROSS_COMPILE=aarch64-unknown-linux-gnu- \
    HOSTCFLAGS="-I$HOME/.gemini/antigravity/scratch/hostinclude -I$OSSL/include" \
    HOSTLDFLAGS="-L$OSSL/lib" -j8 Image dtbs
  ```
- **打包**:
  ```sh
  BK=~/.gemini/antigravity/brain/1aa1eae7-f290-4c11-ae7f-9444617f1cf3/scratch
  python3 "$BK/mkdtbh.py" build/linux-6.6/arch/arm64/boot/dts/exynos/exynos7420-zenlte.dtb dt.img
  python3 "$BK/mkbootimg_7420.py" build/linux-6.6/arch/arm64/boot/Image \
    lean_ramdisk_wifi.cpio.gz dt.img out.img "<cmdline>"
  ```
- **刷机(TWRP)**:
  ```sh
  adb push out.img /tmp/x.img
  adb shell "dd if=/tmp/x.img of=/dev/block/sda7 bs=4096; sync"
  adb shell "head -c <size> /dev/block/sda7 | sha256sum"   # 校验
  adb reboot
  ```
- 串口:`screen /dev/cu.usbmodem2401 115200` 或自写脚本 `/tmp/acm.py "cmd"`;占用串口的 `screen` 需先 kill。TWRP 下 adb 需等约 4~6 秒。

---

## 8. 当前内核树状态（已编译并刷机验证）

- `.config`:`CONFIG_DRM_EXYNOS=m`,`CONFIG_DRM_EXYNOS7_DECON=y`,`CONFIG_DRM_EXYNOS_DSI=y`,`CONFIG_DRM_PANFROST=y`,`CONFIG_TOUCHSCREEN_STMFTS=m`;USB gadget configfs 已开(serial 走 legacy `g_serial`)。
- `drivers/clk/samsung/clk-exynos7.c`:**CMU_G3D + CMU_DISP 均已完成**(§4/§4.5)。
- `drivers/gpu/drm/tiny/simpledrm.c`:**整帧 blit + 去掉 100ms 刷新 work**(§4.8);含 `sboot_probe` 调试探针和 DECON push。
- `include/dt-bindings/clock/exynos7-clk.h`:TOP0 显示 ID + DISP block。
- `exynos7.dtsi`:`pd_g3d`、`cmu_g3d`、`cmu_disp`、`decon`(disabled、clocks 指向 `&cmu_disp`、仍带 `power-domains=<&pd_disp>`)、`pd_disp`(disabled)。
- `exynos7420-zenlte.dts`:`&gpu{okay}`;触摸相关——`ldo15_reg` always-on、`tsp_avdd`/`tsp_io` fixed、`i2c_tsp`(gpj1)、`i2c_max77838`(gpb0)、`i2c_s2mpb02`(gpd2)、`touchscreen@49`(st,stmfts, IRQ gpa1-6, vdd=ldo15, `pinctrl-0=<&tsp_attn_irq>`)、`&pinctrl_alive` 下 `tsp_attn_irq`(gpa1-6 func 0xf)。
- **ramdisk**:`lean_ramdisk_touch.cpio.gz`(init=`init_sd2`,含 marker 选 systemd/shell + `setup_touch_power`)。
- **触摸驱动**:`stmfts.c` 已按 §4.9.1 适配 S6 固件(复位 `B6 00 23 01` / 轮询 ready / INT `B6 00 1C 41` / 计数式事件读)。设备上已装到 `/lib/modules/6.6.0/extra/stmfts.ko` 并由 `stmfts-load.service` 开机加载。
- **下一步第一件事**:exynos DRM 真 KMS(见 §5),或 WiFi。

---

## 9. 下一步（优先级）

1. ~~CMU_DISP + CMU_TOP0 显示 mux~~ ✅(§4.5)
2. ~~GPU+显示打通 kmscube~~ ✅(§4.6)
3. ~~systemd 引导 + GNOME 上屏~~ ✅(§4.7/§4.8);最新可用镜像 `WORKING-66gnome/direct_boot_66touch8.img`。
4. ~~触摸~~ ✅(§4.9,`/dev/input/event0` 已上,GNOME/libinput 可用,开机自动加载)。
5. ~~exynos DRM 真 KMS~~ ✅(§5)。**不用 DSI/panel 驱动**:保留 S-Boot 的 DSI/panel,只让 DECON 接管 i80 扫描;Mesa kmsro 让 exynos 卡自动用 Mali。kmscube 56fps。
6. (可选)WiFi BCM4359(未开垦)。
7. (可选)G3D 真 PLL(DVFS);DISP 电源域 `pd_disp` 早挂问题;禁用 simpledrm 双输出;prime import 连续内存。

---

## 10. 产物与备份

- **最新可用(含 GNOME + 触摸)** `~/.gemini/antigravity/scratch/WORKING-66gnome/`:
  - **`mct2_boot.img`(当前稳定回退:exynos DRM+GNOME+触摸 + MCT-tick 内核,`maxcpus=1` 单 A53)**
  - `direct_boot_66touch8.img`(exynos DRM 之前的 systemd + GNOME 上屏;触摸供电/IRQ 已修;stmfts=m)
  - **SMP 产物**:`mct2_boot.img`、`a53_dt.img`(仅 A53 的实验 dt)、`setmax.py`、`patchcmd.py`、`exynos_mct.c.smpworking`、`exynos7.dtsi.smpworking`(§11)
  - **SMP 第二轮(2026-09-12 02:30)**:`archtick_boot.img`(物理 timer + arch tick,单核稳定)、`timer_dt.img`(物理 timer dt)、`kpatch.py`(sda7 原地 57 字节补丁脚本)、`gic.py`(`/dev/mem` 读 GIC 寄存器);`exynos7.dtsi.smpworking`/`exynos_mct.c.smpworking` 已更新为当前树(物理 timer + rating 350)
  - **SMP 第三轮 — ★已解决(2026-09-12 04:00)**:`cntpct_boot.img`(最终修复,可热插 **4×A53**)、`arm_arch_timer.c.cntpctfix`(源码)、`kpatch2.py`(archtick→cntpct 原地补丁)、`smpprobe.c`/`smpprobe.ko`(EL/IPI/CNTVCT/CNTPCT 探针)
  - **SMP 第四轮 — ★8 核(2026-09-12 04:30)**:`smp8_boot.img`(最终,可热插 **8 核**)、`a57_dt.img`(A57+A53 dt)、`cpufeature.h.cpucapfix`(源码)、`kpatch3.py`(cpu_mitigations→OFF,1 字节,实验性)、`kpatch4.py`(加 `PERMITTED_FOR_LATE_CPU`,53 段原地补丁)、`cur_a57.img`(A57 DT 基线)
  - **8 核自动 + 基础软件(2026-09-12 04:45)**:`smp8_auto_boot.img`(`maxcpus=8`,开机自动 8 核)、`kpatch5.py`(`maxcpus=1`→`8` 原地补丁,2 字节);基础软件闭包 `/sideload-basic/`(§12)
  - **`stmfts.c.touchworking`**(改造后的驱动源码,§4.9.1)、**`stmfts.ko`**(可加载产物,sha256 `221fb241…`)、**`stmfts-load.service`**(开机加载单元)、`exynos7420-zenlte.dts.touchworking`(含 `tsp_attn_irq`)
  - **exynos DRM 真 KMS**:`exynos7_drm_decon.c.exynoskms`、`regs-decon7.h.exynoskms`、`exynos7420-zenlte.dts.exynoskms`、`exynosdrm.ko`、`exynosdrm-load.service`、`62-mutter-exynos.rules`
  - 设备端:`/root/dtflash.py`(只刷 dt 段)、`/root/diag.sh` + `/root/regdump.py`(寄存器诊断)、`/root/reload.sh`
  - `direct_boot_66touch2.img`(systemd+GNOME 稳定版,触摸未供电,安全回退用)
  - `direct_boot_66touch7.img`(stmfts=m,触摸节点 disabled 的隔离版)
  - `init_sd2.c` / `init_sd2`(marker 选 systemd/shell 的 init)、`simpledrm.c`(整帧 blit + 去 100ms work)、`clk-exynos7.c`、`exynos7.dtsi`
- 早期可用镜像/备份:`~/.gemini/antigravity/scratch/WORKING-66gpu/`
  - `direct_boot_66disp3.img` / `direct_boot_66gpu.img`(无 systemd/GNOME)
  - `direct_boot_66disp2.img`(失败:pd_disp enabled → 卡 Logo,差分对照)
  - `mesa-sideload/`、`kmscube/`、`disp-experiment1/`、`tools/`(`acm.py`/`send_b64.py`)
- 设备 rootfs 内工具:`/root/{i2cscan,loadko,stmfts.ko,kmscube}`;GNOME 依赖闭包在 `~/.gemini/antigravity/scratch/sideload-gnome/`(360 deb + `gnome-debs.tar.gz` + `device-status`)。
- 参考树:`~/.gemini/antigravity/scratch/build/linux-6.10-exynos7420/`(enesuzun2002)。
- vendor 3.10:`~/.gemini/antigravity/scratch/build/kernel/`
  - 触摸:vendor `fts_touch` 驱动 + `arch/arm64/boot/dts/exynos7420-zenlte_common.dtsi`(tsp 节点)、`exynos7420-zenlte_chn_*.dts`(`tsp_io`=s2mps15 LDO15,`/delete-node/ max77838@60`)。
  - 显示:`dsim_0`/`decon_0`、`drivers/clk/samsung/clk-exynos7420.c`、PMU/寄存器宏。
- `/init` 源码:`.../brain/1aa1eae7-f290-4c11-ae7f-9444617f1cf3/scratch/{init_static.c,init_sd2.c,loadko.c,i2cscan.c}`。
- ramdisk:`~/.gemini/antigravity/scratch/lean_ramdisk_touch.cpio.gz`(init=`init_sd2`);重打包 `find . -print0 | cpio --null -o -H newc | gzip -9`。
- 打包/刷机脚本:`.../scratch/{mkdtbh.py,mkbootimg_7420.py}`;串口 `acm.py`、`send_b64.py`。

---

## 11. SMP / 多核 — ★ 全部解决（8 核 = 4×A53 + 4×A57 稳定）

> **现状(2026-09-12 04:30)**:`nproc=8`、`online=0-7`、`dmesg` 0 次 rcu stall、负载压测通过。逻辑映射:CPU0=A53(启动核,MPIDR 0x100);**CPU1-4=A57**(reg 0x0-0x3);**CPU5-7=A53**(reg 0x101-0x103)。两个根因与修复见 §11.9(CNTVCT clocksource)与 §11.10(A57 Spectre-v2 能力冲突)。以下保留完整排查轨迹。

### 11.1 事实
- CPU:4×A57(reg 0x0-0x3)+ 4×A53(reg 0x100-0x103),`enable-method="psci"`。
- **启动核是 A53 0x100**(MIDR `0x410fd032`),而 mainline 原始 DT 只描述 A57 → boot cpu 匹配不上 → `nr_cpu_ids=1`、`cacheinfo: Failed to find cpu0 device node`。
- 加 A53 节点后:`possible`/`present`=0-7;逻辑映射:**cpu0=A53(boot),cpu1-4=A57,cpu5-7=A53**。
- 大核 2.1GHz(A57)/小核 1.5GHz(A53);开机默认单 A53,且**无 cpufreq**(频率由 S-Boot 定,可能偏低)。

### 11.2 本轮实验与结果
1. **改内置 cmdline `maxcpus=8`**(直接等长改内核 Image 明文 + 重算 boot SHA,脚本 `/root/patchcmd.py`):能开机,`possible=0-7` 但 `online=0`。
2. **热插小核(arch timer 当 tick)**:`echo 1 > cpu5/online` → 打印 `CPU5: Booted secondary processor` 后 **RCU stall**(`timer-softirq` 极低),systemd 服务被 watchdog kill → 卡死。
3. **MCT-tick 方案**(对齐 vendor:arch timer 只当 clocksource,MCT 当每核 clockevent):
   - 改 `drivers/clocksource/exynos_mct.c`:`MCT_CLKEVENTS_RATING` arm64 350→**500**(> arch timer 400);local timer 注册循环从 `for_each_possible_cpu` 改为按 DT local timer 数(`of_irq_count - MCT_L0_IRQ`)。
   - DT 的 MCT 节点加 `samsung,local-timers = <0 1 2 3 4 5 6 7>`;`arm-pmu` 节点暂时注释(atlas 引用会编不过)。
   - 结果:`clockevent0 = mct_tick0`(方案生效),**但热插 cpu5 仍 stall**。
4. **开机直接起多核**(仅 A53 的 DT + `maxcpus=2/4`):**卡 logo**(极早挂),说明 secondary bring-up 本身就是阻塞点(不只是 tick)。
5. **大核 A57**:`echo 1 > cpu1/online` 立即挂。
6. **内核里加 PMU 核上电**(`arch/arm64/kernel/psci.c: cpu_psci_cpu_boot`,在 `psci_ops.cpu_on` 前调 `exynos7420_pmu_cpu_power_up(cpu_logical_map(cpu))`,等价 vendor `exynos_cpu_up`):编到 `pmu_boot.img`,**online cpu1 仍 stall**。→ **PMU 上电不是根因**(或不是唯一根因)。
7. **★ 定时器关键发现**:mainline `arch_timer_select_ppi()`(非 HYP 模式 + DT 里有 VIRT PPI 就返回 `ARCH_TIMER_VIRT_PPI`),所以本机日志 `arch_timer: ... (virt)`——**内核用的是虚拟定时器**。而 vendor DT 用 `use-physical-timer`(物理)。虚拟定时器依赖每核 `CNTVOFF`,secondary 核很可能没配对 → 很可能就是 stall 主因。**修法:DT 的 timer 节点用 `interrupt-names` 省略 "virt"**(使 `arch_timer_ppi[VIRT]=0`),内核即退到非安全物理定时器(PPI 14)。注意 `arm,cpu-registers-not-fw-configured` 在 arm64 上被 `IS_ENABLED(CONFIG_ARM)` 包住、**对 arm64 无效**。
8. **物理定时器实机验证 `(phys)`（推翻 #7 假设）**:把 DT timer 节点改成 `interrupt-names = "sec-phys","phys","hyp-phys"`(删掉 PPI 11/virt),重编 dtb、用 `/root/dtflash.py` 只刷 dt 段。开机日志变 `arch_timer: cp15 timer(s) running at 24.00MHz (phys)` → **物理定时器已生效**。但 `echo 1 > cpu1/online` **仍然 stall**。
9. **★ 决定性实验:换 arch timer 当 tick（CPU1 仍 0 ticks）**:把 `MCT_CLKEVENTS_RATING` 从 500 降到 350(低于 arch timer 400),使 `arch_sys_timer` 成为 per-CPU clockevent(`/proc/timer_list` 证实 `Per CPU device 0: Clock Event Device: arch_sys_timer`)。`echo 1 > cpu1/online` → 打印 `CPU1: Booted secondary processor 0x0000000101`、`ncpus=2`,但 `rcu: 1-...!: (0 ticks this GP) ... Possible timer handling issue on cpu=1`。**结论:虚拟/物理 arch timer、MCT 三种 tick 在 CPU1 上全都不触发 → 不是定时器问题,而是 CPU1 收不到任何中断。**

### 11.2b 附加:在线 CPU1 后系统级联死锁
- `echo 1 > cpu1/online` 前台执行会把 CPU0 也带死(整机黑屏、串口无输出、`SysRq`/break 无效),只能长按电源强制重启。用后台 `(echo 1 > ...) &` 才能拿到 RCU stall 日志。
- 说明 secondary bring-up 路径里某处持有全局锁后卡死(非常像等待某个永不发生的中断/完成量),不只是"CPU1 自己 idle 不醒"。

### 11.3 历史假设（已降级，保留作参考）
- vendor `arch/arm64/mach-exynos/pmu.c: exynos_cpu_up()` **在拉起核前直接写 PMU 给核上电**:
  ```c
  EXYNOS_PMU_CPU_CONFIGURATION(nr) = PMU_base(0x105c0000) + 0x2000 + nr*0x80
  /* atlas core0-3 = 0x2000 + n*0x80 ; apollo core0-3 = 0x2200 + n*0x80
     所以 nr = core + 4*cluster */
  LOCAL_PWR_CFG = (0xF << 0)   // 置位即上电
  ```
  vendor 的 PSCI/cpufreq 链路会先给核/簇上电再 `CPU_ON`;mainline 没有这步 → `PSCI CPU_ON` 挂。
- vendor `drivers/cpufreq/exynos7420-{apollo,atlas}-cpufreq.c` 使能 **CMU_CPU** 时钟(`mout_apollo_pll`/`mout_apollo`、`EXYNOS7420_DIV_APOLLO0/1`、`APOLLO_PLL_CON1` 等);mainline 无 CMU_CPU 驱动。**且没有 cpufreq → 单核频率也可能没拉满。**
- vendor 还有 `pm_domains-exynos7420.c`(簇/域)与 `exynos-powermode*.c`。
- CCI-400 一致性:vendor DT 无 cci 节点(可能固件管),待查。

### 11.4 userspace 关键验证（方向已明确，待确认稳定性）
- 用 `/dev/mem` 直接写 **apollo core1(逻辑 cpu5)的 PMU 寄存器 `0x105c2280 |= 0xF`**,再 `echo 1 > cpu5/online` → **成功 `nproc=2`**(此前同样操作必 stall)。
  - A53/apollo 各核 PMU 寄存器:core0=`0x105c2200`,core1=`0x105c2280`,core2=`0x105c2300`,core3=`0x105c2380`
  - A57/atlas:core0=`0x105c2000`,core1=`0x105c2080`,core2=`0x105c2100`,core3=`0x105c2180`
- 最后一次"是否稳定"的检查被打断。**下一步要重做该验证**:若"PMU 上电 + online"长期稳定,则修复=在内核里于 `PSCI CPU_ON` 前给核写 PMU 上电。

### 11.5 当前源码树改动（可能与运行镜像不一致，注意核对）
- `drivers/clocksource/exynos_mct.c`:local timer 注册按 DT 数;`MCT_CLKEVENTS_RATING` 现为 **350**(为让 arch timer 当 tick 的测试值;原 arm64 值 500、`MCT_CLKSOURCE_RATING` 350)。
- `arch/arm64/kernel/psci.c`:**新增 `exynos7420_pmu_cpu_power_up()` 并在 `cpu_psci_cpu_boot()` 里 `psci_ops.cpu_on` 之前调用**(写 `0x105c2000 + (core+4*cluster)*0x80 |= 0xF`)。备份 `WORKING-66gnome/psci.c.smpworking`。**注意:vendor 的 `exynos_cpu_up` 只用于 cpuidle `wakeup_from_c2`,vendor 的 PSCI `cpu_boot` 并不预上电 → 这个补丁很可能是多余/有害的。**
- `arch/arm64/boot/dts/exynos/exynos7.dtsi`:加 A53 节点(0x100-103)+ `samsung,local-timers`;**A57(atlas)节点已启用**(`cpu@0-3`,`next-level-cache=<&atlas_l2>`;电源由 psci.c 的 PMU 补丁负责);`arm-pmu` 暂注释;timer 节点已改为 `interrupt-names = "sec-phys","phys","hyp-phys"` 且删掉 PPI 11(用物理定时器,`(phys)` 已实机验证)。
- **`arch/arm64/include/asm/cpufeature.h`（★A57 修复,§11.10）**:`ARM64_CPUCAP_LOCAL_CPU_ERRATUM` 增加 `ARM64_CPUCAP_PERMITTED_FOR_LATE_CPU`,允许"系统未启用、但迟到 CPU 自带"的本地 erratum(异构 A53/A57);否则 A57 一上线就被 `verify_local_cpu_caps()` 判 Spectre-v2 冲突 → `cpu_die_early()`。备份 `WORKING-66gnome/cpufeature.h.cpucapfix`。
- **`drivers/clocksource/arm_arch_timer.c`（★最终修复,§11.9）**:`arch_counter_register()` 里 clocksource 原本在非 hyp(`EL1`)下强制用 CNTVCT;改为**当选用物理 timer PPI(`arch_timer_uses_ppi != ARCH_TIMER_VIRT_PPI`)时用物理计数器 CNTPCT,并把 `clocksource_counter.vdso_clock_mode = VDSO_CLOCKMODE_NONE`（关 CNTVCT vDSO）**。备份 `WORKING-66gnome/arm_arch_timer.c.cntpctfix`。
- `.config` 未动(cmdline 仍 `maxcpus=1`);DeviceTree 里的 `bootargs` 未动,内核内置 cmdline 是 `CONFIG_CMDLINE_FORCE`。

### 11.6 产物 / 脚本
- **`WORKING-66gnome/mct2_boot.img`** = 稳定回退镜像(MCT-tick 内核 + A53+A57 DT + `maxcpus=1`;`nproc=1`,`clockevent0=mct_tick0`)。
- **`WORKING-66gnome/pmu_boot.img`** = 加了内核 PMU 核上电补丁 + A53-only DT + `maxcpus=1`(online cpu1 仍 stall)。
- **`WORKING-66gnome/archtick_boot.img`** = 物理 timer DT + `arch_sys_timer` 当 tick 的内核(中间产物;因 CNTVCT 问题 online cpu1 仍 stall);同目录 `timer_dt.img` 为对应 dt。
- **`WORKING-66gnome/cntpct_boot.img`(4×A53 里程碑)** = archtick + **CNTPCT clocksource 修复**;boot SHA-1 `8044857d42efc9c970f4a65d6c4d5d252dd8146a`。
- **★ `WORKING-66gnome/smp8_boot.img`(最终 8 核)** = cntpct + **cpufeature 异构 erratum 修复** + A57 DT;boot SHA-1 `2863d002045edb1fb00e85163254c44fece5340c`;**设备 sda7 当前即此内核**。
- **就地补丁/探针(本轮)**:`kpatch2.py`(archtick→cntpct 的 sda7 原地补丁,基线 SHA `7abc6331…`→目标 `8044857d…`);`smpprobe.c/.ko`(读 `CurrentEL/MPIDR/DAIF/CNTPCT/CNTVCT/CNTP_CTL/TVAL`,在 CPU1 上跑 kthread——正是它定位了 CNTVOFF 每核不一致)。
- **本轮新脚本**:主机 `/tmp/{kpatch.py,gic.py,sysrq.py,timer_dt.img}`;设备 `/root/{kpatch.py,gic.py}`。
  - `kpatch.py`:基线(dtflash 后的 sda7,SHA `c35257bd…`)与新镜像只差 **57 字节**,直接在 sda7 原地打 11 段小补丁并重算 SHA(免传 27MB boot.img;含旧/新字节与 SHA 校验)。
  - `gic.py`:经 `/dev/mem` 从 CPU0 读 `GICD_CTLR/TYPER/IGROUPR0/ISENABLER0`、`GICC_CTLR/PMR`(见 §11.7)。
  - `sysrq.py`:串口 `break`+sysrq(实测在整机死锁时无效)。
- `WORKING-66gnome/{psci.c.smpworking, exynos_mct.c.smpworking, exynos7.dtsi.smpworking, a53_dt.img, setmax.py, patchcmd.py, findcmd.py}`。
- `/tmp/{mct2_boot.img, pmu_boot.img, a53_dt.img, rec_kernel, rec_ramdisk.cpio.gz, setmax.py, patchcmd.py}`。
- 设备端:`/root/{dtflash.py(刷dt段), patchcmd.py(maxcpus→8), setmax.py <n>, a53_dt.img, new_dt.img, i2cread.py(可 /dev/mem 读写 PMU)}`。
- vendor 参考:`build/kernel/arch/arm64/mach-exynos/{pmu.c, pm_domains-exynos7420.c, exynos-powermode*.c}`、`drivers/cpufreq/exynos7420-{apollo,atlas}-cpufreq.c`、`include/mach/regs-pmu-exynos7420.h`。
- **虚拟磁盘**:内核源码在 `~/.gemini/antigravity/scratch/kernel_build.sparseimage`(挂载点 `~/.gemini/antigravity/scratch/build`)。**若 `build/` 只剩 `.config`,说明镜像没挂** → `hdiutil attach -mountpoint ~/.gemini/antigravity/scratch/build ~/.gemini/antigravity/scratch/kernel_build.sparseimage`。

### 11.7 中间阶段结论（2026-09-12 02:30）★
> **⚠ 已被 §11.9 推翻/取代**:后续 `smpprobe.ko` 探针证明 CPU1 **能收 SGI/IPI、EL=1、且 tick 在跑**(`CNTP_TVAL` 被重编程);"secondary 收不到任何中断 / 安全态不一致"是误判。真正根因是 **CNTVCT clocksource**。以下保留排查轨迹。
- **定时器彻底排除**:虚拟 arch timer(PPI 11)/ 物理 arch timer(PPI 14)/ MCT 本地 timer(SPI 116+)三种 tick 在 CPU1 上**都不触发**。
- **PMU 核上电不是根因**:内核补丁版与 userspace 版都无法让 CPU1 稳定工作(userspace 那次 `nproc=2` 不可复现)。
- **真正症状**:CPU1 `Booted secondary processor 0x101` 成功、`present` 置位、`ncpus=2`,但**零中断**——RCU `0 ticks this GP`、`timer-softirq≈0`,连 resched IPI 都醒不了它;前台 online 还会拖死 CPU0(§11.2b)。
- **GIC 实测**(`/root/gic.py`,经 `/dev/mem` 从 CPU0 读):
  ```
  GICD_CTLR=0x1        GICD_TYPER=0xfcef      GICD_IIDR=0x200143b
  GICD_IGROUPR0=0x0    GICD_ISENABLER0=0x4000feff
  GICD_IPRIORITY0=0xa0a0a0a0   GICD_ITARGETSR0=0x10101010
  GICC_CTLR=0x1        GICC_PMR=0xf0          GICC_IIDR=0x202143b
  ```
  `GICD_CTLR=0x1` 只 EnableGrp0、`GICC_CTLR=0x1` 只 EnableGrp0、`IGROUPR0=0x0`(SGI/PPI 全在 Group0)→ **整个 GIC 只在 Group0(安全态)工作**;而 CPU0 能正常收中断,说明 **CPU0 运行在安全态**。
- **最可能根因**:PSCI `CPU_ON` 把 secondary 核放进**非安全态**;GIC 只投递 Group0(安全)中断,于是 CPU1 永远收不到任何 IRQ → idle/RCU stall,并在 bring-up 路径死锁全局锁导致整机黑屏。vendor 能跑 8 核,说明其 secondary 进入的安全态与 GIC 配置匹配(或固件另做了 Group/安全态处理)。
- vendor GIC DT 差异(供参考):vendor `reg` 的 CPU 接口是 `0x1000`(我们 `0x2000`),且带维护中断 `interrupts = <1 9 0xf04>`(我们没有)。

### 11.8 下一步（SMP）
1. **★ 先验证"CPU0 安全态 / CPU1 非安全态"**:在 secondary 启动早期打印 `CurrentEL` 及读取 `SCR_EL3`(需给 `arch/arm64/kernel/head.S` / `smp.c` 加探针,或用一个早期 `pr_info`)。这是当前最硬的未知量,决定后面怎么修。
2. **按安全态结论二选一**:
   - 若 CPU1 确实非安全态 → 需要让 GIC 把中断配到 **Group1**(CPU0 也要),即 Linux 应以非安全态运行;这通常要求固件/ATF 正确配置 GIC,可能要 SMC 或换 `method`/PSCI 版本。
   - 若 CPU1 也在安全态 → 问题在 `gic_cpu_init` 未真正 enable CPU1 的 CPU 接口,需加打印确认并排查 GICC 基址/映射。
3. **对齐 vendor GIC 节点试一把**(低成本 DTB):`cpu` 区改 `0x1000` + 加维护中断 `PPI 9`(用 dtflash 只刷 dt)。
4. **CMU_CPU / 簇域**:vendor `drivers/cpufreq/exynos7420-{apollo,atlas}-cpufreq.c` 会开 CMU_CPU 时钟;secondary 的 GIC 时钟若依赖它也会出此症状,值得并行排查。
5. **回退**:单核稳定用 `WORKING-66gnome/mct2_boot.img`(MCT tick);DTS 改动用 `/root/dtflash.py` 只刷 dt 段;内核改动用 `kpatch2.py` 式原地补丁(基线 SHA 必须匹配)或 TWRP 刷 sda7。

### 11.9 ★ 最终根因与修复（2026-09-12 04:00）— 4×A53 稳定

**根因**:
- arm64 `drivers/clocksource/arm_arch_timer.c: arch_counter_register()` 在**非 hyp(`EL1`)系统上强制用虚拟计数器 CNTVCT** 作为 clocksource/vDSO:
  ```c
  if ((IS_ENABLED(CONFIG_ARM64) && !is_hyp_mode_available()) ||
      arch_timer_uses_ppi == ARCH_TIMER_VIRT_PPI) { /* rd = cntvct */ }
  ```
  本机 `EL1`、非 hyp → 恒用 CNTVCT,与 timer 用哪个 PPI(phys/virt)无关。
- Exynos7420 固件**没正确设置 `CNTVOFF`**,且**每个核不同**。`smpprobe.ko` 实测:
  ```
  cpu0: CNTPCT=3470464567  CNTVCT=298699418000937991    (CNTVCT-CNTPCT ≈ 2.99e17)
  cpu1: CNTPCT=3470463485  CNTVCT=6083507184103982588   (CNTVCT-CNTPCT ≈ 6.08e18)
  cpu1: CNTP_TVAL 20ms 内被重编程(说明 tick 其实在跑);DAIF=0(IRQ 已开);EL=1
  cpu1: CNTPCT 20ms 递增 492058(≈24.6MHz,全核一致)
  ```
  → **CNTPCT 全核一致**;CNTVCT 每核一个巨大且不同的常数偏移。
- 单核:同核偏移恒定,timekeeping 用差值 → 正常。
- 加第二个核:timekeeping/`sched_clock` 在不同核上读 CNTVCT,跨核差值巨大 → jiffies 乱跳、RCU `0 ticks`、全局锁死锁、整机黑屏。
- (旁证:`GICD_CTLR=0x1/GICC_CTLR=0x1/IGROUPR0=0` 的 Group0 是 mainline GICv2 正常行为,不是根因;CPU1 的 IPI 与 PPI 使能都正常。)

**修复**(`arm_arch_timer.c`,见 `WORKING-66gnome/arm_arch_timer.c.cntpctfix`):
1. `arch_counter_register()`:当 `arch_timer_uses_ppi != ARCH_TIMER_VIRT_PPI`(即用物理 timer)时走**物理计数器**分支(`arch_counter_get_cntpct`),不再用 CNTVCT;
2. 该分支置 `clocksource_counter.vdso_clock_mode = VDSO_CLOCKMODE_NONE`(关掉基于 CNTVCT 的 vDSO;物理计数器 EL0 不可读,否则用户态与内核时间不一致)。

**实测结果(修复后,sda7 = `cntpct_boot.img`)**:
```
echo 1 > /sys/devices/system/cpu/cpu1/online   # → nproc=2, 无 stall
echo 1 > cpu2/online; echo 1 > cpu3/online     # → online=0-3, nproc=4, dmesg rcu stall=0
8 路忙循环压测 10s                              # → 0 stall, uptime 正常, 串口流畅
```

**后续**:
1. A57 大核(需在 DT 恢复 A57 节点;可能还要 CMU_CPU/簇上电)。
2. 若要 SMP 开机自动生效,把内置 cmdline 的 `maxcpus=1` 改成 4/8(`/root/setmax.py`/`patchcmd.py`),或在 rootfs 加开机热插脚本。
3. 本修复后 **不提供 arch timer vDSO**(`VDSO_CLOCKMODE_NONE`),`clock_gettime` 走 syscall,性能影响极小。
4. 可选:若能通过固件/SMC 正确设置 `CNTVOFF`,则可恢复 CNTVCT+vDSO;当前不需要。

### 11.10 ★ A57 大核修复（2026-09-12 04:30）— 8 核稳定

**现象(恢复 A57 DT 后)**:`echo 1 > cpu1/online` 时:
```
CPU features: CPU1: Detected conflict for capability 58 (Spectre-v2), System: 0, CPU: 1
CPU1: will not boot
CPU1: failed to come online
CPU1: died during early boot
```

**根因**:`arch/arm64/kernel/cpufeature.c: verify_local_cpu_caps()` 对每项能力做一致性校验。Spectre-v2 的类型是 `ARM64_CPUCAP_LOCAL_CPU_ERRATUM`(只含 `SCOPE_LOCAL_CPU | OPTIONAL_FOR_LATE_CPU`,**不含** `PERMITTED_FOR_LATE_CPU`):
```c
if (system_has_cap) { ... } else {
    if (cpu_has_cap && !cpucap_late_cpu_permitted(caps))  // ← A57 命中后 die
        break;
}
```
- 启动核 A53 的 `has_spectre_v2()` 返回 false(硬件/固件判定未受影响)→ 系统级能力=0;
- A57 的 `has_spectre_v2()` 返回 true → "迟到的 CPU 有、系统没有" → `cpu_die_early()`。
- 这是 mainline 对**异构 big.LITTLE**(A53/A57 的 Spectre-v2 状态不同)的固有限制;且 6.6 的 `has_spectre_v2()` 只看硬件 MIDR / 固件 SMC,**不认 `mitigations=off`/`nospectre_v2`**(所以先试的 `cpu_mitigations` 置 OFF 无效,见 `kpatch3.py`)。

**修复**:`arch/arm64/include/asm/cpufeature.h` 给 `ARM64_CPUCAP_LOCAL_CPU_ERRATUM` 加 `ARM64_CPUCAP_PERMITTED_FOR_LATE_CPU`:
```c
#define ARM64_CPUCAP_LOCAL_CPU_ERRATUM		\
	(ARM64_CPUCAP_SCOPE_LOCAL_CPU | ARM64_CPUCAP_OPTIONAL_FOR_LATE_CPU | \
	 ARM64_CPUCAP_PERMITTED_FOR_LATE_CPU)
```
→ 允许迟到的异构核"自带"本地 erratum 而系统未启用(代价:该核不做该项缓解,本移植场景可接受)。该改动只改能力表的 `.type` 字段(`.rodata` 数据),**不改变代码布局**,故可用 sda7 原地补丁(`kpatch4.py`,53 段 / 96 字节)。

**实测(修复后,`smp8_boot.img`)**:
```
echo 1 > cpu1/online     # CPU1: Booted secondary processor 0x0 [0x411fd070]   ← A57
for c in 2 3 4; do echo 1 > cpu$c/online; done   # A57 全上 → online=0-4, nproc=5
for c in 5 6 7; do echo 1 > cpu$c/online; done   # A53 补齐 → online=0-7, nproc=8
12 路忙循环压测 10s                               # 0 stall, uptime 正常
```
用户主观反馈:**流畅度明显上升**。

**后续**:
1. **开机自动起 8 核**:把内置 cmdline `maxcpus=1` 改成 8(`/root/setmax.py`/`patchcmd.py` 改内核 Image 等长明文 + 重算 boot SHA),或在 rootfs 加开机热插脚本(`for c in 1..7; do echo 1 > /sys/devices/system/cpu/cpu$c/online; done`)。
2. `arm-pmu`(perf/PMU)仍注释;要 perf 需补 A53/A57 PMU 节点并解决 `atlas` 引用。
3. CMU_CPU / cpufreq / DVFS 仍未做(频率由 S-Boot 定,可能未拉满)。

---

## 12. 基础软件 — 离线侧载（2026-09-12 04:45）✅

设备无网络,继续用 §6 的 Docker 依赖闭包 + TWRP adb 侧载流程。

**本次安装**(arm64 Docker `ubuntu:24.04`,以设备当前 `dpkg status` 为目标状态算闭包):
- **设置**:`gnome-control-center`
- **监视器**:`gnome-system-monitor`、`htop`
- **常用 CLI**:`vim nano git curl wget less file tree unzip rsync sudo bash-completion man-db net-tools iputils-ping dnsutils ca-certificates usbutils i2c-tools pciutils`
- 闭包共 **134 个 .deb / 61.5MB**,产物在 `~/.gemini/antigravity/scratch/sideload-basic/`(`basic-debs.tar.gz` 约 61MB)。

**流程(实测)**:
```sh
# 1) 拉设备当前 dpkg status(串口 /tmp/recv_b64.py 得到 gzip 的 status → gunzip)
python3 /tmp/recv_b64.py /var/lib/dpkg/status /tmp/device-status-now
gzip -dc /tmp/device-status-now > ~/.gemini/antigravity/scratch/sideload-basic/target-status
# 2) Docker 算闭包并下载(同 §6)
docker run --rm -v .../sideload-basic:/out ubuntu:24.04 bash -c '
  cp /out/target-status /var/lib/dpkg/status; mkdir -p /var/lib/dpkg/info; apt-get update -qq
  apt-get install -y --download-only --no-install-recommends -o Dir::Cache::archives=/out
    gnome-control-center gnome-system-monitor htop vim nano git curl wget less file tree
    unzip rsync sudo bash-completion man-db net-tools iputils-ping dnsutils ca-certificates
    usbutils i2c-tools pciutils'
# 3) 重启进 TWRP,adb push 到 sda18 里的 ubuntu rootfs(注意是 /data/ubuntu/...)
adb shell "mkdir -p /data/ubuntu/root/sideload-basic"
adb push sideload-basic/*.deb /data/ubuntu/root/sideload-basic/
# 4) 重启回 Linux,安装
cd /root/sideload-basic && dpkg -i *.deb      # 一次成功:RC=0, Setting up=134, dpkg error=0
```

**结果**:`gnome-control-center`(设置)、`gnome-system-monitor`(监视器)、`htop` 及 CLI 工具全部可用,GNOME 应用列表里已出现(用户确认"确实多了几个应用")。无缺依赖。

---

## 13. 电池 / 充电检测（MAX77833 fuel gauge）— 2026-09-12 ✅

**硬件（SM-G9280 / zenlte CHN）**:
- 充电+燃料计是 **MAX77833**:MFD 在 I2C **0x66**（vendor `hsi2c@13650000`）;燃料计是它的子设备,**I2C 地址 `0x36`**（= `0x6C >> 1`,见 vendor `drivers/mfd/max77833.c` 的 `I2C_ADDR_FG`）。
- 寄存器 **16-bit,地址按 [低字节, 高字节] 发送**,读回 2 字节 `LSB,MSB`:
  - `SOCREP=0x000C`（MSB=整数 %）→ 实测 `0x62A8` = 98%
  - `VCELL=0x0012`（vendor 公式:`(d&0xFFF)*78.125µV` + `((d&0xF000)>>4)` 段）→ 4.34V
  - `CURRENT=0x0014`（有符号,±312.5µA/LSB）→ 充电为正、放电为负
- 实测（G9280,USB 供电）:`cap=98% v=4341mV i=119mA`（charging）;供电变化后电流变负 → discharging。

**实现**:
- 写了最小 mainline `power_supply` 驱动 `WORKING-66gnome/max77833_fg.c`（out-of-tree 模块,`i2c_device_id="max77833_fg"`）:
  - 从 0x36 读 SOCREP/VCELL/CURRENT;导出 `STATUS/PRESENT/CAPACITY/CAPACITY_LEVEL/VOLTAGE_NOW/CURRENT_NOW/TECHNOLOGY/HEALTH`。
  - **充放电判定不靠电流符号**（会在 0 附近抖动）,而是读 **MAX77833 充电器（0x66）的 `DTLS_00=0x83` bits[7:6],`==3` 表示 VBUS 有效**:有 VBUS → Charging（满则 Full）,无 → Discharging。`INT_OK(0x82)` 可看 `VBUSOK/CHGOK/TOPOFF`（实测 0xdd）;`PMICID(0x20)=0x33`。
  - 每 **2 秒**轮询（原 10s 有延迟）。
- **不改 DTS**:加载模块后用 sysfs 实例化:`echo max77833_fg 0x36 > /sys/bus/i2c/devices/i2c-0/new_device`（i2c-0 = i2c-gpio-1,即 MAX77833 所在总线,扫描可见 0x25/0x36/0x66）。
- **持久化**:`/lib/modules/6.6.0/extra/max77833_fg.ko` + `/etc/systemd/system/max77833-fg-load.service`（`loadko` + `new_device`）,已 `systemctl enable`。
- **GNOME**:UPower 1.90（已装）自动认到 `/org/freedesktop/UPower/devices/battery_max77833_fuelgauge`,`state=charging/discharging`、`percentage`、`icon-name=battery-*-symbolic` → GNOME 顶栏显示电池图标与电量。

**注意（LDO/DCDC 别弄错）**:
- 本驱动**不碰任何 LDO/DCDC/regulator**,MAX77833 由电池/PMIC 供电。G9280 上 `tsp_io` 是 **s2mps15 LDO15**（不是别的变体的 max77838 LDO2!）——变体差异勿混用。
- MAX77833 的 `SAFEOUT1/2`（vendor regulators 节点）暂未纳入;实际充电控制（充放电电流设定）需要 charger 驱动,当前只做**检测/显示**。

**验证**:
```sh
cat /sys/class/power_supply/max77833-fuelgauge/uevent
upower -i $(upower -e | grep battery | head -1)
```

---

## 14. USB 拔线死机修复（内核 console 挂在 gadget 上）— 2026-09-12 ✅

**现象**:一直插着 USB 正常;一拔掉 USB 线,整机死机（需强制重启）。
**排查/结论**:
- 内核内置 cmdline 有 `console=ttyGS0,115200`,即**内核 console 也输出到 USB gadget 串口**。拔线时 gadget 断开,console 写路径/`gs_close` 卡住 → 死机。
- boot 时另可见 `WARNING: ... u_serial.c:688 gs_close+0x114`（`WARN_ON(1)`,gadget 串口 refcount 的小 bug）,但不是死机主因。
**修复**:内置 cmdline 去掉 `console=ttyGS0,115200`（原地等长补丁 `kpatch6.py`,只留 `console=tty0`）。串口 `getty@ttyGS0` 仍在 → **shell 照常用**,只是内核 log 不再实时写 USB（可用 `dmesg`/`journalctl`）。
**实测**:改后拔线不再死机（屏幕/GNOME 存活）。镜像 `WORKING-66gnome/smp8_nocon_boot.img`。
> 备注:若要恢复串口实时内核 log,可把 console 加回,或加 `netconsole`。

---

## 15. 桌面完善（二）：温度 / 磁盘 / 电源菜单 / htop-freq / DVFS（2026-09-12）

### 15.1 温度检测（已完成 ✅）
- 主线 `exynos_tmu` 驱动**内置且支持 `samsung,exynos7-tmu`**,但板级 DTS 里 `&tmuctrl_0 { status = "disabled"; }` → 没 probe。
- 改为 `status = "okay"`（`exynos7420-zenlte.dts`）,重建 dtb（`WORKING-66gnome/tmu_dt.img`）并 dtflash。开机后:
  - `/sys/class/thermal/thermal_zone0/type = cluster0-thermal`,`temp = 45000`（45.0℃）✅
  - 温度源 `tmu@10060000`,`readw(base+0x40) & 0x1ff`。
  - dmesg 有 `exynos-tmu 10060000.tmu: Regulator node (vtmu) not found`（可选 regulator,不影响）。
- 注:thermal 的 hwmon 未自动生成（`CONFIG_THERMAL_HWMON=y` 也没出现 `/sys/class/hwmon/hwmonN`）。用桥接模块 `exynos_tmu_hwmon.c`（`thermal_zone_get_zone_by_name("cluster0-thermal")`+`thermal_zone_get_temp` → `hwmon_device_register_with_info`）导出 `temp1_input`。**两个坑**：① `hwmon_device_register_with_info(NULL,…)` 返回 `-EINVAL`（`dev` 必须非空）→ 否则 `finit_module` 静默 EINVAL,改用 `get_cpu_device(0)`;② htop 只用 `tempDriverPriority()` 白名单芯片名（`coretemp`/`via_cputemp`/**`cpu_thermal`**/`k10temp`/`zenpower`/`acpitz`）,所以 hwmon 名必须叫 **`cpu_thermal`** 才显示。持久化:`/lib/modules/6.6.0/extra/exynos_tmu_hwmon.ko` + `exynos-tmu-hwmon.service`（已 enable）。

### 15.2 GNOME About 磁盘容量（已装 udisks2）
- `gnome-control-center` 链接 `libudisks2` → About 的磁盘容量来自 **udisks2 守护进程**。设备原先只有 `libudisks2-0`,没装 `udisks2`。
- 离线装 `udisks2`（30 deb/3.5MB,设备 `/root/sideload-udisks`）,`systemctl enable --now udisks2` → active。About 磁盘容量应已显示。

### 15.3 GNOME 关机/重启菜单（已完成 ✅）
- 电源菜单需要 `org.gnome.SessionManager`。真 `gnome-session` 在本系统起不来（见末注）。最终**不用 gnome-session**,改用一个最小 **Python D-Bus shim** 在 direct gnome-shell 的 session bus 上提供 `org.gnome.SessionManager`。
- shim(`/usr/local/bin/sessionmanager-shim`,`WORKING-66gnome/sessionmanager-shim`)实现 gnome-shell 实际用到的接口:`Logout(u)/Shutdown()/Reboot()/CanShutdown()->b/IsInhibited(u)->b` + 属性 `SessionIsActive`;`Shutdown/Reboot` 转调 **system bus 的 logind**(`PowerOff/Reboot(False)`),`Logout` → `TerminateSession($XDG_SESSION_ID)`。
- `/root/.bash_profile`:`exec dbus-run-session -- bash -c '/usr/local/bin/sessionmanager-shim & exec gnome-shell --wayland --display-server --no-x11'`。
- **坑1**:dbus-python 1.3.2 **没有 `dbus.service.property`**,属性要用 `org.freedesktop.DBus.Properties.Get/GetAll` 实现;gnome-shell 还会调 `Setenv/Unsetenv`(需 no-op 提供)。
- **坑2**:`dbus.service.BusName(...)` 的返回值**必须保存**,否则被 GC 回收 → 名字释放、菜单不出现。
- **★ 真正的 reboot 卡死根因**:不是复位寄存器。`kernel_restart → device_shutdown()` 里 **UFS 驱动 `ufshcd_wl_shutdown`(`ufs_device_wlun` 驱动的 `.shutdown`)访问已关的 UFS 寄存器 → synchronous external abort → panic**(PC `exynos_ufs_ctrl_clkstop`)。修法:`exynos7420_reboot.ko` 在 `register_reboot_notifier`(先于 `device_shutdown` 执行)里遍历 platform 设备子树,找到 `driver->name=="ufs_device_wlun"` 的设备并把 `driver->shutdown=NULL` → 跳过它。
- 复位本身:模块 `restart_handler` 先调 **PSCI SMC `0x84000009`(SYSTEM_RESET)**,回退清 `MASK_WRESET(0x410)` + 写 `SWRESET(0x400)=1`;poweroff 用 `sys_off` 清 `PS_HOLD_CONTROL(0x330c)` 的 output-high 位。DT 里本已有标准 `syscon-reboot/poweroff`,但被 UFS shutdown 挡住,所以模块的 notifier 是关键。
- 持久化:`exynos7420-reboot.service`(enabled)+ `/lib/modules/6.6.0/extra/exynos7420_reboot.ko`。
- 末注:真 `gnome-session` 曲线失败——系统没装 `dbus-user-session`(已离线装)、`systemd --user` 不持有 `systemd1`、`/usr/bin/gnome-session` 包装脚本会 `exec bash -l` 再次 source `.bash_profile` 递归 fork;`dbus.socket` 已 enable。getty@tty1 autologin 在 `/etc/systemd/system/getty@tty1.service.d/autologin.conf`。

### 15.4 htop 真实 freq — 真·双簇 DVFS（已完成 ✅）
- **放弃旧假驱动 `exynos_cpufreq_static.ko`**（会 oops/挂）。新写自包含模块 **`exynos7420_dvfs.c/.ko`**（out-of-tree,mainline cpufreq `target_index`）:
  - 直接 ioremap:`CMU_APOLLO=0x11900000`、`CMU_ATLAS=0x11800000`;`PLL_CON0/CON1/LOCK(0x0000)`、`MUX_SEL2=0x0208`/`MUX_STAT2=0x0408`、`DIV0/1=0x0600/0x604`、`DIV_STAT0/1=0x700/0x704`。
  - 频率/分频/电压表与 PLL M/P/S 全部取自 vendor 3.10:`exynos7420-{apollo,atlas}-cpufreq.c` 的 `APLL_FREQ`(分频) + `clk-exynos7420.c` 的 `table_apollo/table_atlas`(PLL) + `asv_voltage_7420_CA53/57`(电压)。
  - 变频序列照 vendor:改 **P** 时先 `mout_*` mux 到 BUS0_PLL（轮询 `MUX_STAT2[2:0]==1`）→ 写 PLL M/P/S 并等 `CON0 bit29` lock → mux 回（等 `==0`）;同 P 只写 M/S;升频先升压、降频后降压（`regulator_get(NULL,"VDD_APOLLO_AP"/"VDD_ATLAS_AP")`,by `regulator-name`）。
  - 分簇用 MPIDR Aff1（`of_get_cpu_node`+`reg` 建 mask）:A53/apollo={0,5,6,7},A57/atlas={1,2,3,4}。
  - **关键坑**:`cpufreq_generic_init()` 结尾 `cpumask_setall(policy->cpus)`（假设单簇 SMP）→ 必须在它**之后**再设 cluster mask,否则 8 核并进一个 policy。
  - 参数:`read_only`(默认1)、`max/min_a53_khz`、`max/min_a57_khz`。
- **实测**:`read_only=0` 下 A53 真切到 1296（`APOLLO CON0=m108,p2,s0`）、A57 掉到 200（`ATLAS CON0=m200,p3,s3`,验证了 **BUS0 mux 路径**）,0 rcu stall、20+ 分钟稳定;htop 两簇频率实时变化。
- **开机默认**:active + 保守上限（A53 1500 / A57 1704）。自编带参 loader `loadko2 <ko> <params...>`（`finit_module(fd, params, 0)`）+ `exynos7420-dvfs.service`（已 enable,显式传 `read_only=0 max_a53_khz=1500000 max_a57_khz=1704000`;模块本身默认仍 `read_only=1` 安全）。
- 未做:bus/CCI/EMI DVFS、ASV/ABB、更高频率（A53>1.8G / A57>2.5G 需先补总线/电压实测）。

### 15.5 htop temp+freq 结果（✅）
- `libsensors5` 已装,`sensors` 能看到 `cpu_thermal-virtual-0 temp1=+45.0°C`;htop 3.3 同时显示 CPU 温度与实时频率。

### 15.6 屏幕亮度调节（已完成 ✅）
- 面板是 **s6e3ha2**(zenlte display dtsi);亮度是 AMOLED 面板级,走 **DSI 命令**。我们没接管 DSI(S-Boot 配置),所以自写模块直接操作 **DSIM `0x13900000`** 发 DCS 包。
- **DSIM 命令通路**(`exynos7420_dsi.c/.ko`):ioremaps DSIM,按 vendor `exynos_mipi_dsi_common.c` 的方式发 **DCS 长写**(data type `0x39`):把 payload 写 `DSIM_PAYLOAD(0x40)`(4 字节一组)→ 写 `DSIM_PKTHDR(0x3c)`= `di | len<<8 | len>>8<<16` → 轮询 `DSIM_INTSRC(0x34)` 的 `SFR_PH_FIFO_EMPTY(1<<28)`。**验证**:发标准 `0x28`(display off)/`0x29` 能真黑屏/恢复 → 通路 OK。
- **亮度命令**:`0x51` 单独**无效**,必须先发 **`0x53 0x20`(WRITE_CTRL_DISPLAY,BCTRL=1)** 使能亮度控制,再发 **`0x51 <level>`**(DCS 长写,payload `{0x51,val}`)→ **有效**。vendor 还叠加 gamma/AID/ELVSS,但基础 `0x53+0x51` 已能平滑调亮度。
- 做成标准 **backlight 设备**:`backlight_device_register("exynos_dsi", max_brightness=255)`,`update_status` 发 `0x53 0x20`+`0x51 val` → `/sys/class/backlight/exynos_dsi/`。
- **GNOME 亮度滑块**:需要 **gsd-power**(gnome-settings-daemon 电源插件,经 **logind `Session.SetBrightness`** 写背光)。要点:
  1. `backlight.ko` 是模块(`CONFIG_BACKLIGHT_CLASS_DEVICE=m`),符号不在 Module.symvers → 用 `KBUILD_MODPOST_WARN=1` 编译,运行时**先加载 `backlight.ko`** 再加载我们的模块。
  2. gsd-power 必须在**有 seat 的会话**(tty1/session scope)里运行,否则 logind 拒绝("session has no seat");且要在 gnome-shell 起来之后启动(缺 `org.gnome.ScreenSaver` 会早退)→ profile 里 `(sleep 10; exec gsd-power) &`。
  3. 之后滑块出现且可调(`/sys/class/backlight/exynos_dsi/brightness` 随之变)。
- 持久化:`exynos7420-backlight.service`(`loadko backlight.ko` + `loadko exynos7420_dsi.ko`)+ `.bash_profile` 起 shim + 延迟 gsd-power + gnome-shell。
- 备注:更精细的亮度(避免低亮度偏色)需移植 vendor 的 gamma/AID/ELVSS 表。

### 15.7 喇叭声音（音频）— 调研 + 里程碑(a) 攻关（进行中，独立大工程）
- S6/Edge+ 音频链路:**AP I2S0 → WM1840(Arizona/Clearwater,SPI)→ 内部 DSP → AIF4 → MAX98505(I2C 0x31,I2S 功放)→ SPK**;耳机走 WM1840 的 HPOUT1。`sound` 节点用 `samsung,audio-routing`。
- **无捷径**:MAX98505 的 I2S 输入接的是 WM1840 的 `clearwater-aif4`(codec-to-codec DAI link),不是 AP 直连 → 喇叭也必须经过 WM1840 的 DSP。
- **需要移植**(vendor 3.10 → mainline 6.6):
  1. **MFD**:`drivers/mfd/arizona-{core,spi,i2c,irq}.c` 加 **WM1840**(Clearwater,同 `WM8285`;`clearwater_devs` + compatible `wlf,wm1840`)。mainline 目前 **没编 Arizona**(`CONFIG_MFD_ARIZONA_SPI` 未开)。
  2. **codec**:`sound/soc/codecs/clearwater.c`(**3177 行**,含 DSP/patch/固件);mainline 无 clearwater。
  3. **功放**:`sound/soc/codecs/max98505.c`(**1820 行**);mainline 有相近的 `max98504.c` 可参考。
  4. **机器驱动**:`sound/soc/samsung/noble_arizona.c`(**2411 行**;I2S0 + AIF links + DAPM `SPK`/`HP`/`RCV` + jack)。
  5. **I2S + 时钟**:mainline `sound/soc/samsung/i2s.c` 已支持 `samsung,exynos7-i2s`/`exynos7-i2s1`;需补 exynos7420 音频时钟(CMU)与 DTS 节点。
  6. **DTS**:SPI codec(`wlf,wm1840`,IRQ gpa2-5,reset gpf4-0)、`max98505@31`(i2c-gpio gpd2)、`sound` 卡片、pinctrl、供电/regulator。
  7. **config**:`MFD_ARIZONA=m`、`MFD_ARIZONA_SPI=m`、新增 `SND_SOC_CLEARWATER`、`SND_SOC_MAX98505`、`SND_SOC_SAMSUNG`、`SND_SAMSUNG_I2S`。
- **建议里程碑**:(a) codec 在 SPI 上 probe 成功;(b) I2S DAI + 音频时钟;(c) 机器卡注册(声卡出现);(d) `aplay` 喇叭出声;(e) 耳机/jack/录音。
- **量级**:数周,独立大工程。建议单独开 session 专做,从 (a) 开始。

#### 15.7.1 里程碑(a) 进展：codec 已确认可用，真正卡点是 **exynos SPI 控制器**（2026-09-12）
- **codec 硬件在 stock Android 上被证实完全可用**：`[0.730758] arizona spi0.0: WM1840 revision C`(读到 ID `0x6338`)，音频卡 "Noble WM1840 Sound" 注册、`clearwater-aif1 <-> 11440000.i2s mapping ok`、MAX98505 走 I2S、喇叭使能、播放时 MCLK 才开(`change mclk as 24M`，`mclk_source=1`)。
- **6 个来源的配置完全一致**(CHN stock DTB、EUR stock DTB、LineageOS hw_rev9 DTB、vendor 源码 `chn_09`、EUR dump、我们的 DTS):
  - SPI0 `14d20000` + `swap-mode`;引脚 `gpd8-0`(SCK)/`gpd6-0`(MOSI)/`gpd6-1`(MISO) func 2;**CS = GPIO `gpd8-1`**(`cs-gpio`，非硬件 CS);reset `gpf4-0`;IRQ `gpa2-5`。
  - `DCVDD=LDO26`(VDD_1.2V_CODEC);`AVDD/LDOVDD/DBVDD1-4/CPVDD/SPKVDD*`=`LDO16`(VCC_1.8V_CODEC_PMIC)。
  - MCLK=`clkout`:PMU `PMU_DEBUG` bit0 gate、source bits[12:8]、`writel(0x1000)`=enable+XXTI 24MHz;mainline 未注册 `clkout` 时钟。
- **datasheet 确认**:SPI 帧 = `R/W(1b)+31b addr+16b pad+16b data`=64 bit;**寄存器访问不需要 SYSCLK**;RESET 低有效;device ID `0x6338`。
- **mainline 侧尝试**:给 `exynos7.dtsi` 加了 `spi_0` 节点 + alias，并做了 **spi-gpio 位翻转**(禁用 exynos spi_0) + `wm1840_id.ko` probe 模块。**位翻转在 24 种引脚角色 × 3 组引脚、SPI mode 0-3、CS 极性高/低、reset 输入/高/低、各种端序下全部无响应。**
- **结论**:vendor 用的是 **exynos SPI 控制器**;该控制器在 **mainline 6.6 下一访问寄存器就 PERIC1 总线挂死**(时钟已核实跑到 66.7MHz，不是时钟问题)。→ **里程碑(a) 的真正阻塞是 exynos SPI 控制器驱动，不是 codec。**

#### 15.7.2 音频下一步
1. 修 mainline `spi-s3c64xx`/exynos SPI 在 7420 PERIC1 上的挂死(对照 vendor `spi-s3c64xx.c`，重点 IP 时钟、`CH_CFG`/`CLK_CFG`、FIFO 时序)。
2. 或继续位翻转，但需**逻辑分析仪/USB 抓 SPI 波形**校准 CPOL/CPHA/CS 建立保持，并确认 64-bit 帧的 pad 位处理。
3. 在控制器可用前，(b)-(e) 无法推进。

**产物**:`tmu_dt.img`、`exynos_tmu_hwmon.c/.ko`、`exynos-tmu-hwmon.service`、`exynos7420_dvfs.c/.ko`、`exynos7420-dvfs.service`、`loadko2.c/loadko2`、`cpufreq_read.py`、`getty-tty1-autologin.conf`、`exynos7420_reboot.c/.ko`、`exynos7420-reboot.service`、`sessionmanager-shim`、`exynos7420_dsi.c/.ko`、`backlight.ko`、`exynos7420-backlight.service`、`bash_profile.final`;`dbus-user-session` deb 在 `~/.gemini/antigravity/scratch/`、udisks2 deb 在 `~/.gemini/antigravity/scratch/sideload-udisks/`。

---

## 16. 设备当前状态 / 引导恢复（2026-09-12 晚，重要）

**结论先行**：音频调试期间刷入国行 **CRF2(Android 7.0) 全量固件**后，**新 BL/TZ 锁死了 UFS protector**，导致按旧(Android 5)底包调的 mainline 内核在 **UFS 初始化处总线挂死**（不是 rootfs/TWRP 问题）。现已全部解决：
- **UFS**：移植 6.10 的 **SMC 版 `exynos_ufs_config_smu`**（§17）→ 内核正常启动。
- **rootfs**：CRF2 首次开机格式化了 USERDATA(sda18)，已用 5.23GB 备份**流式恢复**（§17）。
- **TWRP**：`twrp-3.1.1-0-zenlte.img` 可正常进 recovery（先前 2.8.7.0 / `zenltezt` 进不去是**包**的问题）。
- **CROM 已解锁**；sda16 国行 Android 仍为备胎。

- **引导现状(已实测,2026-09-12 23:00)**：
  - sda7 = `smp8_ufssmc8.img`（**maxcpus=8 + UFS SMC 修复 + 无 ttyGS0**）→ 正常启动，**开机即 8 核**。
  - sda8 = TWRP `twrp-3.1.1-0-zenlte.img`（**可用，能进 recovery**）。
  - sda16 = 国行 CHN Android(`NRD90M.G9280ZCU2CRF2`)仍在(备胎)。
  - sda18 = **Ubuntu 24.04.5 rootfs（已恢复）**，systemd `running`、0 failed。
- **CROM 已解锁**：Download 模式此前 `Secure Download: Enabled`，用户已在 Android 里打开 OEM 解锁并重进 Download。
- **TWRP 结论(重要,已修正)**：**`twrp-3.1.1-0-zenlte.img`（24,762,384 B，sha256 `11703e5bc5367749260a4043e25cb5a3fd389ae67948e81549e320e93b9756b0`）刷入 sda8 后 `音量+ + Home + 电源` 能正常进 TWRP** ✅。而 `twrp-2.8.7.0-zenlte` 与 `twrp-3.1.1-0-zenltezt` 虽也 `RECOVERY upload successful`，却进不去 → **是这两个包与 CRF2 新 BL/机型不匹配，不是“老 TWRP 一律不兼容”**。以后刷 recovery 优先用 `zenlte` 版（非 `zt`）。
- **heimdall 坑**：`Protocol initialisation failed! / Failed to receive handshake response` 几乎都是 **USB 没重新枚举**（设备已进 Download，但 host 侧还挂着旧的 CDC 会话）→ **拔掉 USB 再插回**，`heimdall detect` 确认后即可 `flash --RECOVERY` 成功。
- **Odin 打包(本轮产物，在 `~/Desktop/` 与 `/Volumes/ODIN/`)**：
  - 原厂 `*.tar.md5` 实为**纯 tar(末尾无 MD5)**；据此重做了 TWRP(GNU 格式，单一 `recovery.img`，无 MD5)：
    - `TWRP-2.8.7.0-zenlte.tar.md5`(28,364,800B)
    - `TWRP-3.1.1-0-zenltezt.tar.md5`(18,104,320B)
  - Odin 放 **AP** 槽。带 MD5 的版本会被 Odin 判 `MD5 error`(尽管我们本地校验 md5 正确)；纯 `.tar` 会卡 `file analyze`；**纯 tar 命名 `.tar.md5` 最接近原厂**。
- **heimdall**:`WORKING-66audio/heimdall`(自编译)。握手不稳，重试即可(本轮 detect/flash 均一次成功)。
- **ODIN 分区**(xtb SSD `disk6`，exFAT)：**有完整 7.0 全量**——`AP_..._meta.tar.md5`(4.2GB)、`BL_...`、`CP_...`、`CSC_...`，加上述 TWRP 包。保底可随时重刷 7.0。
- **备份**:`~/.gemini/antigravity/scratch/WORKING-ALL-backup-20260912.tgz`(545MB)；`~/Desktop/sda18-linux-rootfs.img.gz`(5.23GB，SHA256 `f138d7c2a61d65c276ad7ab831d0dfdc1e4c052ed51612123f1b73827b44601a`)；内核源码 sparseimage 14.2GB。全部已复制到 `/Volumes/xtb/linux-backup-20260912/`。
- **下一步(可选)**：(1) 继续开发 → 直接刷 sda7（TWRP `dd` 或 Download 模式 `heimdall flash --BOOT`）；(2) 可选把 `twrp-3.1.1-0-zenlte` 打成 Odin AP 包备用；(3) 继续音频（§15.7）。

---

## 17. Android 7 (CRF2) 新 BL 下的 UFS 适配 + rootfs 恢复 + 8 核/TMU 收尾（2026-09-12 晚）★

**背景**：音频调试期间刷过国行 **CRF2(Android 7.0) 全量固件**，把底包从 **Android 5 换成 Android 7**，BL(`sboot`)/TZ/CP 全部更新。此后**所有 Linux boot.img 启动即卡死**。根因与这次底包变化直接相关。

### 17.1 现象与定位
- 现象：内核打印到早期 initcall 后停住（屏幕冻结、无 USB gadget）。
- 定位手段：
  - 从 `smp8_boot.img` 的命令行**空白填充处原地等长插入 `initcall_debug`**，并**重算 boot header 的 SHA-1**（`mkbootimg_7420.py` 算法：`sha1(kernel|len|ramdisk|len|0|dt|len)`，写入 header offset **576**）。
  - **关键坑**：`maxcpus=8` 时多核并发 probe 会互相占住 printk/console 锁，最后一行**不可信**；改 `maxcpus=1` 串行后才看到真实卡点。
- 卡点：`calling exynos_ufs_pltfm_init` → `UFSEX: ioremap_*` 之后进入 `exynos_ufs_init` 的 **`exynos_ufs_config_smu()`** —— 这是 `exynos_ufs_init` 里**第一次碰 UFS 硬件**的地方（`exynos7_ufs_drv_init` 空实现、之前全是 ioremap/DT/software）。

### 17.2 根因
- 6.6 驱动 `exynos_ufs_config_smu()` **直接 MMIO 读写 UFS protector**（`ufsp_readl/writel`，基址 `0x15572000`，含 `exynos_ufs_disable_auto_ctrl_hcc_save()` 里的 `hci_readl(HCI_MISC)`）。
- **Android 7 新 BL/TZ 把 UFS FMP/SMU 保护了起来**，直接访问 → 总线挂死（bus stall，无 oops，和当年 hsi2c 挂死同类）。
- 参考树 **6.10 早已改成 SMC 调用**，让安全监视器(EL3)去初始化 FMP/SMU。

### 17.3 修复（移植 SMC 版 config_smu）
`drivers/ufs/host/ufs-exynos.c`：加 `#include <linux/arm-smccc.h>`，并把 `exynos_ufs_config_smu()` 换成：
```c
static void exynos_ufs_config_smu(struct exynos_ufs *ufs)
{
	struct arm_smccc_res res;
	/* 0xC2001810 = SMC_CMD_FMP ; 0xC2001820 = SMC_CMD_SMU */
	arm_smccc_smc(0xC2001810, 0x8, 0x15572000, 0x0, 0,0,0,0, &res);
	arm_smccc_smc(0xC2001820, 0x0, 0x0,       0x0, 0,0,0,0, &res);
}
```
- 备份：`WORKING-66gnome/ufs-exynos.c.smcfix`。
- **效果**（一次点亮）：dmesg `UFS-DBG stage=ok err=0`、`Power mode changed to FAST series_B G_2 L_2`、`sda1..sda18` 全部枚举、`sda18` 挂载为 `/`。

### 17.4 构建与打包（增量）
```sh
cd ~/.gemini/antigravity/scratch/build/linux-6.6
OSSL=/opt/homebrew/var/homebrew/tmp/.cellar/openssl@3/3.6.4
export PATH="/opt/homebrew/bin:$HOME/.gemini/antigravity/scratch/toolchain-aarch64/aarch64-unknown-linux-gnu/bin:$PATH"; export LC_ALL=C
gmake ARCH=arm64 CROSS_COMPILE=aarch64-unknown-linux-gnu- \
  HOSTCFLAGS="-I$HOME/.gemini/antigravity/scratch/hostinclude -I$OSSL/include" HOSTLDFLAGS="-L$OSSL/lib" -j8 Image dtbs
# 重打包（新 Image + 原 ramdisk + 原 dt）：ramdisk = lean_ramdisk_touch.cpio.gz(4,908,811B)
python3 <brain>/mkbootimg_7420.py arch/arm64/boot/Image lean_ramdisk_touch.cpio.gz dt.img out.img "<cmdline>"
```
- 正式版 cmdline：`console=tty0 maxcpus=8 loglevel=8 init=/init rw clk_ignore_unused pd_ignore_unused fw_devlink=permissive`（去掉 ttyGS0 console 防拔线死机）。
- 若同时要 TMU：用 `tmu_dt.img`（带 TMU 的 dt，34816B）代替上面的 `dt.img`。

### 17.5 sda18 rootfs 恢复（流式，省 USB）
- 备份：`~/Desktop/sda18-linux-rootfs.img.gz`（5.23GB；解压 **28,093,448,192B = 整分区**；sha256 `f138d7c2a61d65c276ad7ab831d0dfdc1e4c052ed51612123f1b73827b44601a`）。
- **不要把 .gz 在 Mac 解压后再传**（那会走 28GB USB）。正确：**原样传 5.23GB 的 .gz，设备端解压**。TWRP 自带 `pigz 2.2.5`（`/sbin/gzip`）：
```sh
adb shell "umount /sdcard 2>/dev/null; umount /data 2>/dev/null"
cat ~/Desktop/sda18-linux-rootfs.img.gz | pv -s 5233658584 | \
  adb exec-in "gzip -dc | dd of=/dev/block/sda18 bs=4M 2>&1; sync"
```
- 约 12–15 分钟（6–10 MB/s）；完成后挂载校验 `/mnt/sda18/ubuntu/etc/os-release` = `Ubuntu 24.04.5 LTS`。

### 17.6 8 核持久化
- 正式镜像本身 `maxcpus=8`，**开机即 8 核**。
- 另装 `/etc/systemd/system/cpu-online.service`（oneshot，`echo 1 > /sys/devices/system/cpu/cpuN/online`）作兜底，已 `enabled`。

### 17.7 温度(TMU)修复
- `CONFIG_EXYNOS_THERMAL=m` → TMU 是**模块**，但恢复后的 rootfs **缺 `exynos_tmu.ko`**（只有 hwmon 桥接模块），所以 `/sys/class/thermal` 一直为空、`exynos-tmu-hwmon.service` 报 `zone not found` / `finit_module: No such device`。
- 修：把 `drivers/thermal/samsung/exynos_tmu.ko` 放进 `/lib/modules/6.6.0/extra/`，并给 `exynos-tmu-hwmon.service` 加 drop-in 先加载 tmu：
```ini
# /etc/systemd/system/exynos-tmu-hwmon.service.d/load-tmu.conf
[Service]
ExecStart=
ExecStart=/bin/sh -c '/usr/local/bin/loadko /lib/modules/6.6.0/extra/exynos_tmu.ko || true; /usr/local/bin/loadko /lib/modules/6.6.0/extra/exynos_tmu_hwmon.ko || true'
```
- 结果：`thermal_zone0=cluster0-thermal`、`hwmon1=cpu_thermal`（htop/sensors 可用）；`systemctl is-system-running` = **running**，0 failed。

### 17.8 本轮产物
- `WORKING-66gnome/{smp8_ufssmc8.img, smp8_ufssmc.img, ufs-exynos.c.smcfix, Image-6.6-ufssmc}`。
- 设备端：`/lib/modules/6.6.0/extra/exynos_tmu.ko`、`exynos-tmu-hwmon.service.d/load-tmu.conf`、`cpu-online.service`。
- **TWRP**：`twrp-3.1.1-0-zenlte.img`（sha256 `11703e5bc5367749260a4043e25cb5a3fd389ae67948e81549e320e93b9756b0`）。

---

## 18. 音频移植（WM1840 / CS47L85）—— 进行中（2026-09-12 深夜）

> **★ 关键结论：三星的 "WM1840 / Clearwater / Arizona" 就是 Cirrus `CS47L85`（Madera 家族），mainline 原生支持它！不用移植 vendor 的 clearwater.c/arizona 那 7400 行！**

### 18.1 判定依据（铁证）
- mainline `drivers/mfd/madera-core.c`：`#define CS47L85_SILICON_ID 0x6338`
- vendor `wm1840_id.c` 期望的 WM1840 ID：**0x6338**（完全一致）
- 寄存器地址一致：`ARIZONA_SOFTWARE_RESET 0x00` == `MADERA_SOFTWARE_RESET 0x00`；`ARIZONA_EQ1MIX_INPUT_1_SOURCE 0x880` == `MADERA_EQ1MIX_INPUT_1_SOURCE 0x880`；ADSP 都是 **7 个**
- mainline `madera_of_match` 有 **`cirrus,wm1840`**；`madera-spi.c` 有 `{ "wm1840", WM1840 }`，并复用 `cs47l85_16bit/32bit_spi_regmap`

### 18.2 已完成
- 内核开启音频子系统（**全部模块化**，避免 Image 超 sda7 的 28MB 分区）：
  `CONFIG_SND=m`、`SND_SOC=m`、`SND_SOC_SAMSUNG=m`、`SND_SAMSUNG_I2S=m`、`SND_SIMPLE_CARD=m`、`MFD_MADERA=m`、`MFD_MADERA_SPI=m`、`MFD_CS47L85=y`、`SND_SOC_MADERA=m`、`SND_SOC_CS47L85=m`。
- DTS codec 节点：`compatible = "cirrus,wm1840"`（原 vendor 是 `wlf,wm1840`）、`interrupt-parent=<&gpa2> interrupts=<5 0 0>`、`clocks=<&s2mps13_osc 0>` + `clock-names="mclk2"`、`reset-gpios=<&gpf4 0 ...>`、供电 DCVDD=ldo26 / AVDD=DBVDD1=LDOVDD=CPVDD1=ldo16。
- **给 codec 两路电加 `regulator-always-on`**（否则 Linux 关闭空闲电轨 → codec 断电）。
- **原生 exynos7 SPI 编成模块**（`spi-s3c64xx.ko`）：之前「启动挂死」其实是延迟 probe 的问题；insmod 时**控制器正常**（`spi spi0.0: feedback delay set to default (0)`）。
- 模块加载顺序（`loadko`，需手动按序）：
  `snd → snd-timer → snd-pcm → snd-pcm-dmaengine → snd-compress → cs_dsp → snd-soc-core → snd-soc-wm-adsp → snd-soc-madera → snd-soc-cs47l85 → spi-s3c64xx → madera → madera-spi`。
- 实测加载后：`madera spi0.0: Unknown device ID: ffff` → **codec 控制口不应答**（`ffff`），probe 失败（`-EINVAL`）。

### 18.3 当前卡点：codec 控制口恒 `ffff`
已排除/尝试过的：
- 供电：`VCC_1P8_CODEC_PMIC`=1.8V、`VDD_CODEC_1P2`=1.2V 均 enabled ✅
- reset：`gpf4-0` 已确认可控制（CON 输出、DAT 变化），两种极性都试 ✅
- MCLK2 32kHz：已给（`s2mps13_osc`）✅
- SPI 引脚枚举（`spibrute2.py` 试 gpd6/gpd8/gpd5 全排列）、4 种 SPI 模式、bit-bang 3线/4线：**全部 `ffff`/`0x0000`**
- 原生 SPI（正确 regmap 协议）同样 `ffff`
- `PMU_DEBUG=0x1000`（vendor 的 `exynos5_audio_set_mclk` 使能 MCLK）单独打开 → 仍 `ffff`

**推断**：codec 需要 SoC 侧正确输出 **MCLK/CLKOUT**（§15.7 待办原话：「补 `clkout`/MCLK(PMU_DEBUG bit0) + I2S/CMU_AUD，再回到 WM1840 probe」）。

### 18.4 mainline 已有 CMU_AUD（重要）
- `drivers/clk/samsung/clk-exynos7.c` **已内置 CMU_AUD**：`aud_clk_regs` + `CLK_OF_DECLARE(exynos7_clk_aud, "samsung,exynos7-clock-aud")`，含 `mout_aud_pll_user`(父=fin_pll/fout_aud_pll)、`dout_aud_cdclk`、`dout_sclk_i2s`、`sclk_i2s`、`pclk_i2s`、`aclk_dmac` 等。
- TOPC 已有 `fout_aud_pll`(pll_1460x) / `sclk_aud_pll` / `dout_sclk_aud_pll`。
- **仅缺 DT 节点**：已加 `cmu_aud: clock-controller@114c0000 { compatible="samsung,exynos7-clock-aud"; ... }`（在 `exynos7.dtsi`）。

### 18.5 剩余 TODO（按顺序）
1. **DT**：`adma@11420000`(PL330, `clocks=<&cmu_aud ACLK_ADMA>`, IRQ SPI 97) + `i2s0@11440000`(`samsung,exynos7-i2s`, `clocks=<&cmu_aud PCLK_I2S/SCLK_I2S>`, dmas=`<&adma 0>,<&adma 2>`, pinmux)。
2. **声卡**：先用 `simple-audio-card` 连 `i2s0 ↔ wm1840`，触发 I2S/DAPM 使能 MCLK。
3. **验证 codec**：MCLK 起来后，`madera spi0.0` 应能读到 `0x6338`（不再是 `ffff`）。
4. **max98505**：mainline 无，需移植/仿 `max98504.c`（I2C 0x31，喇叭经 WM1840 AIF4 的 codec-to-codec link + DSP）。
5. **machine 驱动**：noble_arizona（2411 行）或自写最小版，含 speaker/HP DAPM 路由。
6. **DSP 固件**：把 `clearwaterc-dsp*.wmfw` 放到 firmware 路径（按 mainline cs47l85 期望的名字）。

### 18.6 相关产物
- `WORKING-66audio/audio-modules/`（`snd*.ko`、`madera*.ko`、`snd-soc-cs47l85.ko`(8.5MB)、`cs_dsp.ko`、`spi-s3c64xx.ko`、`spi-gpio.ko` 等）
- `WORKING-66gnome/{smp8_audio1.img, smp8_audio2.img, smp8_audio3.img}`（音频调试镜像；`smp8_audio3` 用原生 `spi_0`）
- `WORKING-66audio/android_captures/`（Android 侧抓的 dmesg/DAPM/mixer/firmware，音频规格）

### 18.7 本轮追加进展（CMU_AUD / I2S / adma / simple-card）
- **CMU_AUD ✅**：mainline `clk-exynos7.c` 已内置 CMU_AUD；只需在 `exynos7.dtsi` 补 `cmu_aud@114c0000 { compatible="samsung,exynos7-clock-aud"; }`。实测 `clk_summary` 出现 `fout_aud_pll`/`mout_aud_pll_user`/`dout_aud_cdclk`/`dout_aclk_aud`/`sclk_aud_pll`（rate = S-Boot 默认 202MHz，enable=0）。
- **DT 追加**：`adma@11420000`(PL330, `clocks=<&cmu_aud ACLK_ADMA>`, IRQ SPI 97)、`i2s0@11440000`(`samsung,exynos7-i2s`, `clocks=<&cmu_aud PCLK_I2S/SCLK_I2S>`, `dmas=<&adma 0>,<&adma 2>`)、板级 `simple-audio-card`(i2s0↔wm1840) + `&wm1840 { #sound-dai-cells = <1>; }`。i2s0 引脚是 `gpz0-0..6`，属**独立 AUD pinctrl 块 `pinctrl@114B0000`**（mainline 未有，暂未加）。
- **配置**：新增 `CONFIG_PL330_DMA=m`。产物 `WORKING-66gnome/smp8_audio4.img`；`WORKING-66audio/audio-modules/` 增加 `pl330.ko`/`snd-soc-i2s.ko`/`snd-soc-simple-card*.ko`。
- **串口永久修复**：从 sda7 内置 cmdline 去掉 `console=ttyGS0,115200`（`rmcon.py` 原地补丁+重算 SHA），以后不用再手动 `systemctl restart serial-getty@ttyGS0`。
- **加载顺序(更新)**：`pl330 → snd → snd-timer → snd-pcm → snd-pcm-dmaengine → snd-compress → cs_dsp → snd-soc-core → snd-soc-wm-adsp → snd-soc-madera → snd-soc-cs47l85 → snd-soc-s3c-dma → snd-soc-idma → snd-soc-i2s → spi-s3c64xx → madera → madera-spi → snd-soc-simple-card-utils → snd-soc-simple-card`（`snd-soc-i2s` 依赖 `s3c-dma`/`idma` 导出符号）。
- **★ 推翻「MCLK 才能让 codec 应答」**：`madera_dev_init` 是**先读 ID（`MADERA_SOFTWARE_RESET` 0x00，期望 `0x6338`）、之后才轮到 I2S/MCLK**。故 codec ID 读取**不依赖 MCLK**，`ffff` 只能是 **供电 / 复位 / SPI 帧格式 / 引脚**。
- **已排除**：供电 1.8V/1.2V(enabled)、复位（低有效，vendor `arizona-core.c:415/431` 同为 low=assert / high=deassert）、SPI 引脚全排列、SPI 4 模式、bit-bang 3/4 线、原生 SPI 正确 regmap 协议。
- **待查**：① codec 是否有**独立电轨**（DBVDD2/3/4、CPVDD2、SPKVDDL/R——vendor 节点都挂 ldo16，真机可能不同）；② 主控 SPI 的 **CS/帧格式**（对比原厂 `spi_0`）；③ 打印/反汇编原生 SPI 实际发出的字节与预期帧比对。
- **★ SPI 帧已抓到**（给 `drivers/spi/spi-s3c64xx.c` 的 `s3c64xx_spi_transfer_one()` 加 tx hexdump，模块化重编 `spi-s3c64xx.ko`）：
  ```
  S3CSPI tx len=6: 80 00 18 80 00 00   # 读 0x1880 (MADERA_IRQ1_RAW_STATUS_1，madera_wait_for_boot 轮询)
  S3CSPI tx len=6: 80 00 00 00 00 00   # 读 0x0000 (MADERA_SOFTWARE_RESET) → 回 0xffff
  ```
  即 `80 00`(读标志) + `16 位地址` + `16 位数据`，**与 mainline/vendor 的 regmap 帧格式完全一致 → SPI 协议没问题**。codec 不回 = **硬件级（缺 MCLK / 供电时序）**。
- **现象补充**：加载 `madera-spi` 有时会**整机硬挂**（屏幕全死、串口无输出），疑与 codec 中断(gpa2-5)或 SPI 访问相关（和当年 stmfts IRQ 风暴类似）。
- **MCLK 强制打开的两次尝试（均未成功，供下次参考）**：
  1. 写小模块 `mclk_on.ko` 用 `clk_get(NULL,"sclk_i2s")` 等按名取时钟 → **全部 NOT FOUND**（CMU_AUD 走 `of_clk_add_hw_provider`，**没有 clkdev 名字**，`clk_get(NULL,name)` 取不到）。
  2. 用 `/dev/mem` 直接写 CMU_AUD 门控(`ENABLE_SCLK/PCLK/ACLK_AUD`)+`PMU_DEBUG=0x1000` → **把整机写挂**（不推荐硬写时钟寄存器）。
- **★ 下一步（干净做法）**：在 `drivers/clk/samsung/clk-exynos7.c` 的 `aud_gate_clks` 里给 `sclk_i2s`(及 `dout_aud_cdclk` 对应门控) 加 **`CLK_IS_CRITICAL`**，并给 `fout_aud_pll` 设一个默认速率（或让 `sclk_i2s` `CLK_SET_RATE_PARENT`），重编内核刷入 → MCLK 常开 → 再 probe codec 验证「缺 MCLK」假设。若仍 `ffff`，则需示波器实测 codec 供电/时钟/MISO。

### 18.8 本轮追加（MCLK 真相 / `spi_0` 卡死定位 / 运行 DT 核对）2026-09-13 00:40
- **★ 更正 MCLK 路径**：厂商 `sound` 节点 `clocks = <&clock 45>`；vendor `clk-exynos7420.c:36` 中 **45 = `clkout`**，对应 `clk-exynos7420.c:3317`：
  `GATE(clkout, "clk_out", "fin_pll", EXYNOS_PMU_PMU_DEBUG, 0, ...)` → codec 的 **MCLK1 = SoC CLKOUT（`fin_pll` 24MHz，`PMU_DEBUG` 控制）**，**不是 `sclk_i2s`**。mainline 完全没有这个 clock，也无人 enable 它。故 §18.7 的「给 `sclk_i2s` 加 `CLK_IS_CRITICAL`」方向不对。
- 厂商机器驱动 `noble_arizona.c` `mclk_control()`：`clk_enable(priv->mclk)` + `exynos5_audio_set_mclk(true,0)`（→ 写 `PMU_DEBUG=0x1000`，见 `arch/arm64/mach-exynos/include/mach/exynos-audio.h:34`）。基频 `24MHz`(48k)/`22.5792MHz`(44.1k)/`32768`(默认)，由 `clk_sel_gpio` 选择。
- **实测（干净启动）**：`PMU_DEBUG=0x00000000`；写 `0x1000` 后读回 `0x00001000`，**机器稳定（写 PMU_DEBUG 本身不卡）**。
- **bit-bang 复测（CLKOUT 开）**：`/root/mclk.py`(写 0x1000) → `/root/spibrute2.py`(gpd6/gpd8/gpd5 全排列) → **仍全 `0x0000/0xffff`，`non-trivial: []`**。即「CLKOUT(MCLK1) 常开」本身不足以让 codec 应答 SPI。
- **★ `spi_0` 控制器 probe 卡死（第一顺位阻塞）**：加载 `/root/audio-modules/spi-s3c64xx.ko` 打印 `module loaded OK` 后，下一条命令无回显，整机硬挂（屏幕死、串口无输出）。`journalctl -k -b -1` 尾部：`rcu: detected stalls` + `Unable to handle kernel paging request` @ `copy_page_range`。**卡的是 SPI 控制器 probe，不是 codec/madera/IRQ**；不加载 `spi-s3c64xx` 时设备稳定。
- **运行 DT 核对**（`/proc/device-tree`，外设都在 `soc@0/` 下，全部存在）：`clock-controller@114c0000`(CMU_AUD)、`i2s@11440000`、`dma-controller@11420000`、`spi@14d20000`(status=okay，子 `audio-codec@0` compatible=`cirrus,wm1840`、clock-names=`mclk2`)、`sound`(simple-audio-card)。**spi 节点无 `power-domains`**。
- **供电映射正确**：`ldo16_reg`=`VCC_1P8_CODEC_PMIC`、`ldo26_reg`=`VDD_CODEC_1P2`，运行时均 enabled。mainline `madera_core_supplies={AVDD,DBVDD1}` + DCVDD（读 ID 只需这三路，见 `madera-core.c:43`）。
- **`s2mps13_*` 32k（mclk2 来源）`enable=0`**（mainline madera 在读 ID 之后才 enable mclk2）。
- 厂商 DT 差异：codec `spi-max-frequency=25000000`(我们 1MHz)；厂商供 `CPVDD` 我们 `CPVDD1`；机器用 `noble-arizona` + `audio_clk_sel` pinctrl(`gpf5-6` func1/val0) + `clk_sel_gpio=<&gpf5 6 0>`；codec pinctrl `codec_reset`(gpf4-0)+`codec_irq`(gpa2-5 func 0xf)；vendor SPI compatible=`samsung,exynos742x-spi` 且带 `swap-mode`。
- **下次顺序**：① 先修 `spi_0` controller probe 卡死（硬阻塞）；② 再把 CLKOUT/MCLK（`clkout` gate → `PMU_DEBUG` bit12）在 mainline 常开；③ 若 codec 仍不应答，则需示波器实测 codec MCLK/供电/MISO（软件侧基本排除）。

### 18.9 全面排查（SPI 卡死根因 / codec 矩阵扫描）2026-09-13 01:13
- **★ `spi_0` 卡死根因 = 旧模块**：`/root/audio-modules/spi-s3c64xx.ko` 一加载就整机硬挂；用当前 mainline 源码重编的 `spi-s3c64xx.ko`（`gmake` 4.4.1 + `toolchain-aarch64`）**probe 完全正常、稳定**。`journalctl -k -b -1` 里的 `rcu detected stalls` + `copy_page_range` paging fault 是旧模块所致，与源码/DT 无关。
- **autosuspend 可疑**：新模块在 `AUTOSUSPEND_TIMEOUT=2000` 时，probe 成功后约 2s 整机卡死；改成 **600000** 后长时间稳定。怀疑 `s3c64xx_spi_runtime_suspend`（关 clk）触发问题，**待查**。
- **新编探针 `wmprobe.ko`**（`module_param`: `mode`/`bpw`/`mclk1`；配合 sysfs 改参 + `unbind`/`bind` 重探）做全矩阵：
  **`mode 0..3` × `bpw 8/32` × CLKOUT(`PMU_DEBUG` bit12) 开/关 → 全部 `ID=0xffff rev=0xff`**。
- 已确认正常项：供电 `ldo16/ldo26` enabled；复位 `gpf4-0` output、`DAT=1`(释放)；SPI 引脚 `gpd6/gpd8 CON=0x22`(func2)、PUD 上拉；`sclk_spi0=2MHz` enabled；无 over/underrun；TX 帧 `80 00 00 00 00 00`(读 0x0000)。
- **codec liveness**：reset 脉冲后 `gpa2-5`(IRQ) 恒高、不翻转 → codec 未启动/未驱动 IRQ（Android 上是会驱动 IRQ 的）。
- 去掉 `S3C64XX_SPI_QUIRK_CS_AUTO`（与厂商 `exynos742x` 一致）→ 仍 `ffff`。
- **结论**：软件侧（SPI 控制器/协议/4 模式/CS/时钟/复位/供电/mclk1+mclk2）已全面穷尽，codec 始终不应答 → **硬件/电气层**问题（codec 供电时序、未建模电轨 DBVDD2/3/4、SPKVDD、MICVDD，或 /RESET/MISO/CS 走线、codec 本体）。下一步需**示波器**测 codec 端 SCK/MOSI/MISO/CS、/RESET、MCLK。
- **迭代技巧**：可用 Python `ctypes` 调 `delete_module` 卸载 `spi_s3c64xx`/`wm1840_id*`，无需重启；模块参数经 `/sys/module/wmprobe/parameters/*` 设置后 `unbind`/`bind` 即可重探。

### 18.10 软件“逻辑分析仪” + 排除加密/频率/寄存器/时序 2026-09-13 01:30
- **排除软件模拟 SPI / 加密**：Android 日志实证 codec 在**硬件** `s3c64xx-spi 14d20000.spi`（`/devices/14d20000.spi/spi_master/spi0/spi0.0`）；厂商 secure SPI 是 `CONFIG_ESE_SECURE_SPI_PORT=**3**`（指纹 eSE），与 codec(port 0) 无关；厂商 codec 驱动就是标准 Wolfson `arizona`/`clearwater`，**无任何加解密/认证代码**。
- **排除频率**：Android 25MHz；我们试过 1MHz(native) 与 10kHz(bit-bang)，均 `ffff`。
- **★ PMIC 型号修正**：主板 PMIC 是 **S2MPS15**（`samsung,s2mps15-pmic` @0x66），不是 s2mps13。用 s2mps15 表重读 `1-0066`：
  - `LDO16(0x43)=0xec` → vsel=0x2c，range1(1.0V,step25mV,min_sel12) → **1.8V**，enabled(`[7:6]=11`)
  - `LDO26(0x4d)=0xe8` → vsel=0x28，range3(0.7V,step12.5mV) → **1.2V**，enabled
  → **codec 电轨寄存器/电压都正确**（厂商名 `VCC_1.8V_CODEC_PMIC`/`VDD_1.2V_CODEC` = 我们的 ldo16/ldo26）。
- **软件“逻辑分析仪”**（自编内核模块 `spiscope.ko`）：把 gpd6/gpd8 四线当 GPIO、独立控制复位+MCLK1，按真实 regmap 帧 `80 00 00 00 00 00` 以 **10kHz** bit-bang，逐位采样 MISO：
  `MISO bits[48]=111…111 (全 1)，last16=0xffff`。
- **CS-at-reset 时序**（`spiscope2.ko`，复位释放瞬间 CS 分别拉高/拉低）：两者都仍全 1。→ SPI/I2C 选择脚假设不成立（或不在 CS 上）。
- 厂商机器驱动 `noble_arizona` 只用两个 GPIO：`mic_bias_gpio`(MICBIAS_EN_AP)、`clk_sel_gpio`(SEL_44.1K)，**无 codec 使能/模式脚**；厂商 board DTS 也没有额外的 codec 电轨。
- **最终结论**：SoC 侧时钟/CS/数据/复位/供电/MCLK 全部就绪，codec 端 **MISO 恒不驱动** → 纯软件无法再推进，必须外部观测：**最省事是买一个 ¥30-70 的 USB 逻辑分析仪（fx2lafw/“Logic 8”）抓 SCK/MOSI/MISO/CS**（若 SPI 焊盘/测试点可及，无需整机拆解）。备选：示波器测 /RESET、MCLK1、各电轨实际电压。

### 18.11 DTBH 打包坑 + 厂商 1:1 DTB 实测（仍 ffff）2026-09-13 01:55
- **★ DTBH 打包坑（重要，以后 DT 改动必看）**：boot 镜像的 DT 区**不是裸 FDT**，而是 Samsung **DTBH v2 容器**（`DTBH` + ver2 + 7 个 hw_rev 条目×32B + 页对齐 2048 + FDT；`sub_id=0x217584da` 是硬编码常量，非校验和）。**直接用 `repack_dt.py` 塞裸 DTB → 卡 logo**（我踩了）。
  - 正确流程：`python3 mkdtbh.py <x.dtb> <dt.img>` → 再 `repack_dt.py <base.img> <dt.img> <out.img>`。
  - 工具位置：`~/.gemini/antigravity/brain/1aa1eae7-.../scratch/{mkdtbh.py,mkbootimg_7420.py}`；设备端 `/root/dtflash.py` 可只刷 dt 段（改大小+SHA-1）。
- **厂商 1:1 DTB 实测**：回填 `cs-gpios=<&gpd8 1 GPIO_ACTIVE_LOW>` + `spi0_bus_cs`(去 CS) + codec `codec_reset`/`codec_irq` pinctrl + 全部供电(`DBVDD2/3/4`、`CPVDD2`、`SPKVDDL/R`→ldo16) + `spi-max-frequency=25MHz` + 去自造 `mclk2`；用 `mkdtbh.py` 正确打包刷入，**可正常启动**。
  - 实测 `cat /sys/kernel/debug/gpio`：`gpio-98 (spi0 CS0) out hi ACTIVE LOW` → **GPIO CS 已生效**。
  - 结果：仍 `wmprobe spi0.0: ID=0xffff rev=0xff`（3 次/两种复位极性）。
- 追加：CLKOUT(`PMU_DEBUG=0x1000`) + `gpf5-6` 输出低（仿 `audio_clk_sel`）→ 仍 `ffff`。
- **最终**：**CS/供电/pinctrl/协议/模式 全部与厂商一致，codec 端仍全 1** → 确认问题在**物理层**（MCLK 是否真到 codec、SPI 某根线走线、或 codec 本体/strap）。**下一步必须上逻辑分析仪**。
- 产物：`WORKING-66gnome/smp8_audio4_vendor1to1.img`（+ xtb `linux-backup-20260912/vendor1to1/`：img、dtb、dt.img、dts 快照）；`new_dt.img`(38KB DTBH)。

### 18.12 原厂固件（ODIN 盘 AP/BL/CP/CSC）分析 2026-09-13 02:02
- **AP**：`boot.img` → 内核 **Linux 3.10.61-12451430**（2018）；ramdisk 标准 Android（`lib/modules` 空 → arizona/spi/samsung-* **全部编进内核**）；DTBH 含 7 个 hw_rev，取 rev9(=SM-G9280) DTB 反编译：
  - `wm1840@0`：`wlf,wm1840`、`spi-max-frequency=0x17d7840`(25MHz)、`wlf,reset=<gpf4 0 0>`、`pinctrl=<codec-reset,codec-irq>`、**`controller-data{cs-gpio=<gpd8 1 0>}`**、供电全指 **LDO26(DCVDD)/LDO16(其余)**、**无 `clocks`**。
  - `spi@14d20000`：`samsung,exynos742x-spi`、`swap-mode`、**无 dma**、`num-cs=1`、`pinctrl=spi0-bus`(gpd8-0,gpd6-0,gpd6-1 func2，**不含 CS**)。
  - pinctrl：`codec-reset`(gpf4-0 func1/下拉/val0)、`codec-irq`(gpa2-5 func0xf)、`audio-clk-sel`(gpf5-6 func1)。
  - `sound`：`samsung,noble-arizona`、`clocks=<&clock 45>`=**`clkout`**、`clock-names="mclk"`；`audio_pdata{clk_sel_gpio=<gpf5 6>}`。
  - 内核无任何板级 codec 初始化（`exynos7420_pmu_init` 只设 ARM clamp/SRAM；`exynos5_audio_set_mclk` 仅机器驱动播放时调用）。
- **BL**：`sboot.bin`(签名/加密，内嵌 gzip 段标注 `encrypted`，读不出)、`param.bin`、`cm.bin`。
- **CP/CSC**：modem 固件 / 区域定制，**与 codec 无关**。
- **厂商源码对照**：`drivers/mfd/arizona-spi.c` 是**标准 Cirrus 驱动**（无特殊处理）；`clearwater_16bit_spi_regmap` 与 mainline `cs47l85_16bit_spi_regmap` 逐字段一致（reg32/pad16/val16，默认 BIG）。CLKOUT 位定义：`PMU_DEBUG` bit0=DISABLE、bits[12:8]=SEL(XXTI=0x10)；`0x1000` 正确。
- **★ 结论**：原厂就是「标准驱动 + 这套 DT + 内核内置」，**没有隐藏的板级/bootloader/userspace 处理**。我们已 1:1 复刻 DT、用标准实现，且**手工 bit-bang 直接发时钟/数据 codec 仍不应答** → 差异只在**物理/电气层**。唯一出路：**USB 逻辑分析仪/示波器**。

### 18.13 subagent 假设验证（PMU Retention / DT aliases / PUD / MCLK）2026-09-13 02:31
外部 subagent 提出几条底层假设，逐条用实机数据核对：
- **① PMU PAD Retention / Isolation —— 排除**：dump `0x105c11xx-0x105c12xx`（`EXYNOS_PMUREG`，7420 真实地址，非 5433 的 0x30xx）：
  `PAD_RETENTION_SPI(0x1238)=0`、`PAD_ISOLATION_SYS(0x1240)=0`、`PAD_RETENTION_AUD(0x1204)=0`、`PAD_RETENTION_TOP(0x1220)=0`、`PAD_RETENTION_FSYSGENIO(0x1254)=0` —— **全部 0，无隔离**。（`TOP_RETENTION_SYS/MIF=0xffffffff` 是另一类寄存器。）
- **② DT aliases —— 排除**：mainline `pinctrl-samsung.c:990` 确实用 `of_alias_get_id(node,"pinctrl")` 索引 `exynos7_pin_ctrl[]`，但实机 `pinctrl0..8` = `10580000/13470000/14cd0000/14ce0000/14c90000/14ca0000/10e60000/15690000/14870000` 与驱动数组（Alive/BUS0/NFC/TOUCH/FF/ESE/FSYS0/FSYS1/BUS1）**逐一吻合**。
- **③ PUD/上下拉实测**（`pintest.py`）：
  - `MISO(gpd6-0)`: none→1、pull-down→0、pull-up→1 → **MISO 电平完全跟随 SoC 内部 PUD** ⇒ **codec 的 SDO 是三态高阻、没在驱动**（确证）。
  - `RESET(gpf4-0)`: none→1、pull-down→0、pull-up→1；设为输出 0/1/0/1 读回一致 ⇒ **pad 未隔离、输入/输出通路正常、复位已释放**。
  - ⇒ “Pad 隔离 / 走线断连”排除。
- **④ PUD 位宽**：Exynos 非 Alive bank 也是 2bit/pin；本会话脚本用的是 `(p*2)` 位移（正确）。
- **⑤ MCLK**：同意——读 ID(0x00) 时不需要 MCLK，厂商也后开 MCLK2。
- **最终**：PAD 通路正常、复位释放、供电寄存器“enabled”，但 **codec SDO 三态、IRQ 不动** → 收窄到**芯片侧**：**1.8V/1.2V 实际是否到芯片（PMIC “enabled”≠有电压）**、或 **codec 本体/strap**。软件无手段，必须**万用表量 codec 供电脚**或**逻辑分析仪**。

### 18.14 补齐 LPASS（厂商音频平台初始化）2026-09-13 02:39
- **发现**：厂商内核有一套 mainline 没有的 `samsung-lpass` 音频子系统驱动：
  - `sound/soc/samsung/lpass.c`（`fs_initcall` 注册，probe 早于 codec）：`lpass_set_clk_heirachy`（fout_aud_pll 351MHz 等）+ **`lpass_init_clk_gate()`**
  - `lpass-exynos7420.c:248` `lpass_init_clk_gate()`：清 `INIT_ACLK_GATE_MASK(bit31,30)`/`INIT_PCLK(22,23,24,26,27,28)`/`INIT_SCLK(26..31)` → **打开 CMU_AUD 的 ACLK/PCLK/SCLK 门控**
  - `lpass_release_pad_reg()`：PMU `0x3028` bit28 + `0x1340`=1；runtime resume `lpass_enable_pll(true)`
- **复刻**（`lpassinit.ko`，直接 ioremap CMU_AUD/PMU，照厂商掩码清位）实测**成功、无卡死**：
  - `ACLK 0x7fffffff→0x3fffffff`、`PCLK 0xffffffff→0xe23fffff`、`SCLK 0xffffffff→0x03ffffff`
  - PMU `0x1340 0→1`（AUD pad release）；`0x3028` 写不进去（只读/异块）
- **结果**：LPASS 补齐后再 probe codec，**仍 `ID=0xffff`** → 证实 **AUD 平台初始化不是 codec 沉默的原因**（codec SPI 在 BUS0、MCLK=CLKOUT/XXTI、reset 在 BUS1，都不在 AUD 域）。
- **意义**：这是官方“整条链路”里 mainline 缺的一环，补齐对后续 I2S/播放有用；但 codec 读 ID 这一关仍卡在**芯片侧物理层**。

### 18.15 网络调研：mainline 上没人搞定过 WM1840 + 为何 1:1 复刻还不够 2026-09-13 02:46
- **社区现状**：
  - `github.com/Exynos7420/linux`（分支 `v6.10-exynos7420`，7420 mainline 移植）：支持 S6(`zeroflte`)，但 `exynos7420-zero-common.dtsi`/`zeroflte.dts` **完全没有音频**（无 `spi0`/`i2s`/codec/`sound`；PMIC ldo16/26 连 `always-on` 都没有）。**进度落后于本项目。**
  - **postmarketOS** Galaxy S6 Edge(`samsung-zeroltexx`) 页：Features 表 **Audio=Works**，但该端口 **`Mainline: no`**、**pmOS 内核 = 3.10.108（下游/vendor 内核）**；硬件表明确标 **`Audio Codec: Cirrus Logic WM1840ECS-R` → `Mainline: N`（不支持）**。
  - 「Audio Works」是**跑在下游 vendor 内核**上的；**mainline 上 CS47L85/WM1840 至今无公开可用记录**。
- **为何 1:1 复刻 DT/驱动还不够**：复刻的是 **codec 层**（`madera` 驱动 + DT：SPI/复位/供电/时钟名）；但 codec 依赖下面**平台层**（PMIC s2mps15、CMU、PMU、电源域、bootloader 遗留状态）把电/复位/时钟**真正送到芯片脚上**。我们把平台层换成了 mainline 实现，与原厂 3.10 不同。**codec 能不能醒取决于平台层**，肉眼看不见，只能测。
- **铁证（排除驱动）**：手工 bit-bang（绕开内核驱动）也全 1；MISO 三态、IRQ 不动 ⇒ 芯片未运行。**驱动再对也没用。**
- **下一步（唯一能推进）**：① 万用表量 codec 1.8V/1.2V 供电脚 + MCLK 脚；② USB 逻辑分析仪抓 SCK/MOSI/MISO/CS + MCLK；③ 临时回刷下游内核/pmOS，对比 PMIC/PMU 寄存器值找出平台层差异；④ 把发现发到 pmOS/Exynos7420 社区。

### 18.16 ★★★★★ 根因找到并修复：S2MPS15 Rev1 LDO25/LDO26 寄存器地址对调 → codec DCVDD 从未上电！2026-09-13 02:55
- **现象**：codec 读全 `0xffff`、SDO 三态、IRQ 不动；软件/驱动/DT 全部 1:1 复刻也无解。
- **根因（厂商源码铁证）**：`include/linux/mfd/samsung/s2mps15.h`：
  ```
  S2MPS15_REG_L26CTRL_REV1 = 0x4C,   /* Rev1 上 LDO26 实际在 0x4C */
  S2MPS15_REG_L25CTRL_REV1 = 0x4D,   /* 0x4D 其实是 LDO25 */
  ```
  `drivers/regulator/s2mps15.c:921`：`desc_type = SEC_PMIC_REV(iodev) ? TYPE1 : TYPE0`；TYPE1 表里 LDO26 用 `L26CTRL_REV1`(0x4C)、LDO25 用 `L25CTRL_REV1`(0x4D)。
  **mainline `s2mps11.c` 的 `regulator_desc_s2mps15_ldo` 硬编码 `L1CTRL+num-1`，算 LDO26 永远是 Rev0 地址 0x4D**，没有 Rev0/Rev1 区分。
- **实机验证**：`i2cget -f -y 1 0x66 0x00 = 0x12` → rev=0x12&0xf=**2（Rev1）**；`0x4C=0x3c`（真 LDO26/DCVDD，bits[7:6]=00 **关着**）、`0x4D=0xe8`（mainline 误开的 LDO25/PROX_LED）。
  → **codec 的 1.2V 数字核心（DCVDD=LDO26）从头到尾没上电**，芯片 POR 锁死，SPI 不起作用。
- **★ 立刻验证**：`i2cset -f -y 1 0x66 0x4c 0xe8`（1.2V=0x28|使能0xC0）→ 加载 SPI+探针后：
  ```
  wmord spi0.0: ID=0x6338 rev=0x02  <== WM1840 CONFIRMED
  ```
  **codec 立刻应答，ID 正确！**
- **正式修复**（已改 `drivers/regulator/s2mps11.c`）：`S2MPS15X` 分支读 `S2MPS15_REG_ID`，`rev&0xf != 0`（Rev1）时 `devm_kmemdup` 一份 `s2mps15_regulators` 并把 `LDO25→0x4D`、`LDO26→0x4C` 交换，再注册。`CONFIG_REGULATOR_S2MPS11=y`（内置）→ 需重编内核 Image 刷入。
- **临时 workaround**（免重编）：开机跑 `i2cset -f -y 1 0x66 0x4c 0xe8`。
- **产物**：修复内核已编好 → `WORKING-66gnome/smp8_audio4_rev1fix.img`（27,775,008B，含新 Image + 原 ramdisk/DTBH；Image 内含 `S2MPS15 rev%u: LDO25/LDO26 register swap applied`）。构建命令带 `HOSTCFLAGS="-I scratch/hostinclude -I <openssl@3>/include" HOSTLDFLAGS="-L <openssl@3>/lib"`。
- **意义**：这颗 SoC 上所有“平台层不对齐”之谜一次解开——**根因是 PMIC Rev1 的寄存器地址互换**，与 codec 驱动/DT 无关。LDO16(AVDD) 未受影响的巧合让我们一直误以为供电正常。
- **★★★ 修复内核实测（2026-09-13 03:05）**：刷入 `smp8_audio4_rev1fix.img` 后开机，**无需任何手动 i2cset**：
  ```
  [0.753] s2mps11-pmic s2mps15-regulator: S2MPS15 rev2: LDO25/LDO26 register swap applied
  LDO26(0x4c)=0xe8
  wmord spi0.0: ID=0x6338 rev=0x02  <== WM1840 CONFIRMED
  ```
  **codec 在 mainline 上首次成功应答！根因与修复均验证通过。** 后续即可正常加载 `madera`/`cs47l85` + 机器驱动 + I2S 做完整音频。

---

## 附录 A：历史疑难（USB 未通阶段，现已解决，留档）

- MAX77833 MUIC 需在 Linux 内经 i2c-gpio 写 `0x0f=0x04,0x10=0x09`(`SW_USB`),否则 D+/D- 模拟开关不导通 → 电脑端看不到设备。**现已通过 `/init` 里的 MUIC 切换解决。**
- hsi2c 总线挂死 → 改 i2c-gpio(见 §3 关键修复 #3)。
