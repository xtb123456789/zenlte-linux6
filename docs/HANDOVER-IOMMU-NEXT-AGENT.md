# 交接文档：SM-G9280 (Exynos7420 zenlte) mainline 6.6 —— 显示 IOMMU/SYSMMU 攻坚

## 0. 一句话现状

设备**当前处于卡死状态**（刚刷了 `boot_bt_iommu14.img`，开机黑屏、光标不闪、串口无响应）。
需要先 TWRP 恢复，再继续。**GPU 硬件加速未完成**；WiFi/蓝牙/浏览器/桌面/2x 缩放均已完成且稳定。

## 1. 目标

让 Exynos DECON（显示控制器 `13930000.decon`）挂到 SYSMMU/IOMMU 上，
使 `exynos_drm_gem` 能接受 Panfrost 输出的**非连续 dma-buf**（当前报
`buffer chunks must be mapped contiguously` 而拒收），从而恢复 GNOME 硬件加速合成。

硬件：Exynos7420，DISP 两个 SYSMMU：`13a00000`(RO, SPI 176)、`13a10000`(RW, SPI 179)。
SysMMU 版本 v6（`0x13a00034 = 0x60020014`，解码 major=6 → mainline 走 `sysmmu_v5_variant`，寄存器布局与 v5 一致）。

## 2. 当前最关键的已验证结论

### 2.1 IOMMU 域建立完全正常（iommu12 串口日志，实锤）

```
IOMMU: of_xlate master=13930000.decon sysmmu=13a00000.sysmmu
IOMMU: of_xlate master=13930000.decon sysmmu=13a10000.sysmmu
exynos-decon 13930000.decon: Adding to iommu group 0
IOMMU: attach master=13930000.decon
IOMMU: attach sysmmu=13a00000.sysmmu active=0     <-- SYSMMU 未激活
IOMMU: attach sysmmu=13a10000.sysmmu active=0     <-- SYSMMU 未激活
[drm] Exynos DRM: using 13930000.decon device for DMA mapping operations
exynos-drm exynos-drm: bound 13930000.decon (ops decon_component_ops [exynosdrm])
[drm] Initialized exynos 1.1.0 20180330 for exynos-drm on minor 2
exynos-drm exynos-drm: [drm] fb1: exynosdrmfb frame buffer device
```

→ IOMMU 域、iommu_group、DRM component bind、fbdev 全部成功，
**唯独 SYSMMU 硬件没有被 enable**（mainline `exynos_iommu_attach_device()` 里
`if (pm_runtime_active(data->sysmmu)) __sysmmu_enable(data);` 条件不成立）。
→ DECON 用 IOVA 地址做扫描输出但 SYSMMU 不翻译 → 黑屏 → 后续 AXI 卡死。

### 2.2 强行在 attach 时 enable → 卡死

把 attach 改成**无条件** `__sysmmu_enable(data)`（iommu13/14）后，
串口/屏幕最后一条是 `IOMMU: attach master=13930000.decon`，随后整机卡死
（SYSMMU 寄存器访问挂死）。

**结论：在 DECON component bind 那一刻访问 SYSMMU 寄存器会挂**，
即使 CCF 层面 `clk_prepare_enable(aclk/pclk)` 都执行了。

### 2.3 最新线索（下一步要验证的）

mainline `exynos-iommu.c` 里 SYSMMU 支持**第 3 个时钟 `master`**：

```c
struct clk *clk_master;   /* master's device clock */
...
static void __sysmmu_enable_clocks(struct sysmmu_drvdata *data)
{
	BUG_ON(clk_prepare_enable(data->clk_master));
	BUG_ON(clk_prepare_enable(data->clk));
	BUG_ON(clk_prepare_enable(data->pclk));
	BUG_ON(clk_prepare_enable(data->aclk));
}
```

它在**访问 SYSMMU 寄存器期间持有 master（master 设备的时钟）**；
厂商驱动同样有 `__master_clk_enable(drvdata)` 包住硬件访问。

**但我们的 DTS 里 SYSMMU 节点只给了 `aclk`/`pclk`，没有 `master`** →
`clk_master == NULL` → 寄存器访问时缺少 master 侧时钟 → 怀疑正是卡死原因。

绑定文档 `Documentation/devicetree/bindings/iommu/samsung,sysmmu.yaml` 允许：
`clock-names = "sysmmu"` / `"sysmmu","master"` / `"aclk","pclk"`（三选一）。

**下一步实验**：给两个 SYSMMU 节点加 master 时钟（= DECON 的 aclk）：

```dts
sysmmu_disp_ro: sysmmu@13a00000 {
	compatible = "samsung,exynos-sysmmu";
	reg = <0x13a00000 0x1000>;
	interrupts = <GIC_SPI 176 IRQ_TYPE_LEVEL_HIGH>;
	clocks = <&cmu_disp CLK_ACLK_DISP_RO_SYSMMU>,
		 <&cmu_disp CLK_PCLK_DISP_RO_SYSMMU>,
		 <&cmu_disp CLK_ACLK_DECON0>;
	clock-names = "aclk", "pclk", "master";
	#iommu-cells = <0>;
};
```
（`13a10000` 同理，aclk 用 `CLK_ACLK_DISP_RW_SYSMMU`。）

## 3. 已经踩过并排除的坑（务必不要再犯）

1. **pd_disp 是雷**：mainline genpd 的通用上电序列**缺少厂商的 TZPC SMC**
   （`arch/arm64/mach-exynos/pm_domains-exynos7420.c`：
   `exynos_smc(MC_FC_SET_CFW_PROT, MC_FC_DRM_SET_CFW_PROT, CFW_DISP_RW, 0)`
   注释 "TZPC should be enabled at every power on"）。
   只要有设备挂 `power-domains = <&pd_disp>` 触发 genpd 上电/断电，就会挂死。
   → **当前 DTS 里 SYSMMU 和 DECON 都不挂 power-domains**，DISP 域保持 bootloader 状态（0xf）。
   （`pd_disp` 正确基址 = `0x105c4080`，厂商 DT 与寄存器实测均确认；mainline 原写的 0x105c4120 是错的。）
2. **打包用的 DT 是 DTBH 容器文件**（`WORKING-66bt/new_dt_mod2.img`）。
   DTS 改完必须重新生成：`python3 mkdtbh.py <新编的 .dtb> new_dt_mod2.img`，
   否则 DTS 改动**完全不生效**（曾因此浪费数轮实验）。
3. **cmdline**：`console=tty0`（内核日志走屏幕）。
   加 `console=ttyGS0,115200` 可从 USB 串口抓内核日志，**但主机若不持续读取会阻塞内核 printk**（会假卡死）。
   当前 cmdline：`console=tty0 maxcpus=8 loglevel=8 init=/init rw clk_ignore_unused pd_ignore_unused fw_devlink=permissive`
   （`CONFIG_CMDLINE_FORCE=y`）。
4. **模块（=m）方案的边界**：
   - 运行期 `insmod exynos-iommu.ko`：SYSMMU 能 bind，但 DECON 不会重挂
     （`exynos_drm_register_dma()` 只在 probe 执行一次）。
   - 开机早期 `insmod`（systemd 服务）：卡死（DISP 时钟未起）。
   - 运行期 insmod + rmmod/insmod DRM：GNOME 能起来（带 IOMMU），但随后显示冻住/设备重启，不稳定。
5. **内建（=y）**：无 pd_disp 挂载时能开机（`boot_bt_iommu11.img`），
   但 DRM attach 后黑屏（同 §2.1 原因）。

## 4. 环境 / 工具 / 操作

### 4.1 目录与工具
- 内核树：`/Volumes/kernel_build/linux-6.6`（**路径不能含空格**，否则 kbuild 报错）
- 厂商树：`/Volumes/kernel_build/kernel`（3.10.61，`drivers/iommu/exynos-iommu-v6.c`、`arch/arm64/mach-exynos/pm_domains-exynos7420.c` 是主要参考）
- 镜像/模块：`/Users/macintosh/.gemini/antigravity/scratch/WORKING-66bt/`
  - `boot_bt_iommu_mod2.img` = **稳定可启动镜像**（=m 版）
  - `boot_bt_iommu11.img` = 内建 =y、无 pd_disp、能开机但黑屏
  - `boot_bt_iommu12.img` = 内建 + 打点（日志见 §2.1）
  - `boot_bt_iommu13/14.img` = 内建 + 无条件 enable（卡死）
  - `new_dt_mod2.img` = DTBH 容器（当前 DTS 编出）
  - `exynosdrm-iommu.ko`（676600B，带 IOMMU 的 DRM 模块）、`exynos-iommu.ko`（160216B）
- 打包器：`/Users/macintosh/.gemini/antigravity/brain/1aa1eae7-f290-4c11-ae7f-9444617f1cf3/scratch/{mkbootimg_7420.py,mkdtbh.py}`
- 串口工具：`/Users/macintosh/.gemini/antigravity/scratch/WORKING-66gpu/tools/{acm.py,send_b64.py}`
  （串口 `/dev/cu.usbmodem2301` 或 `2302`；`acm.py '<cmd>'` 执行命令，`send_b64.py <local> <remote>` 传文件）

### 4.2 构建
```bash
T=/Volumes/kernel_build/linux-6.6
TOOL=/Volumes/xtb/linux-backup-20260912/toolchain-aarch64/aarch64-unknown-linux-gnu/bin/aarch64-linux-gnu-
export HOSTCFLAGS="-I/Users/macintosh/.gemini/antigravity/scratch/hostinclude -I/opt/homebrew/var/homebrew/tmp/.cellar/openssl@3/3.6.4/include"
export HOSTLDFLAGS="-L/opt/homebrew/var/homebrew/tmp/.cellar/openssl@3/3.6.4/lib"
cd $T && gmake ARCH=arm64 CROSS_COMPILE=$TOOL -j8 Image modules dtbs
```
打包（DTB 变了要先 mkdtbh）：
```bash
cd WORKING-66bt
python3 $P/mkdtbh.py $T/arch/arm64/boot/dts/exynos/exynos7420-zenlte.dtb new_dt_mod2.img
python3 $P/mkbootimg_7420.py $T/arch/arm64/boot/Image good_boot/ramdisk.cpio.gz new_dt_mod2.img boot_bt_iommuXX.img
```

### 4.3 刷机 / 恢复（TWRP + adb）
进入 TWRP（长按电源 12s 关机 → Vol+ + Home + Power），`adb devices` 出现 recovery 后：
```bash
# 刷 boot
adb push boot_bt_iommuXX.img /tmp/boot.img
adb shell "dd if=/tmp/boot.img of=/dev/block/sda7 bs=4096; sync"
# 恢复稳定组合（=m 镜像 + 旧 DRM 模块）
adb shell "dd if=/tmp/boot_mod2.img of=/dev/block/sda7 bs=4096; sync; mkdir -p /mnt/rootfs; mount -t ext4 /dev/block/sda18 /mnt/rootfs; cp /mnt/rootfs/ubuntu/root/exynosdrm.ko.bak /mnt/rootfs/ubuntu/lib/modules/6.6.0/extra/exynosdrm.ko; sync"
adb reboot
```
- 设备内 rootfs 路径：`/lib/modules/6.6.0/extra/exynosdrm.ko`（TWRP 下 `/mnt/rootfs/ubuntu/...`）
- DRM 加载服务：`/etc/systemd/system/exynosdrm-load.service` → `/usr/local/bin/loadko <ko>`
- 旧 DRM 备份：`/root/exynosdrm.ko.bak`（671840B，无 IOMMU）
- 新 DRM 模块（带 IOMMU）：`/root/exynosdrm-iommu.ko`（676600B）
- 屏幕缩放：`/root/.config/monitors.xml`（Unknown-1 与 VGA-1 均 scale=2）

## 5. 内核树当前改动清单

| 文件 | 改动 |
|---|---|
| `drivers/iommu/exynos-iommu.c` | ① `exynos_iommu_ops` 加 `.owner = THIS_MODULE`（修模块化时 `iommu_device_register()` 的 `-EINVAL`）② probe 不再读版本寄存器，静态 `MAKE_MMU_VER(6,0)` + `sysmmu_v5_variant` ③ probe 失败回滚 `pm_runtime_disable` + `dma_dev=NULL` ④ `module_init/module_exit` ⑤ `exynos_iommu_of_xlate()` 未 probe 时返回 `-EPROBE_DEFER`（原 `-ENODEV`）⑥ **attach 里无条件 `__sysmmu_enable()`（iommu13+，当前状态，会卡死）** ⑦ 多处 `pr_emerg("IOMMU: ...")` 打点 |
| `drivers/iommu/Kconfig` | `EXYNOS_IOMMU` bool→tristate |
| `drivers/clk/samsung/clk-exynos7.c` | 新增 4 个 DISP SYSMMU 门控（`0x0804/0x0808/0x0904/0x0908` bit0，flags=0；父 `top_aclk_disp_400`） |
| `include/dt-bindings/clock/exynos7-clk.h` | 新增 4 个 clock ID（12–15），`DISP_NR_CLK=16` |
| `arch/arm64/boot/dts/exynos/exynos7.dtsi` | 新增 `sysmmu_disp_ro/rw` 节点（**无 power-domains**，只有 aclk/pclk）② DECON 加 `iommus = <&sysmmu_disp_ro>, <&sysmmu_disp_rw>`（**无 power-domains**）③ `pd_disp` = `power-domain@105c4080` + `samsung,exynos7420-pd` |
| `drivers/pmdomain/samsung/exynos-pm-domains.c` | `samsung,exynos7420-pd` 匹配 + DISP pre/post 序列（**注意：缺 TZPC SMC，不能真的用它上电**） |
| `drivers/gpu/drm/exynos/exynos_drm_dma.c` | IOMMU 未就绪且有 `iommus` 时 `-EPROBE_DEFER`（不缓存"无 IOMMU"状态） |
| `.config` | `CONFIG_EXYNOS_IOMMU=y`（当前）；`CONFIG_CMDLINE` 见 §3.3 |

## 6. 建议的下一步（按优先级）

1. **给 SYSMMU 加 `master` 时钟**（§2.3）→ 重编（注意重新生成 DTBH）→ 刷机验证。
   若黑屏消失、GNOME 流畅 → 成功，随后去掉 `WEBKIT_DISABLE_DMABUF_RENDERER=1` 等软件渲染绕过再测。
2. 若仍卡死：**对齐厂商做法** —— 不要在 attach 阶段硬开 SYSMMU，
   而是修 runtime-PM 传递：让 DECON 的 runtime-resume 经 device_link 真正拉起 SYSMMU 的
   `exynos_sysmmu_resume()`（其中 `if (data->domain) __sysmmu_enable(data)`）。
   需要先查 `/sys/kernel/debug/pm_genpd/*`、`/sys/bus/platform/devices/*.sysmmu/power/runtime_status`
   确认 device_link 是否存在/传播。
3. 备选：写一个小的 helper（供 DECON 在 `decon_enable`/首次 modeset 后调用），
   在 DECON 真正上电（runtime resume 完成、时钟确实在跑）之后再 `__sysmmu_enable()`。

## 7. 参考：厂商实现要点（`/Volumes/kernel_build/kernel`）

- `drivers/iommu/exynos-iommu-v6.c`：
  - probe 只 `clk_prepare()`（不 enable）、不读版本寄存器；
  - `__sysmmu_enable()` 里 `if (is_sysmmu_runtime_active())` 才 `__master_clk_enable()` + `__sysmmu_enable_nocount()` + `__master_clk_disable()`；
  - `exynos_sysmmu_probe` 用 `pm_runtime_enable` + `__sysmmu_setup`。
- `arch/arm64/mach-exynos/pm_domains-exynos7420.c`：
  - `exynos_pd_power_on_pre`：先开 top→local 时钟、async-bridge 时钟，再清 sys_pwr regs；
  - `exynos_pd_power_on_post`：`exynos_restore_sfr(save_list)`；**pd-disp 额外调 TZPC SMC**；
  - DISP 域寄存器：`0x105c4080`，`LOCAL_PWR_CFG=0xf`，`OPTION(base+0x8)=0x0102`。
- 厂商 DT：SYSMMU 节点**没有 power-domains**，只有 `clocks = aclk,pclk`；
  `sysmmu,block-when-stop`、`pb-info` 等属性 mainline 不使用。

## 8. 其它已完成的系统状态（不要破坏）

- 蓝牙：UART4/LPASS 路径 + `aclk_peric1_66` critical + AUD pad retention，服务 `exynos7420-bt-power.service`
- 桌面：`/root/.bash_profile` 里 `dbus-run-session` 启动 gnome-shell（tty1），含软件渲染绕过（IOMMU 修好后可去掉）
- 服务：`exynos7420-{backlight,bt-power,dvfs,pcie,reboot,smp}.service`、`exynosdrm-load.service`
- 触摸：`stmfts-load.service`；WiFi：`exynos7420-pcie.service` + brcmfmac
