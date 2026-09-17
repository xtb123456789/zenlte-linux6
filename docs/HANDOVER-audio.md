# 交接文档 — SM-G9280 (Exynos7420 "zenlte") mainline Linux 6.6 音频攻关

> 写于 2026-09-13 03:10。给下一个 AI 的**自包含**交接。完整长文档见
> `~/Desktop/S6EdgePlus-Linux6-status/S6EdgePlus-Linux6-status.md`（§18.15/§18.16 是重点）。

---

## 0. 一句话现状

**整条音频链已在 mainline 上跑通并注册出声卡：codec probe（WM1840 rev2）、ADMA（PL330）绑定、I2S 就绪，`/proc/asound/cards` → `zenltewm1840`。当前卡在最后一步：播放时 DMA 传输报 -EIO，清了 `0x10ef0000` 后甚至卡死整机——疑似 mainline `pl330` 缺 Exynos7420 的 `pl330_fixup_ctrl` + `#dma-mcode-addr`（LPASS SRAM）支持。详见 §7/§8。**

---

## 1. 环境

- 设备：三星 Galaxy S6 Edge+ **SM-G9280 / Exynos7420 / 代号 zenlte / hw_rev=9**。
- 目标：跑**主线 Linux 6.6 LTS**（非 Android）。rootfs = Ubuntu 24.04 ARM64（sda18）。
- 控制通道：设备 Linux 的 **USB CDC ACM 串口**（`/dev/cu.usbmodem*`，115200）。
  - Host 助手：`/Users/macintosh/.gemini/antigravity/scratch/WORKING-66gpu/tools/acm.py "cmd1" "cmd2"`（跑命令）、`send_b64.py <local> <remote>`（推文件）。
- 刷机：设备进 TWRP 后用 **adb**（`adb push xxx.img /tmp/; adb shell "dd if=/tmp/xxx.img of=/dev/block/sda7 bs=4096; sync"`）。
  - `sda7=BOOT(28MB)`，**只刷 sda7**；`sda8=TWRP`（后盾，绝不刷）；`sda18=rootfs`。
- 内核源码树：`/Users/macintosh/.gemini/antigravity/scratch/build/linux-6.6`
- 构建工具链：`/Volumes/xtb/linux-backup-20260912/toolchain-aarch64/aarch64-unknown-linux-gnu/bin/aarch64-linux-gnu-`
- 构建命令（macOS 特供：需补 `elf.h`/openssl 头）：
  ```
  gmake -C /Users/macintosh/.gemini/antigravity/scratch/build/linux-6.6 ARCH=arm64 \
    CROSS_COMPILE=/Volumes/xtb/linux-backup-20260912/toolchain-aarch64/aarch64-unknown-linux-gnu/bin/aarch64-linux-gnu- \
    HOSTCFLAGS="-I/Users/macintosh/.gemini/antigravity/scratch/hostinclude -I/opt/homebrew/var/homebrew/tmp/.cellar/openssl@3/3.6.4/include" \
    HOSTLDFLAGS="-L/opt/homebrew/var/homebrew/tmp/.cellar/openssl@3/3.6.4/lib" \
    Image -j8
  ```
  模块：把 `Image` 换成 `M=drivers/xxx modules`（本会话编译过 spi/regulator 等模块）。
- 文件大小写：`gmake`（macOS 自带 make 3.81 太老，必须用 homebrew 的 `gmake` 4.4）。

---

## 2. ★ 已解决的核心难题（务必先懂这段）

**现象**：内核 probe codec 读寄存器 `0x00 (SOFTWARE_RESET)` 恒返回 `0xffff`（应 `0x6338`）；
SDO/MISO 三态、IRQ 不动；手工 bit-bang 也一样；DT/驱动 1:1 复刻无效。

**根因**：**S2MPS15 PMIC 的 Rev1（量产）芯片把 LDO25/LDO26 寄存器地址对调了**。
- 厂商证据：`include/linux/mfd/samsung/s2mps15.h`：
  `S2MPS15_REG_L26CTRL_REV1 = 0x4C`、`S2MPS15_REG_L25CTRL_REV1 = 0x4D`
  驱动 `drivers/regulator/s2mps15.c:921`：`desc_type = SEC_PMIC_REV ? TYPE1 : TYPE0`。
- **mainline `drivers/regulator/s2mps11.c` 按 Rev0 硬编码 `S2MPS15_REG_L1CTRL + num - 1`**，
  算 LDO26 永远是 `0x4D`（Rev0 地址）。
- 结果：**codec 的 DCVDD（1.2V 数字核心）实际在 `0x4C`，从未被使能** → 芯片 POR 锁死 → SPI 全 `ffff`。
- 本机 `i2cget -f -y 1 0x66 0x00 = 0x12` → rev=2（Rev1）；`0x4C` 曾是 `0x3c`（关），`0x4D=0xe8`（被 mainline 误当 LDO26 打开，其实是 LDO25）。

**已实施的修复**（在 `drivers/regulator/s2mps11.c` 的 `S2MPS15X` case）：
读 `S2MPS15_REG_ID`，`rev & 0xf != 0` 时 `devm_kmemdup` 一份 `s2mps15_regulators`，
把 `LDO25 -> 0x4D`、`LDO26 -> 0x4C` 交换后再注册。
`CONFIG_REGULATOR_S2MPS11=y`（内置）→ 必须重编 Image。

**验证（已刷入并生效，无需任何手动操作）**：
```
[0.753] s2mps11-pmic s2mps15-regulator: S2MPS15 rev2: LDO25/LDO26 register swap applied
LDO26(0x4c)=0xe8
wmord spi0.0: ID=0x6338 rev=0x02  <== WM1840 CONFIRMED
```

**临时 workaround（不重编时）**：开机 `i2cset -f -y 1 0x66 0x4c 0xe8`
（或 systemd oneshot 服务 `/etc/systemd/system/codec-ldo26.service`）。

> 影响面：**所有 S2MPS15 Rev1 设备**（S6/S6 Edge/Edge+/Note5）在 mainline 都会踩这个坑。
> 该 patch 值得 upstream，并同步给 postmarketOS / `github.com/Exynos7420/linux`（他们音频都没通，pmOS 把 WM1840 标 `Mainline: N`）。

---

## 3. 当前产物 / 路径

- **当前已刷入的可开机镜像**：`/Users/macintosh/.gemini/antigravity/scratch/WORKING-66gnome/smp8_audio4_rev1fix.img`（27,775,008B）
  = 修复后的 Image + 原 ramdisk + 厂商 1:1 DTBH 容器。备份在
  `/Volumes/xtb/linux-backup-20260912/vendor1to1/`（含 img、dtb、dt.img、`s2mps11.c.rev1fix`）。
- 打包工具（**关键**）：DT 区必须是 **Samsung DTBH v2 容器**，不能塞裸 FDT（否则卡 logo）：
  - `mkdtbh.py <x.dtb> <dt.img>`（→ `~/.gemini/antigravity/brain/1aa1eae7-.../scratch/mkdtbh.py`）
  - `mkbootimg_7420.py <kernel> <ramdisk.cpio.gz> <dt.img> <out.img> [cmdline]`（同目录）
- 音频模块（预编译，放设备 `/root/audio-modules/`）：`snd*.ko`、`cs_dsp.ko`、`madera.ko`、`madera-spi.ko`、`snd-soc-madera.ko`、`snd-soc-cs47l85.ko`、`snd-soc-i2s.ko`、`snd-soc-simple-card*.ko`、`pl330.ko` 等。
  - **补遗漏**：还需 `irq-madera.ko`（源码树 `drivers/irqchip/irq-madera.ko`，vermagic 6.6.0）。
    原列表没有它，缺了 `cs47l85-codec` 会一直 `-EPROBE_DEFER`（判据 `!madera->irq_dev`）。
    已推送至设备 `/root/audio-modules/irq-madera.ko`。
- 现场用的探针模块（在设备 `/root/`）：`spi-cs.ko`（新编、稳定的 SPI 控制器；旧 `/root/audio-modules/spi-s3c64xx.ko` 会整机卡死，已弃用）、`wmord.ko`（读 codec ID）、`spi3w/spiscope` 等。
- **旧 SPI 模块警告**：`/root/audio-modules/spi-s3c64xx.ko` 一加载就硬挂整机（根因是旧构建坏），**用 `/root/spi-cs.ko` 或重新编**。

---

## 4. 音频链现状（下一步的起点）

**DTS（`arch/arm64/boot/dts/exynos/exynos7420-zenlte.dts`，即镜像里的 DTB）**：
- codec：`&spi_0 { wm1840: audio-codec@0 { compatible="cirrus,wm1840"; ... } }`（已 1:1 厂商：25MHz、`cs-gpios=<&gpd8 1 ACTIVE_LOW>`、`codec-reset`/`codec-irq` pinctrl、全供电指 ldo16/ldo26）。
- `&i2s0 { status="okay"; }`；`/ { sound { compatible="simple-audio-card"; cpu=<&i2s0 0>; codec=<&wm1840 0>; }; }`。
- `&wm1840 { #sound-dai-cells = <1>; }`。
- adma：`dma-controller@11420000`（见 `exynos7.dtsi`/板级）。i2s0 引脚在独立 AUD pinctrl `pinctrl@114B0000`（**mainline 暂无该 pinctrl 块，需补**）。

**内核配置**（已开，模块化）：`CONFIG_SND=m`、`SND_SOC=m`、`SND_SOC_SAMSUNG=m`、`SND_SAMSUNG_I2S=m`、`SND_SIMPLE_CARD=m`、`MFD_MADERA=m`、`MFD_MADERA_SPI=m`、`MFD_CS47L85=y`、`SND_SOC_MADERA=m`、`SND_SOC_CS47L85=m`、`PL330_DMA=m`。

**厂商 3.10 的处理**（参考 `github.com/Exynos7420/linux` 没有音频，pmOS 只有下游内核有）：
- 机器驱动 `sound/soc/samsung/noble_arizona.c`：播放时 `noble_change_mclk()` →
  `clk_enable(clkout)` + `exynos5_audio_set_mclk(true)`（写 `PMU_DEBUG=0x1000`，CLKOUT=XXTI 24MHz）
  + `gpio_set_value(clk_sel_gpio=<gpf5 6>, ...)`；再 `set_pll/set_sysclk`(FLL3→SYSCLK)。
- `sound` 节点 `clocks=<&clock 45>` = `clkout`。
- 另有厂商 `samsung-lpass` 平台驱动（`lpass.c`+`lpass-exynos7420.c`）开 CMU_AUD 门控 + AUD pad release；
  **本项目已复刻**为 `lpassinit.ko`（`WORKING-66audio/` 有源码，`/Volumes/xtb/.../vendor1to1/lpassinit.ko`），
  实测 CMU_AUD `ACLK/PCLK/SCLK` 门控已开、PMU `0x1340=1`。

**下一步建议顺序**：
1. 在设备上按序 `loadko` 加载 codec+snd 栈（见 §3 列表），看 `madera` 是否读到 `0x6338`、`cs47l85-codec` 是否 probe。
2. 让 `simple-audio-card` 注册成功（`aplay -l` 能列出 zenlte-wm1840）。缺什么补什么（I2S 驱动/时钟/pinctrl/adma）。
3. I2S MCLK 打开：在 simple-card 或一个小 machine driver 里复刻 `noble_change_mclk`（`clkout` + `PMU_DEBUG=0x1000`）。
   （注意：mainline 无 `clkout` clock 节点，需在 `clk-exynos7.c` 补，或直接写 PMU_DEBUG。）
4. 播放验证（`aplay`），必要时补 DSP 固件（`clearwaterc-dsp*.wmfw`，见 `WORKING-66audio/android_captures/firmware/`）。
5. codec 子驱动需要的供电名：`DBVDD2/3/4`、`CPVDD2`、`SPKVDDL/R`、`MICVDD`（DTS 已加，均指 `ldo16`）。

---

## 5. 踩坑清单（别再犯）

1. **DTB 必须 DTBH 容器**：`repack_dt.py` 传裸 FDT → 卡 logo。用 `mkdtbh.py` 先打包。
2. **旧 SPI 模块硬挂**：`/root/audio-modules/spi-s3c64xx.ko` 加载即死机；用新编的 `/root/spi-cs.ko`。
3. **`s3c64xx` autosuspend=2s 会卡**：本会话构建的模块已改 600s 规避。
4. **串口 getty 常掉**：开机后若串口无响应，在手机屏上 `systemctl restart serial-getty@ttyGS0`。
5. **`i2cset` 只是临时手段**：永久修复在 Image 里（s2mps11 patch）。
6. **加载 madera-spi 有时会硬挂**（IRQ gpa2-5 电平触发风暴）；诊断时可先只加载 SPI 控制器 + 自写探针。
7. **不要用 `/dev/mem` 硬写 CMU_AUD/时钟寄存器**（曾把整机写挂）；用 clk 框架或正规模块。
8. **别读未上电的 ADMA**：`/root/admaread.ko`（ioremap `0x11420000` 读寄存器）一加载就整机卡死。
   在补上 AUD 电源域之前，任何对 `11420000` 寄存器块的读写都会触发总线 abort。**严禁再加载 `admaread.ko`。**
9. **`/dev/mem` 现在读被拒**（`PermissionError`，strict devmem），旧脚本 `regdump.py`/`pmudump.py` 已不能直接用。

---

## 6. 重要路径速查

| 用途 | 路径 |
|---|---|
| 完整状态长文档 | `~/Desktop/S6EdgePlus-Linux6-status/S6EdgePlus-Linux6-status.md`（§18.16 = 根因） |
| 内核源码树 | `~/.gemini/antigravity/scratch/build/linux-6.6` |
| 当前镜像 | `.../scratch/WORKING-66gnome/smp8_audio4_rev1fix.img` |
| 串口助手 | `.../scratch/WORKING-66gpu/tools/{acm.py,send_b64.py}` |
| DTBH/打包工具 | `~/.gemini/antigravity/brain/1aa1eae7-f290-4c11-ae7f-9444617f1cf3/scratch/{mkdtbh.py,mkbootimg_7420.py}` |
| 音频模块/抓取 | `.../scratch/WORKING-66audio/`（`audio-modules/`、`android_captures/`、`lpassinit.c`） |
| 全量备份 | `/Volumes/xtb/linux-backup-20260912/`（含 `vendor1to1/`、`status/`） |

---

## 7. 续作进展与当前阻塞（2026-09-13 续，下一个 AI 接手后）

### 7.1 已完成：codec 链成立
按 §4 顺序加载全部走通：
- `/root/spi-cs.ko` → `spi0.0` 枚举，`s3c64xx-spi ... registered OK`（无卡死）。
- `snd` 核心栈 + `cs_dsp` + `snd-soc-wm-adsp` + `madera` + `snd-soc-madera` + `snd-soc-cs47l85` 全部 load OK。
- `madera-spi.ko` → `[187] madera spi0.0: WM1840 silicon revision 2`；供电 alias（MICVDD/DBVDD*/CPVDD*/SPKVDD*）正常。
- **缺模块 `irq-madera.ko`**：加载前 `cs47l85-codec` 一直 deferred（`!madera->irq_dev`）；
  推送并 `loadko` 后 → `cs47l85-codec` 绑定成功，`wake enabled for irq 58 (gpa2-5)`，**无 IRQ 风暴**。
- `snd-soc-i2s`/`simple-card` 模块 load OK，但 `11440000.i2s` 与 `sound` 均进入 deferred
  （`devices_deferred` 里 `sound` 显示 `asoc-simple-card: parse error`，实为 EPROBE_DEFER）。

### 7.2 ★ 当前阻塞：ADMA（`11420000.dma-controller`）无法 probe（根因已细化）
- 表象：`/sys/kernel/debug/devices_deferred` 永久含 `11420000.dma-controller`；
  `uevent` → **`AMBA_ID=00000000`**。`amba_match()` 在 periphid==0 时调 `amba_read_periphid()`，
  读失败即 `-EPROBE_DEFER`；`pl330` 要求 `0x00041330`，读到 0 → 永不匹配。
- **不是电源域没开**：自建 `audpower.ko` 读 PMU：`0x105c4000=0x0000000f`、`0x105c4004=0x0003000f`
  （`LOCAL_PWR_CFG=0xf`，STATUS 已 on）。AUD 域**开机就是上电的**，写 0xF 前后无变化。
- **真正卡点是 AUD 局部块的时钟/复位**：
  - ADMA 总线门控 = CMU_AUD `0x114c0800`（`ENABLE_ACLK_AUD`）**bit31 = `aclk_dmac`**。
    mainline CCF 极性是 **1=enable**（`clk_hw_register_gate` 默认，`gate_flags=0`）。
    开机时 bit31=0 → 门控关；此时读 `0x11420000` 会**停总线整机卡死**（`admaread.ko` 首次即如此）。
  - 用 `of_clk_get(adma_dt_node, 0)` + `clk_prepare_enable()`（模块 `audclk3.ko`）把 bit31 置 1
    （`0x3fffffff → 0xbfffffff`），`clk_summary` 中 `aclk_dmac` 变 **Y/enabled**；此后读**不再卡死**。
  - **但 ADMA 寄存器全读 0**（`admard3.ko`：`pid=0 cr0=0 crd=0`），且读 `0x11420000` 仍会触发
    **synchronous external abort（SError oops，`admard4.ko`）** → 块仍处于复位/不可访问状态。
  - `lpassinit.ko` 是**裸写** CMU 门控，但 mainline CCF 的状态与之不一致，会相互覆盖；
    厂商 `lpass_release_pad_reg`（PMU `0x3028 bit28`）实测无效（该寄存器恒读 0）。
- 结论：不是“补个 pd_aud 就行”，而是 **AUD 局部子系统的时钟/电源/异步桥/复位整套** mainline 都没有建模。
  这也正是 Exynos7420 音频在 mainline/postmarketOS 一直不通的根因。

### 7.3 下一步候选（按优先级）
1. **移植厂商 pd-aud 整套**（唯一正路）。参考已在本机的厂商树
   `/Users/macintosh/.gemini/antigravity/scratch/build/kernel/`：
   - `arch/arm64/mach-exynos/pm_domains-exynos7420.c/.h` + `pm_domains-exynos7420-cal.h`
     （`local_clks_aud` = `ENABLE_ACLK_AUD` bit28 等；`sys_pwr_regs_aud` 9 个 PMU 寄存器清零；
      `LOCAL_PWR_CFG=0xf` 写 `0x105c4000` 轮询 `+0x4`）。
   - `arch/arm64/mach-exynos/include/mach/regs-pmu-exynos7420.h`、`regs-clock-exynos7420.h`、
     `arch/arm/.../pmu-exynos7420.c`（`exynos7420_pmu_init` / `pmu_cal_sys_init`）。
   - 厂商 `pd_aud@105c4000` 兼容 `samsung,exynos-pd`（mainline 对应 `samsung,exynos5433-pd`，
     `drivers/pmdomain/samsung/exynos-pm-domains.c`，已 built-in）。
2. DT：加 `pd_aud: power-domain@105c4000 { #power-domain-cells=<0>; }`，给 `adma`/`i2s0`
   加 `power-domains = <&pd_aud>`；并给 ADMA 补 `arm,primecell-periphid = <0x00041330>`
   （防御性，避免 periphid 依赖扫描时时钟已开）。
3. I2S 的 AUD pinctrl（`0x114B0000`）mainline 缺失，出声前仍需补。
4. MCLK 的 `clkout`（`clk-exynos7.c` 补节点，或复刻 `noble_change_mclk` 写 `PMU_DEBUG=0x1000`）。

### 7.3b 设备上遗留的实验模块（下次可复用，注意风险）
`/root/audpower.ko`（读/写 AUD 上电）、`audclk.ko`/`audclk2.ko`/`audclk3.ko`（用 CCF 开 ADMA 时钟；
`audclk3` 会泄漏一个 enable，保持 `aclk_dmac` 常开）、`admard3.ko`（只读 ADMA，安全）、
`admard4.ko`（读 I2S，会 SError oops）、`audpad.ko`（PMU 0x3028/0x1340）、`admaread.ko`（**会卡死，别用**）。

### 7.4 复现用模块加载顺序（重启后，勿含 admaread / playtone）
```
/root/loadko /root/spi-cs.ko
for m in snd snd-timer snd-pcm snd-pcm-dmaengine snd-compress snd-soc-core; do /root/loadko /root/audio-modules/$m.ko; done
for m in cs_dsp snd-soc-wm-adsp madera snd-soc-madera snd-soc-cs47l85; do /root/loadko /root/audio-modules/$m.ko; done
/root/loadko /root/audio-modules/madera-spi.ko
/root/loadko /root/audio-modules/irq-madera.ko     # 关键，原音频模块列表缺
/root/loadko /root/audio-modules/pl330.ko
/root/loadko /root/lpassup.ko                       # ★关键：开全 AUD 门控 + AUD_OPTION
echo 11420000.dma-controller > /sys/bus/amba/drivers_probe   # ADMA 绑定
for m in snd-soc-idma snd-soc-s3c-dma snd-soc-i2s snd-soc-simple-card-utils snd-soc-simple-card; do /root/loadko /root/audio-modules/$m.ko; done
```

---

## 8. ★ 运行时突破（2026-09-13 续）：ADMA 绑定 + 声卡注册成功

### 8.1 关键：ADMA 卡死不是缺电源域，而是 AUD 门控没全开
- `0x105c4000`（AUD_CONFIGURATION）**一直是 `0xf`**，`0x105c4004=0x0003000f` → 域早就上电。
- 真正缺的是 CMU_AUD 的整组门控（base `0x114c0000`，**写 1=enable**，与 mainline CCF 一致）：
  - `0x114c0800`(ACLK)：bit31=`aclk_dmac`、bit30=`aclk_sramc`
  - `0x114c0900`(PCLK)：bit25-28
  - `0x114c0a00`(SCLK)：bit28/29/31
  - `AUD_OPTION(0x105c4008) = 0x0102`
  - 只开 `aclk_dmac`(bit31) 不够，读 ADMA 仍是 0；**全开**后寄存器活了。
- 模块 `lpassup.ko` 写上述位，实测：
  `adma pid=0x00000030 cr0=0x000ef075 crd=0x00731313`（PID 低字节 0x30 正确）。
- 之后 `/sys/bus/amba/drivers_probe` → **`AMBA_ID=00341330`，`dma-pl330` 绑定成功**：
  `PL330 DMAC-341330, DBUFF-8x8bytes Num_Chans-8 Num_Peri-16 Num_Events-8`。
- 继续加载后 **声卡注册成功**：
  `samsung-i2s 11440000.i2s-sec: DMA channels sourced from device 11440000.i2s`；
  `cs47l85-codec` probe；`/proc/asound/cards` → **`0 [zenltewm1840]: simple-card - zenlte-wm1840`**；
  `/dev/snd` → `controlC0 pcmC0D0p pcmC0D0c timer`。

### 8.2 播放测试把整机卡死（未解决，危险）
- 设备无 `aplay`/`amixer`（也没有网络/gcc）。用 `python3`+ctypes 调 `libasound.so.2` 开 `hw:0,0`：
  `snd_pcm_open=0`、`snd_pcm_set_params=0`，codec DAPM 寄存器写入正常；
  但 `snd_pcm_writei` 返回 **-EIO(-5)**。
- 怀疑 mainline `pl330` 缺 Exynos7420 workaround：厂商 `pl330_fixup_ctrl()` 会
  `writel(0, ioremap(0x10ef0000))`（实测该寄存器原本 = `0x3`）。
  用 `pl330fix.ko` 清零后重试播放 → **整机卡死（需硬重启）**。**`/root/playtone.py` 现在别跑！**
- 待办（先改代码、后上机，别再盲试）：
  1. **移植厂商 pl330 补丁**到 mainline `drivers/dma/pl330.c`：
     `pl330_fixup_ctrl()`（`0x10ef0000=0`，probe 与 resume 都调）＋ `#dma-mcode-addr` 支持
     （mcode 放 LPASS SRAM `0x03047000`；mainline 现在用 `dma_alloc_coherent`，
     7420 的可达性/epilogue 可能不兼容 → 很可能就是卡死根因）。
     厂商参考：`build/kernel/drivers/dma/pl330.c:3357-3383`、`:2308-2321`、`:1645-1655`。
  2. I2S `CON_RSTCLR`（`samsung,supports-rstclr`）＋ MCLK（clkout/PMU_DEBUG）后再试 DMA。
  3. 播放用带超时的 `aplay` 或自建静态工具，禁 Python 无限 recover 循环。
- 危险模块：`/root/playtone.py`（会卡死）、`admard4.ko`（SError oops）、`admaread.ko`（会卡死）。

### 8.3 设备上新增实验模块
`lpassup.ko`（★开 AUD 全门控，ADMA 复活）、`pl330fix.ko`（`0x10ef0000=0`，会诱发卡死，慎用）、
`audclk3.ko`（CCF 开 aclk_dmac）、`admard3.ko`（只读 ADMA，安全）、`audpower.ko`、`audpad.ko`。

### 8.4 续测：补齐 I2S 时钟 + MCLK 后，DMA 仍卡死（2026-09-13 续二）
- I2S 块此前**读寄存器会 SError**（`i2srd.ko` 读 `0x11440000` → synchronous external abort），
  因为 `pclk_i2s`/`sclk_i2s` 未使能（`clk_summary` 显示 N）。
- 用模块 `i2sclk.ko` 对 i2s 节点做 `of_clk_get(np,0/1/2)+clk_prepare_enable` 后：
  `pclk_i2s`=Y、`sclk_i2s`=Y；再读 I2S 正常：
  `I2SCON=0x80000878 I2SMOD=0x00400000 I2SPSR=0 I2SFIC=0x00008000 I2SCLC=0`。
- MCLK：模块 `mclk.ko` 写 `PMU_DEBUG`（PMU 偏移 `0xa00`）= `0x1000`（= 厂商 `exynos5_audio_set_mclk`
  的开 CLKOUT 动作）→ 24M 的 CLKOUT 打开，供给 codec MCLK。
- 在此状态下重试播放（**这次没有清 `0x10ef0000`**）：`snd_pcm_open`/`set_params` 都是 0，
  但随后 **`python3` 卡在内核 DMA 调用，RCU stall（CPU4 running task python3），整机无响应**，需硬重启。
- 结论：EIO/卡死与 I2S 时钟、MCLK 无关；**ADMA 在 7420 上的传输本身会锁死总线**。
  运行时手段到此为止，必须改内核 `pl330` 后再测。
- 下一步（代码）：在 mainline `drivers/dma/pl330.c` 按厂商实现：
  1. `pl330_fixup_ctrl()`：`writel(0, ioremap(0x10ef0000, 32))`，probe 与 resume 调用；
  2. 评估 `#dma-mcode-addr` + `arm_exynos_dma_mcode_ops`（厂商把 mcode 固定到 LPASS SRAM
     `0x03047000`）；mainline 用 `dma_alloc_attrs(..., DMA_ATTR_PRIVILEGED)`，7420 可达性可能不兼容；
  3. 先加 `pl330_fixup_ctrl` + 给 ADMA 节点补 `#dma-mcode-addr`，再测。
- `0x10ef0000` 作用未明（疑似 DMA/安全/总线配置），清 0 会让传输真正开始从而暴露下游问题。
- **在 pl330 改好前不要再跑 `/root/playtone.py`（必卡死）。**

---

## 9. Gemini 分析（2026-09-13 续三）与纠正

### 9.1 -EIO 的机理（可信）
`snd_pcm_writei` 返回 -EIO 的**唯一**路径是 `sound/core/pcm_native.c` 里“playback drain timeout
(DMA or IRQ trouble?)”，即 DMA 启动了但**没有中断**在超时前推进 period。
→ 关键怀疑仍是 **LPASS TOP 中断没解掩码**（见 9.3）。

### 9.2 ★ 纠正：不要碰 `0x10ef0000`
厂商 `pl330_fixup_ctrl()` 里对 7420 的 `writel(0, 0x10ef0000)` 与**音频 ADMA（0x11420000）无关**。
`0x10ef0000` 属 **FSYS0 域（PDMA0 0x10E10000 / PDMA1 0x10EB0000 / UFS 控制器）**，
实测读 `0x3`（bit[1:0]=1 允许 Non-Secure 访问）。**写 0 会把 FSYS0 锁成 Secure-only，
rootfs 在 UFS 上 → 立即 AXI DECERR / synchronous external abort 死机**。
→ **绝不要写 0x10ef0000。** §8.2/§8.4 里“移植 pl330_fixup_ctrl”的建议作废。

### 9.3 ★ 关键：LPASS→CPU 中断掩码 `0x11400058`
- `LPASS_INTR_CPU_MASK = 0x58`。厂商 `lpass.c:1115` 初始化写
  `INTR_CPU_MASK_VAL = DMA(0x40)|I2S(0x10)|PCM(0x8)|SB(0x4)|UART(0x2)|SFR(0x1) = 0x5F`。
- 且 `lpass_set_dma_intr(true)` 是**置位=使能**（不是屏蔽）。复位默认 0 → 全部关闭。
- ADMA 的 IRQ（GIC SPI 97）要穿过 LPASS TOP 才能到 GIC；掩码关着时 PL330 搬完也不中断
  → ALSA 等不到 period → -EIO（甚至更糟的锁死）。

### 9.4 ★ 纠正：mcode 不必须放 LPASS SRAM
mainline 用 `dma_alloc_attrs(..., DMA_ATTR_PRIVILEGED)` 从 DRAM 分配 mcode 是可行的
（DRAM 不掉电时 PL330 AXI 能读）。厂商放 SRAM `0x03047000` 只是为熄屏 DRAM 自刷新省电。
可读 `0x11420034`(FSRC) 与 `0x11420100`(CSR0：0x2=执行,0x0=停止) 验证 PL330 是否在跑。

### 9.5 本机教训（别再卡）
- 上次把“解 LPASS 中断掩码 + 复位 toggle + i2sclk + mclk”打成一个模块一次性加载，
  **整机卡死**。嫌疑：① 写 `0x08`(CORE_SW_RESET) toggle 时 I2S/ADMA 驱动已激活；
  ② 使能 `0x58` 前未清 `0x54`(INTR_CPU_STATUS) → 可能中断风暴。
- **更稳的做法（下次）**：
  1. 先只读 `0x54/0x58` 确认状态；
  2. **不要**再动 `0x08` 复位（现状已 normal=0xF1F）；
  3. 先写 `0x54` 清状态（若为写 1 清零），再仅置 `0x58 |= 0x5F`；
  4. 立刻看 `dmesg` 有没有中断风暴，再决定是否播放；playtone 用 `timeout 5 ...` 包住。
- 已确认可用（无风险）：`lpassup.ko`(AUD 门控)、`i2sclk.ko`(I2S 时钟)、`mclk.ko`(CLKOUT)、
  `admard3.ko`(只读 ADMA)、`i2srd2.ko`(读 I2S)。**危险**：`lpassint.ko`(需改)、`playtone.py`、
  `pl330fix.ko`/`admaread.ko`/`admard4.ko`。

### 9.6 Step 顺序（Gemini 建议，采纳）
1. 解 LPASS 中断掩码（0x58，先清 0x54）→ 目标消灭 -EIO，跑通 DMA 周期（不需 codec/MCLK）。
2. 挂 AUD pinctrl（`gpz0` @ `0x114B0000`，mainline `pinctrl-exynos-arm64.c` 已有 bank，只差 DT 节点）。
3. 开 CLKOUT（PMU_DEBUG=0x1000）给 WM1840 MCLK1（已用 `mclk.ko` 验证可写）。
4. ALSA DAPM 混音开关 → 出声。

---

## 10. 续三结果（2026-09-13）：不再硬卡，但 DMA 仍未动

### 10.1 lpassint2（解 LPASS 中断掩码）安全
- 模块 `lpassint2.ko` 只做 `0x11400058 |= 0x5F`（DMA|I2S|PCM|SB|UART|SFR），不碰复位/状态。
- 实测：`before 54=0 58=0 48=0 44=0` → `after 58=0000005f`，**未卡死**。
  （之后模块读 ADMA `0x34` 触发 SError，是因为 pl330 空闲时把 `aclk_dmac` 关了，属正常现象，
   不是系统故障；读 ADMA 前要先确保时钟开。）
- 结论：`lpassint2` 可安全使用；之前卡死是 `lpassint` 里 **CORE_SW_RESET(0x08) toggle** 导致。

### 10.2 受控播放（timeout 10s）
- `timeout 10 python3 playtone.py 440 2` → **不再硬卡死**：
  `snd_pcm_open=0`、`set_params=0` → 第 1 次 `writei` 返回 **22050 帧** → 之后连续 `-EIO(-5)` → giving up。
- `22050 帧 = 0.5s` 恰好是 ALSA 环形缓冲的一次性容量：**首次 writei 只是填满缓冲区、没经过 DMA**；
  之后等 DMA 腾空间超时 → EIO。即 **DMA 一帧都没搬**。
- **ADMA 的 IRQ（GIC hwirq 129 = SPI 97 → virq 62）计数始终为 0**，即便 `0x58=0x5F` 已置位。
- 期间 `dmesg` 无任何 `pl330`/`dma`/`i2s` 报错。

### 10.3 已排除 / 待查
- 已排除：电源域（常 on）、AUD 门控（`lpassup`）、I2S 时钟（`i2sclk` 后 `pclk_i2s`/`sclk_i2s`=Y）、
  codec MCLK（`mclk` 置 `PMU_DEBUG=0x1000`）、LPASS 中断掩码（`0x58=0x5F`）。
- I2S `MOD[31:30]=0`（=CDCLK_OUT）→ **I2S 是 Master**，理论上 DMA 推进不需要 codec。
- 剩余嫌疑（按可能性）：
  1. **PL330 通道没真正跑**：peripheral DRQ（I2S TX）没来，或 `dmaengine` 描述符没提交/微码没执行。
     需在传输进行中读 `0x11420100`(CSR0：0x2=执行/0x0=停止) 与 `0x11420034`(FSRC) 判定。
  2. mainline `pl330` 与 7420 的兼容性（mcode / `DMA_ATTR_PRIVILEGED` / 中断触发方式）。
  3. I2S 的 DMA request 路由（`dmas=<&adma 0>,<&adma 2>` 的 request 号是否正确）。
  4. AUD SMMU（`sysmmu@114E0000`，mainline 无该节点/未配置）。
- 建议下一步（低风险）：写一个模块，**先 `clk_prepare_enable(adma clk)` 再读** `CSR0/FSRC/DSR`，
  并在后台 `timeout 30 python3 playtone... &` 运行期间多次读取，看通道是否 Executing、FSRC 是否报 fault。
- 仍禁止：`playtone.py` 无 `timeout` 直接跑（会卡）；`lpassint.ko`（含 0x08 复位，会卡）。

### 10.4 追加：后台播放 + 采样 PL330 状态 → 仍整机卡死
- 尝试：`(timeout 30 python3 playtone.py ... &)` 后台播放，2s 后加载 `admastat.ko`（先开 ADMA 时钟，
  再采样 `DSR/INTEN/INTMIS/FSRC/FTR/CSR0/CPC0`）→ **整机卡死**（Ctrl-C 无效，`timeout` 也救不回）。
- 说明：ADMA 一旦进入坏状态会**硬锁总线/CPU**，不是可中断的等待。
- 因此**在 pl330/ADMA 侧问题定位并修复前，任何触发 DMA 传输的播放测试都会卡死整机**。
- 若要再查 PL330 状态，必须**不触发传输**：
  1) 只 `clk_prepare_enable` ADMA 时钟后读空闲寄存器（`admastat.ko` 的空闲读是安全的）；
  2) 或改用 devmem/调试器在**开机早期**读；
  3) 不要在设备上跑任何 `aplay`/`playtone` 触发真实 DMA，直到代码层修复。
- 下一步优先级：先解决“ADMA 传输即锁死”，再谈出声。可请 Gemini 依据本文件 9/10 节继续。

---

## 11. 续四：DMA 通路打通，PL330 卡在等 I2S 的 DRQ（2026-09-13）

### 11.1 已解决：ADMA 不再硬锁，且能在 LPASS SRAM 执行微码
- `audbus.ko` 确认并修复了真正的总线阻断：
  - **AUD SysMMU `0x114E0000` 之前是启用的**（`CTRL=0x00000003`），已写 0 旁路
    （`CTRL=CFG=STATUS=0`）。这是之前 ADMA 一 DMA 就硬锁的最可能根因。
  - AUD 异步桥 `aclk_acel_lh_async_si_top`（CMU_AUD `0x114c0800` bit28）与
    `aclk_smmu_aud`（bit27）之前为 0，已置 1（ACLK `0x7fffffff→0xffffffff`）。
  - LPASS SRAM `0x03047000` CPU 读写 **PASS**。
- 给 mainline `pl330.c` 打了补丁（**已编译**）：`of_machine_is_compatible("samsung,exynos7420")`
  时把 mcode 用 `ioremap_cache(0x03047000, chans*mcbufsz)` 映射（Normal-NC），
  `mcode_bus=0x03047000`，跳过 `dma_alloc_attrs`。日志：
  `dma-pl330 ... exynos7420: mcode in LPASS SRAM @0x03047000 (4096 bytes)`。
- 注意：最初用 `ioremap()`（Device 内存）会在 mcode 生成时**对齐 fault Oops**；必须用
  `ioremap_cache()`（Normal-NC）。
- 结果：**播放不再硬锁整机**；PL330 真的在跑微码。

### 11.2 当前卡点：PL330 通道停在 `WFP`（等外设 DMA 请求）
后台播放 + `admastat.ko` 采样（无卡死）：
```
admastat: PID=00000030
CSR0=0x00200007 -> &0xf = 7 = DS_ST_WFP (Wait For Peripheral)
CPC0=0x0304701a / 0x0304702f  (在 LPASS SRAM mcode 区间内，说明在取指执行)
FSRC=0 FTR=0 ; DSR=0x00000200 ; INTEN=1 INTMIS=1 ; IRQ 62(SPI97) 计数=0
```
→ **DMA 引擎/微码都 OK，PL330 在等 I2S 的 TX DMA 请求（DRQ），但 I2S 不产生。**

### 11.3 I2S 侧现状：配置看似正确，但没有有效 BCLK
`i2sstat.ko` 采样（播放期间）：
```
I2SCON=0x80000005 (bit0 CON_ACTIVE=1, bit2 CON_TXDMA_ACTIVE=1)
I2SMOD=0x00400000 (i2sv7: mss_off=12 -> bit12=0 表示 Master; cdclkcon_off=22 -> bit22=1 CDCLK 开)
I2SAHB=0x00000000
I2SPSR=0xffffff00  I2SFIC=0x0000003f
```
`clk_summary`（播放后）：
```
sclk_i2s = 10130402 Hz   (10.13MHz)  <-- 偏低
11440000.i2s_prescaler = 158288 Hz
11440000.i2s_cdclk     = 0 / N (disabled!)   <-- 关键
dout_sclk_i2s = 10130402 ; fout_aud_pll = 202608032
```
- I2S 是 Master、CDCLK 输出位已置，但 `i2s_cdclk` 没使能、prescaler 只有 158kHz：
  `config_setup()` 里 `psr = rclk_srcrate / frmclk / rfs = 10.13M/44100/256 ≈ 0` →
  PSR 无效 → 无正确 BCLK → FIFO 不移位 → 无 DRQ。
- 根因：**mainline 没做厂商 `lpass_set_clk_heirachy()`**：
  `fout_aud_pll=351MHz`、`dout_sclk_i2s=117MHz`、`mout_sclk_i2s` 父→`dout_aud_cdclk`、
  `dout_aclk_ca5/aud` 等；并 `clk_prepare_enable(fout_aud_pll)`。
  厂商参考 `build/kernel/sound/soc/samsung/lpass-exynos7420.c:82-235`（`lpass_set_clk_heirachy`）。

### 11.4 下一步（最后一块拼图）
1. 复刻 `lpass_set_clk_heirachy()` 的频率/父时钟设置（可用模块 + CCF，或裸写 CMU_AUD
   的 MUX_SEL_AUD/DIV_AUD0/DIV_AUD1 与 fout_aud_pll 配置），把 `sclk_i2s` 提到足够高
   （≥ 采样率×256，如 117MHz），并确保 `i2s_cdclk`/`i2s_prescaler` 正确。
2. 之后 PL330 应从 `WFP` 进入搬运、IRQ 62 开始计数；再解决 codec 出声道（DAPM 路由/耳机）。
3. 播放测试继续加 `timeout`；`audbus.ko` 必须先加载（SMMU 旁路），`pl330_sram2.ko` 已内置此补丁。

### 11.5 本轮新增/更新产物
- `pl330.ko`（含 7420 mcode-SRAM 补丁，设备上为 `/root/pl330_sram2.ko`）——源码已改在
  `build/linux-6.6/drivers/dma/pl330.c`。
- 模块：`audbus.ko`（SMMU 旁路+总线时钟，★必须先加载）、`admastat.ko`（读 PL330 状态）、
  `i2sstat.ko`（读 I2S 状态）、`i2srd2.ko`、`i2sclk.ko`、`mclk.ko`、`lpassup.ko`。
  危险：`lpassint.ko`（含 0x08 复位，会卡）、`playtone.py` 无 `timeout` 直接跑会卡。

---

## 12. 续五：I2S 时钟已拉高，但仍无 DRQ；发现 DTB 变体/时钟映射与厂商不一致

### 12.1 用 CCF 复刻时钟层级（比裸写更干净）
- 不要裸写 CMU_AUD：mainline CCF 有频率缓存，裸写不会更新 `clk_get_rate()`，
  I2S 驱动读到旧频率，PSR 依旧无效。
- 正确做法：`sclk_i2s`（cmu_aud id1，`GATE(..., CLK_SET_RATE_PARENT)`）用 CCF `clk_set_rate()`
  会向上设置 `dout_sclk_i2s` 分频 → `mout_sclk_i2s` 选源，并**更新 CCF 缓存**。
  模块 `audclkhi.ko`：`of_clk_get(i2s_np, 1)` 得 `sclk_i2s`，`clk_set_rate(clk,117000000)`。
  实测 `dout_sclk_i2s` 由 /10 变 /1：**`sclk_i2s = 101,304,016 Hz`**（受父 `dout_aud_cdclk` 限制，
  达不到 117M，但已足够）。`i2s_prescaler = 12,663,002`（psr=8），`i2s_rclk_src=101,304,016`。
- 此后 I2SPSR 由 `0xffffff00`（非法）变为 **`0x00008700`（psr=8，合法）**。
  → **I2S 时钟/PSR 问题已解决**。

### 12.2 但仍无 DRQ：PL330 依旧 `WFP`，IRQ 62=0
- 即使 sclk=101MHz、PSR 合法、`CON_ACTIVE/TXDMA_ACTIVE` 置位，I2S 仍不发 TX DMA 请求。
- 生产 `sclk` 的前置：`audclkhi.ko` 必须在 **加载 `snd-soc-i2s.ko` 之前**运行（更新 CCF 缓存）。

### 12.3 ★ 新发现：DTB 的 I2S 变体与时钟映射与厂商不一致
厂商 `build/kernel/arch/arm64/boot/dts/exynos7420.dtsi:3151` 的 i2s0：
```
compatible = "samsung,i2s-v5";        <-- 厂商用 i2s-v5，不是 exynos7-i2s
dmas = <&adma 0 &adma 2>;             (tx=adma req 0, rx=2)
clocks = <&clock 414>,   /* pclk_i2s   */
         <&clock 451>,   /* dout_aclk_aud */   <-- i2s_opclk0
         <&clock 433>;   /* sclk_i2s   */      <-- i2s_opclk1
clock-names = "iis", "i2s_opclk0", "i2s_opclk1";
pinctrl-0 = <&i2s0_bus>;
```
而**我们设备上运行的 DTB**是前一阶段改过的：`compatible="samsung,exynos7-i2s"`，
且只引用两个 cmu_aud 时钟（mainline id3=pclk_i2s、id1=sclk_i2s），`opclk0→sclk_i2s`。
→ **变体（v5 vs exynos7=i2sv7）与 `i2s_opclk0/1` 的时钟映射都和厂商不一致**。
这会导致寄存器位域（mss_off/cdclkcon_off/bfs/rfs）解释错误、内部 RCLK 源选错 → 无 BCLK → 无 DRQ。

### 12.4 下一步建议
1. **修正 I2S DT 节点**使其与厂商一致：
   - `compatible = "samsung,i2s-v5"`（mainline `sound/soc/samsung/i2s.c` 支持，
     `i2sv5_dai_type`/对应 variant regs、`QUIRK_SEC_DAI|QUIRK_NEED_RSTCLR|QUIRK_SUPPORTS_IDMA`）；
   - `clocks` 三路：pclk_i2s、dout_aclk_aud、sclk_i2s；`clock-names` 对应；
   - `pinctrl-0 = <&i2s0_bus>`（AUD pinctrl @0x114B0000，mainline 缺该节点，需补）；
   - 确认 `dmas=<&adma 0 &adma 2>` 的请求号与 7420 实际 DMA 请求线一致。
2. 这需要**重新生成/打包 DTB**（前一阶段是改厂商 DTB，建议用 repo DTS 正确构建或精确 patch）。
3. 仍先只读书寄存器验证；避免无 timeout 播放。

### 12.5 已可安全复用的模块（本轮）
`audbus.ko`（SMMU 旁路+总线时钟）、`audclkhi.ko`（CCF 抬 sclk_i2s）、`pl330_sram2.ko`（mcode 进 SRAM）、
`lpassup.ko`、`i2sclk.ko`、`mclk.ko`、`admastat.ko`、`i2sstat.ko`。
顺序：`audbus` → `audclkhi` → spi/snd/codec → `pl330_sram2` → `lpassup` → `drivers_probe` →
i2s/simple-card → `i2sclk`/`mclk`。

### 12.6 追加负结果：清 `I2SMOD` bit22（开 cdclk）无效
- `cdclken.ko` 把 `I2SMOD` bit22 清 0（= 打开 CDCLK 引脚输出，`cdclkcon_off=22`）。
- 重播仍 `-EIO`、IRQ 62=0、PL330 仍 `WFP`。→ 与 `i2s_cdclk` 无关，排除。
- 至此已排除：电源域、AUD 门控、SysMMU、异步桥、I2S 时钟/PSR、cdclk。
- 剩余最可能：**I2S 的 TX DMA 请求（DRQ）没有到达 PL330**——嫌疑 DT 的
  I2S 变体/时钟映射（§12.3）或 `dmas=<&adma 0 ...>` 的请求号/事件映射与 7420 实际不符。
  需要改 DT/重打包 DTB 或核对 PL330 `of_dma_pl330_xlate` 的 `peri_id` 语义。

---

## 13. 续六：I2S variant 改为 v5(=`i2sv3_regs`) 后仍无 DRQ

### 13.1 做了什么
- mainline `i2s.c` 的 `samsung,exynos7-i2s` 原本映射 `i2sv7_dai_type`（`i2sv7_regs`：
  mss_off=12, cdclkcon_off=22, bfs_off=0）。把它的 `.data` 临时改为 `&i2sv5_dai_type`
  （= `i2sv3_regs`：mss_off=11, cdclkcon_off=12, bfs_off=1, lrp_off=7），重编
  `snd-soc-i2s.ko`（设备上 `/root/snd-soc-i2s_v5.ko`）。依据：厂商 7420 i2s0 用
  `compatible="samsung,i2s-v5"`，mainline 的 `i2sv5_dai_type` 即用 `i2sv3_regs`。
- 重启后按序加载（audbus→audclkhi→…→用 `snd-soc-i2s_v5.ko` 替换原 i2s 模块）。

### 13.2 结果：仍 EIO、IRQ 62=0、PL330 `WFP`
播放期间 I2S 采样（v5 regs 解释）：
```
I2SCON=0x80000005 (ACTIVE + TXDMA_ACTIVE)
I2SMOD=0x00001000 (bit12=cdclk 关; bit11=0 -> Master)   <-- 配置合理
I2SAHB=0x00000000
I2SPSR=0x00008700 (psr=8, 合法)
```
→ **变体不是根因**：两种 variant 下 I2S 都显示 Master + PSR 合法，但 PL330 依旧收不到 DRQ。

### 13.3 结论与下一步
- 现在唯一未解释的是：**I2S 的 TX DMA 请求没有到达 PL330**（硬件信号/事件映射层）。
- 已知 DT `i2s dmas=<&adma 0>,<&adma 2>`、`adma #dma-cells=1`，与厂商一致；
  mainline `of_dma_pl330_xlate` 把 arg 当 `peri_id`（TX=0）。
- 建议下一步（代码级，先不改 DTB）：
  1. 在 mainline `pl330.c` 的 `pl330_prep_slave_sg` / `_setup_req` 临时打印
     `pch->peri_id`、`slave_config->dst_addr/direction`、生成的 mcode 长度；
  2. 或临时把 TX `peri_id` 加偏移（试 1/8/其它）看 DRQ 是否出现，定位 7420 的 I2S0-TX
     事件号线；
  3. 对照厂商 `build/kernel/drivers/dma/pl330.c` 的 `of_dma_pl330_xlate`/`#dma-cells` 与
     `dma-requests` 语义，确认事件号。
- 其它已排除项见 §12/§13。

### 13.4 备注
- 改 variant 的实验性改动位于 `build/linux-6.6/sound/soc/samsung/i2s.c`
  （`exynos7-i2s` → `i2sv5_dai_type`），若要恢复原样记得改回。

---

## 14. 续七：Gemini 关键线索 —— TX FIFO 满、serializer 不排空

### 14.1 结论（与实测吻合）
- ADMA @0x11420000 外设请求线映射确认：**0=I2S0-TX, 1=I2S0-TX-SEC, 2=I2S0-RX**，与 DT `dmas=<&adma 0 &adma 2>` 一致；
  mainline `of_dma_pl330_xlate`(2182) 取 args 作 chan，`pl330_get_desc`(2648) `desc->peri=chan_id`，
  `_emit_WFP(..., desc->peri)` → 微码 `DMAWFP B,0`。**线号没有配错。**
- `i2s_set_fmt`(631) 确认：`DAIFMT_BC_FC` 才置 slave；我们 MOD slave 位=0 → **I2S 是 Master**。
- 硬证据：播放时 **`I2SFIC=0x0000003f`（TX FIFO 满）**。说明：
  **DRQ 曾经生效、DMA 已把 FIFO 填满，但 FIFO 不再被排空** → serializer 的 BCLK/LRCLK 没真正跑
  → FIFO 恒满 → I2S 不再拉 DRQ → PL330 卡 `DMAWFP B,0`（`DS_ST_WFP`）。
  （这解释了为何 `sclk/PSR` 修好后仍无进展：PSR 合法 ≠ serializer 时钟在走。）

### 14.2 为什么 serializer 不跑（待验证）
- `I2SMOD` 的 `OPCLK` 位[31:30]=0 = **CDCLK_OUT**；而 `11440000.i2s_cdclk` 在 clk_summary 是 **N（disabled）**。
  Gemini 认为 cdclk 只驱动外部引脚、内部 BCLK 不依赖它；但实测"清 `I2SMOD` cdclk 位"（v7 的 bit22）无效，
  说明该假设存疑 —— **需确认 7420 I2S 内部 serializer 的时钟到底取自哪条路径**。
- 可能方向：
  1. `MOD_OPCLK` 选错源（应为 PCLK 或 BCLK_OUT 之类），导致内部无 RCLK；
  2. `i2s_cdclk`/`i2s_rclk_src` 的 gate 实际没给到 serializer；
  3. 需要 `I2SCON.CON_RSTCLR` 或 `I2SFIC.TXFLUSH` 的特定时序才能真正启动 FIFO 排空。

### 14.3 建议的验证实验（低成本、可逆）
1. 在驱动启动后**手动 flush TX FIFO**：写 `I2SFIC(0x11440008) |= (1<<15)` 再清 0，
   看 `I2SFIC` 低 6 位是否归 0、DRQ 是否恢复（若 serializer 仍不跑会立刻又满）。
2. 试改 `I2SMOD` 的 `OPCLK`（bits[31:30]）为 `MOD_OPCLK_PCLK`(3) 或 `BCLK_OUT`(2)，
   看 FIFO 是否开始排空、IRQ 62 是否计数。
3. 若仍不行：需从 7420 TRM 确认 I2S serializer 时钟树（CLKOUT/CDCLK/OPCLK 关系）与
   `i2s_cdclk` gate 的作用；再看主线上 Exynos5433/7 的 I2S 是否有已知必需配置。

### 14.4 现状总结（给下一个 AI）
- 已解决：ADMA 总线、SRAM mcode、I2S sclk/PSR、声卡注册、codec probe。
- 卡点精确定位到：**I2S serializer 时钟不跑 → TX FIFO 恒满 → 不发 DRQ**。
- 代码改动：`pl330.c`（mcode SRAM 补丁）、`i2s.c`（临时把 exynos7-i2s 指到 i2sv5_dai_type，实验性）。
- 设备模块见 §12.5；先 `audbus`→`audclkhi` 再加载其余。

---

## 15. 续八：按厂商设置 OPCLK=PCLK + CDCLK=IN 后，FIFO 仍不自动排空

### 15.1 已实施
- 依据厂商 `noble_arizona.c:1001-1019`（`aif_format[0]=I2S|NB_NF|CBM_CFM` = CPU/I2S master；
  `set_sysclk(cpu_dai, SAMSUNG_I2S_CDCLK, 0, SND_SOC_CLOCK_IN)`；
  `set_sysclk(cpu_dai, SAMSUNG_I2S_OPCLK, 0, MOD_OPCLK_PCLK)`）。
- 在 mainline `i2s.c: i2s_trigger()` START 分支加：
  `SAMSUNG_I2S_CDCLK`(IN) + `SAMSUNG_I2S_OPCLK` = `MOD_OPCLK_PCLK >> MOD_OPCLK_SHIFT`。
  **注意 mainline 坑**：`i2s_set_sysclk()` 的 OPCLK 分支会 `(dir << MOD_OPCLK_SHIFT)`，
  所以必须传**原始值 3**，传 `MOD_OPCLK_PCLK`(0xC0000000) 会左移溢出成 0。
- 重编 `snd-soc-i2s.ko`（设备上 `/root/snd-soc-i2s_v5q.ko`）。实测 `I2SMOD=0xC0001000`
  （bits[31:30]=3，OPCLK=PCLK 生效；bit12=cdclk 相关）。

### 15.2 结果：仍 `-EIO`、IRQ 62=0
- 播放时 `I2SCON=0x80000005`、`I2SMOD=0xC0001000`、`I2SPSR=0x00008700`(psr=8)、
  `I2SFIC=0x3f`(TX FIFO 满)。

### 15.3 `fifoflush.ko` 关键实验（验证 serializer 不排空）
- 在播放期间循环 flush TX FIFO（写 `I2SFIC(0x11440008)` bit15 置位再清）：
  `FIC` 由 **0x3f → 0x00/0x01**（能被清空），但很快又会被填满。
- 结论：**FIFO 硬件可清空、DMA 至少能填一次（DRQ 曾生效），但 serializer 的移位时钟没自动排空 FIFO**。
  → 再次确认卡点是 **I2S serializer/BCLK 时钟没真正运行**，不是 DMA 线号、不是 ALSA、不是输出路由。
- 与"耳机孔/输出路由"无关：数据从未送达 codec。

### 15.4 下一步（需要 7420 I2S 时钟树的确切信息）
- 确认 Exynos7420 I2S serializer 的时钟来源：`sclk_i2s`→PSR→BCLK/LRCLK 这条路径是否还需要
  `I2SCON.CON_RSTCLR` 之外的使能，或 `i2s_cdclk`/`i2s_rclk_src` gate、`MOD_OPCLK` 的正确取值
  与 `RCLKSRC_0/1` 选择。
- 建议：拿 §12~§15 给 Gemini，重点问“Exynos7420 I2S 在 mainline 下 serializer/BCLK 不运行的
  确切原因”，或查 7420 TRM 的 I2S 时钟图、对比 Exynos5433/7 已上游的 I2S 配置。
- 仍不要无 `timeout` 播放（可能卡）。

### 15.5 本轮新增设备模块
`fifoflush.ko`（flush TX FIFO 验证）、`snd-soc-i2s_v5.ko`（v5 regs）、`snd-soc-i2s_v5p/v5q.ko`
（v5 + OPCLK 修正）。源码改动：`sound/soc/samsung/i2s.c`（variant + trigger sysclk）。

---

## 16. 续九：Gemini 的 TXR=2 / OPCLK 方案实测无效

### 16.1 已验证的负结果
- 播放期间用模块强制 `I2SMOD` 的 TXR 位（同时置 bit9/bit10 覆盖两种 variant 解释）+
  `I2SPSR=0x00008700`：`MOD=c0001600`，但 `I2SFIC` 始终 `0x3f`、仍无 DRQ、IRQ 62=0、`-EIO`。
- 加载 `lpassint2.ko`（`LPASS_INTR_CPU_MASK(0x11400058) |= 0x5F`）后再播：仍 `-EIO`、IRQ 62=0。
  → ADMA 中断掩码不是原因。
- 说明：`I2SFIC=0x3f` 到底是不是“满”存疑；但手动 `TXFLUSH` 能清到 0，说明 FIFO 可清空。
  真正的现象是 **serializer 不把 FIFO 排空**，即便 TXR/OPCLK/PSR/门控都设了。

### 16.2 Gemini 方案与实测差异
- Gemini 依据 `i2sv7`（mss_off=12, cdclkcon=22, txr_off=9）分析，但我们当前模块用的是
  `i2sv5_dai_type`(=`i2sv3_regs`: mss_off=11, cdclkcon=12, txr_off=8)。
  7420 到底对应 i2sv7 还是 i2sv3/v5 仍未定论（厂商 compatible 是 `samsung,i2s-v5`）。
- Gemini 认为 `0xC0001000` 的 bit12=1 是 Slave；但在 `i2sv3_regs` 下 bit12 是 cdclkcon，
  slave 是 bit11(=0)。→ 其“双从机”结论在当前 variant 下不成立。
- Gemini 的 `MOD_TXR 必须=2` 我们已试（bit9/10），无效。

### 16.3 结论：需要硬件级对照
- 软件可见的寄存器配置看起来都合理（Master、PSR 合法、门控开、TXR 置位、OPCLK 试过 PCLK/CDCLK_OUT），
  但 serializer/BCLK 就是不动手。**强烈需要一份“能出声”的参考寄存器 dump**。
- 建议下一步（二选一）：
  1. 让设备进厂商 Android/内核，在**正在播放**时 dump `0x11440000..0x11440050` 与
     CMU_AUD `0x114c0000..0x114c0a0c`，与我们的对比，找出差异位。
  2. 找 7420 TRM 或已上游的 Exynos7420 I2S 配置（postmarketOS/社区）核对。
- 现有寄存器对照需求：`I2SCON/I2SMOD/I2SPSR/I2SFIC/I2SAHB` + `MUX_SEL_AUD/DIV_AUD0/DIV_AUD1/
  ENABLE_ACLK/PCLK/SCLK_AUD` + `i2s_cdclk` gate。
- 注意：读 ADMA 寄存器前必须先确保 ADMA 时钟开（pl330 空闲时会关），否则 SError（`lpassint2` 即如此）。

---

## 17. 续十：variant 定为 i2sv7 + TXR=2 仍无 DRQ（驱动序列已与厂商一致）

### 17.1 决定性证据（厂商源码）
- 厂商 i2s0 DTS 有 `samsung,supports-tdm;` + `samsung,supports-low-rfs;`
  → `i2s_init_bit_slice()` 走 `EXYNOS5430_MOD_*`（cdclkcon=22, slave=12, txr_shift=9）
  → **7420 = mainline `i2sv7_regs`**。所以原 `samsung,exynos7-i2s`(i2sv7) 才是对的；
  之前改 `i2sv5` 是错的，**已改回 i2sv7**。
- 厂商 `i2s-regs.h:100-108` 在 `CONFIG_SOC_EXYNOS7420` 下：
  `MOD_TXR_TXONLY=2, MOD_TXR_RXONLY=2, MOD_TXR_TXRX=2` → **7420 的 TXR 恒为 2**；
  mainline 播放时写 `0<<txr`（TX-only）是**错的**，导致 TX 状态机不启动。
  **已把 mainline `i2s_txctrl` 的 TX-only 分支改成 `2 << txr_off`**。
- 厂商 TX FIFO 计数 = `(I2SFIC >> 8) & 0x7F`（`i2s.c:1242`）。`I2SFIC=0x3f → 计数=0`，
  即 **TX FIFO 是空的，不是满的**（Gemini 之前把 bit0-5 当计数，看错了）。

### 17.2 实测（i2sv7 + TXR=2，驱动序列已与厂商 `i2s_txctrl` 一致）
```
I2SCON = 0x80000005   (CON_ACTIVE + CON_TXDMA_ACTIVE)
I2SMOD = 0x00400400   (bit22=cdclk 关; bit10=TXR=2)
I2SPSR = 0x00008700   (psr=8)
I2SFIC = 0x00000000   (TX FIFO = 0，空)
```
→ 仍 `snd_pcm_writei=-EIO`、ADMA IRQ 62=0、PL330 `DS_ST_WFP`。**I2S 就是不发 DRQ。**

### 17.3 结论：寄存器序列已对齐，差异只剩“环境”
驱动可见寄存器与厂商一致，仍无 DRQ。与厂商 i2s0 相比，仅剩差异：
1. **时钟映射**：厂商 `i2s_opclk0 = dout_aclk_aud`、`i2s_opclk1 = sclk_i2s`；
   我们的 DTB `opclk0 = sclk_i2s`、opclk1 缺失。
2. **AUD 时钟速率**：厂商 `lpass_set_clk_heirachy` 设 `fout_aud_pll=351M / dout_sclk_i2s=117M`；
   我们只是把 `sclk_i2s` 拉到 101M。
3. **DTB 缺 `pinctrl-0=<&i2s0_bus>`**（PAD 未复用；不影响 DRQ 但影响出声）。
4. 厂商还有 `samsung,tx-iommu/rx-iommu/tx-buf/rx-buf/rx-sram` 等（可能涉及 I2S 侧 DMA 路径）。

### 17.4 下一步（二选一，推荐 1）
1. **抓一份“能出声”的参考 dump**：让设备进厂商内核/Android，在播放时 dump
   `0x11440000..0x11440080` + CMU_AUD + LPASS TOP，与我们的逐位对比。这是最快定位法。
2. 把 DTB 的 i2s `clocks` 改成厂商映射（opclk0=dout_aclk_aud），并按厂商设 AUD PLL 速率
   （`fout_aud_pll=351M`、`dout_sclk_i2s=117M`），再测。

### 17.5 当前源码改动状态（build/linux-6.6）
- `drivers/dma/pl330.c`：7420 mcode 用 `ioremap_cache(0x03047000)`（保留）。
- `sound/soc/samsung/i2s.c`：`exynos7-i2s→i2sv7_dai_type`（原样）；`i2s_txctrl` TX-only 改 `2<<txr`。
- 设备内核仍为原 Image（这些是模块级改动，pl330/i2s 以 .ko 加载）。

---

## 18. 续十一：Android 实机抓取的关键线索（厂商播放走 I2S 自带 DMA，不是外部 ADMA）

来源：`~/.gemini/antigravity/scratch/WORKING-66audio/android_stock_dmesg.txt`（SM-G9280 Android 7.0 实机）。

播放 48k 时的厂商日志（时间 278.0s）：
```
i2s_startup : pri --
noble-audio: playback-eax2-0 2ch, 48000Hz, 15360bytes
noble-audio: noble_change_mclk rate=48000 -> mclk_source=1 -> "change mclk as 24M"
EAX:P:DmaAddr=@5f420000 Total=15360 PrdSz=3840 #Prds=4 area=0xffffff8006a62000
noble-audio: noble_start_sysclk
MAX98505: hw_params ... 48000
arizona spi0.0: DSP5: clearwaterc-dsp5-dsm.wmfw ...   (DSP 固件)
EAXDMA:DmaAddr=@48000000 Total=1920 PrdSz=480 #Prds=4
```
→ 厂商主播放是 **`playback-eax2-0`（EAX/EAXDMA）**，用**固定物理缓冲区**（`0x5f420000`），
配合厂商 DTS 的 `samsung,tx-iommu/tx-buf=<0x40000000>/rx-buf=<0x41000000>/rx-sram`。
即 **I2S0 的音频数据流走 I2S 自带 AHB/EAX DMA（可能经 AUD SMMU），不是外部 ADMA(PL330)**。
（`dmas=<&adma 0 &adma 2>` 仍在 DTS，但主播放实际用 EAX。）

### 18.1 对 mainline 方案的影响
- mainline `samsung-i2s` 用 **外部 ADMA + dmaengine**（`CON_TXDMA_ACTIVE` 触发 DRQ）。
- 厂商 7420 的 I2S 用 **自带 DMA（I2SAHB/EAX）+ IOMMU + 固定 buffer**。
  → 二者的 DMA 请求通路可能根本不同：I2S 在“自带 DMA”模式下可能**不向外部 ADMA 输出 DRQ**，
    或需要额外寄存器（`I2SAHB.AHB_DMAEN` 等）才切到外部请求。
- 这很好地解释了我们的现象：I2S 配置/时钟/PSR 都对，FIFO 空，但外部 ADMA 收不到 DRQ。

### 18.2 其它确认
- MCLK：厂商 48k 播放时开 **24M CLKOUT**（`mclk_source=1`）→ codec FLL3；与我们的 `mclk.ko`(PMU_DEBUG=0x1000) 方向一致。
- 厂商 codec 还加载了 DSP 固件（`clearwaterc-dsp5-dsm.wmfw` 等），mainline 需要时再补。

### 18.3 下一步建议
1. **研究 I2S 自带 DMA（AHB/EAX）路径**：mainline 是否要走 `I2SAHB`（`AHB_DMAEN`）而非外部 ADMA；
   或确认外部 ADMA 的 DRQ 是否在某个寄存器使能后才输出（对比厂商 i2s 自带 DMA 的 init）。
2. 若仍走外部 ADMA：需要有厂商“I2S 使用外部 DMA”模式下的寄存器 dump 对照。
3. 参考厂商 `sound/soc/samsung/i2s.c` 的自带 DMA（`i2s_write_fifo`/`samsung,tx-buf`/IDMA）实现，
   以及 `i2s-regs.h` 中 `I2SAHB` (0x20) 的位定义（`AHB_DMAEN=1`、`AHB_INTENLVL0` 等）。

---

## 19. 续十二：厂商 EAX 其实也用 ADMA（dmaengine），B 路更靠谱

- `build/kernel/sound/soc/samsung/eax-dma.c`（1014 行）是三段式 ASoC 的 **DMA 平台驱动**，
  内部 `dma_request_channel`（日志 `EAXDMA: Failed to request DMA channel`）→ **它请求的就是 ADMA(PL330) 的
  dmaengine 通道**，只是配了固定物理缓冲（`samsung,tx-buf/rx-buf`）和 AUD SMMU。
- 即：**厂商音频数据流最终也是走 ADMA**；`playback-eax2-0` 是 EAX 这层封装，不是换了一种 DMA 控制器。
- 因此 mainline“外部 ADMA + dmaengine”的架构方向是对的；我们卡在 I2S 不向 ADMA 发 DRQ，
  是**某个具体配置差异**（I2S 外部 DMA 请求的使能/线号/时钟），不是 DMA 架构选错。
- 结论：**优先走 B**（抓厂商播放时的 I2S 寄存器 dump 逐位对比），而不是移植 EAX。
  需要 dump 的关键寄存器：
  `I2SCON(0x00) I2SMOD(0x04) I2SFIC(0x08) I2SPSR(0x0c) I2SAHB(0x20) I2SSTR0(0x24) I2SSIZE(0x28)
   I2SLVL0ADDR(0x30..0x3c)` 以及 `CMU_AUD(MUX_SEL_AUD/DIV_AUD0/DIV_AUD1/ENABLE_*_AUD)`、
   LPASS TOP `0x11400008/0x11400058`。
- 若 A 仍要做：EAX 是 1014+566 行下游驱动，移植成本高，且 B 成功即可避免。

---

## 20. 续十三：mainline 播放中的完整寄存器 dump（对照基准）

模块 `i2sdump.ko` 在**播放中**读取（`sclk_i2s=101MHz, PSR 合法, TXR=2, I2SAHB=0`）：
```
I2SCON(0x00) = 80000805   (RSTCLR | LRINDEX | TXDMA_ACTIVE | ACTIVE)
I2SMOD(0x04) = 00000400   (TXR=2; OPCLK=CDCLK_OUT; slave=0)
I2SFIC(0x08) = 00000000   (TX FIFO=0, 空)
I2SPSR(0x0c) = 00008700   (PSREN | psval=7 -> psr=8)
I2SAHB(0x20) = 00000000   <-- 外部 ADMA 模式（自带 AHB DMA 未用）
I2SSTR0(0x24)= 00000000
I2SSIZE(0x28)= 7fff0000
I2SLVL0..3ADDR(0x30..3c) = 0
I2SVER(0x44) = 80010018   I2SFIC1(0x48)=00000040  I2STDM(0x4c)=00000330  I2SFSTA(0x50)=0002aaa9
CMU_AUD: MUX_SEL_AUD(0x200)=00100000  DIV_AUD0(0x600)=00002211
         DIV_AUD1(0x604)=01131310  ACLK/PCLK/SCLK(0x800/900/a00)=ffffffff
LPASS: RESET(0x08)=00000f1f  INTR_MASK(0x58)=00000000
```

### 20.1 抓厂商对照 dump 的脚本
已放在 `~/Desktop/S6EdgePlus-Linux6-status/dump_i2s.sh`（Android/toybox `devmem`，root）。
用法：设备进 **Android**（厂商内核）→ 播放音乐/铃声（保持）→ `sh dump_i2s.sh`（放到 `/data/local/tmp/`）。
把输出贴回来即可与我们上面的逐位对比。

### 20.2 重点看什么
- **`I2SAHB`**：若厂商 != 0 → 厂商主播放用 I2S 自带 AHB DMA/IDMA（决定是否要走 A 路）。
- `I2SMOD`：确认厂商的 OPCLK/slave/TXR 位。
- `I2SCON`：确认 TXDMA_ACTIVE / RSTCLR 等。
- `CMU_AUD`：MUX/DIV 的实际值（厂商 lpass_set_clk_heirachy 结果）。
- `LPASS INTR_MASK(0x58)`：厂商怎么设的。

---

## 21. 续十四：反编译 stock AP 的 boot.img DTB（厂商权威 i2s 节点）

来源：`/Volumes/ODIN/AP_G9280ZCU2CRF2_...md5` → `boot.img`（ANDROID!，含 DTBH 容器 @0x16bf800，7 个 FDT）。
用 `build/linux-6.6/scripts/dtc/dtc` 反编译。完整 dts 存：
`~/Desktop/S6EdgePlus-Linux6-status/stock-g9280.dts`。

厂商 i2s@11440000（stock）：
```
compatible = "samsung,i2s-v5";
dmas = <0xb3 0x00 0xb3 0x02>;          /* 0xb3 = ADMA; TX=0, RX=2 */
clocks = <0x14 0x19e 0x14 0x1c3 0x14 0x1b1>;   /* pclk_i2s=414, dout_aclk_aud=451, sclk_i2s=433 */
clock-names = "iis","i2s_opclk0","i2s_opclk1"; /* opclk0=dout_aclk_aud, opclk1=sclk_i2s */
samsung,supports-6ch/rstclr/secdai/tdm/low-rfs;
samsung,amixer = <4>;
samsung,lpass-subip;
samsung,tx-iommu; samsung,tx-buf = <0x40000000>; samsung,tx-size = <0x80000>;
samsung,rx-iommu; samsung,rx-buf = <0x41000000>; samsung,rx-size = <0x80000>;
samsung,rx-sram = <0x3045000 0x2000>;
pinctrl-names = "default","idle"; pinctrl-0=<0xb4>; pinctrl-1=<0xb5>;
samsung,supports-esa-dma; samsung,supports-sec-compr;
status = "okay";
```
`i2s0-bus` pinctrl（mainline 缺！）：
```
i2s0-bus {
  samsung,pins = "gpz0-0".."gpz0-6";
  samsung,pin-function = <0x02>;   /* I2S0 */
  samsung,pin-pud = <0x01>;
  samsung,pin-drv = <0x00>;
};
```

### 21.1 结论
- **DMA 控制器确认是 ADMA（PL330）**；厂商 `samsung,supports-esa-dma` → `dma.c` 里 `esa_dma` 走
  `samsung_dma_get_ops()` + **`DMA_CYCLIC`**（外部 ADMA cyclic）。所以 mainline 的“外部 ADMA + cyclic”方向正确。
- 厂商额外用：**固定物理 buffer（0x40000000/0x41000000）+ AUD IOMMU（tx/rx-iommu）+ rx-sram**，
  以及 `i2s_opclk0=dout_aclk_aud`。
- mainline 缺 `i2s0_bus` pinctrl（gpz0 复用），出声需要它（可在 DTB 加，或运行时裸写 gpz0 CON）。
- **DRQ 不来的原因仍未定位**，但已排除“DMA 控制器选错”。

### 21.2 下一步
1. 运行时先把 `gpz0-0..6` 复用到 function 2（模块裸写 pinctrl），排除引脚因素。
2. 重点怀疑：**AUD IOMMU**。厂商对 I2S DMA 启用了 `tx-iommu`；我们把 AUD SysMMU 整个旁路了。
   也许 I2S 的 ADMA 请求/事务需要 SMMU **identity 映射**而非旁路。可试：不旁路、而是给 AUD SMMU
   建 identity 域（mainline `exynos-iommu` 对 7420 支持有限，难）。
3. 或继续核对 `samsung_dma`（legacy）如何配置 ADMA 的 `config.maxburst`/burst（mainline dmaengine PCM 的 burst 可能不同）。

---

## 22. 续十五：强制 BURST / lpass_enable 对照后仍无 DRQ（本轮收尾）

- 给 pl330 加 `PL330_QUIRK_PERIPH_BURST`（7420 强制 BURST）→ 仍 `-EIO`、IRQ 62=0。默认（按 brst_len）
  与强制 BURST 都不行 → **不是 BURST/SINGLE 失配**。
- 厂商 `lpass_enable()`（lpass.c:614）顺序：`enable_pll` → `reg_restore` → `set_mux_pll` →
  `clk_prepare_enable(clk_dmac/clk_sramc)` → `reset_toggle(MEM/I2S/DMA)` → `disable(clk_dmac)` →
  `release_pad` → `memset(mem)`。没有明显的 I2S DRQ 配置项。
- 厂商 `config_setup`: `bfs = blc*slotnum`、`psr = (rclk_srcrate + rfs/2)/frmclk/rfs`（四舍五入），
  与 mainline 仅 psr 取整方式不同，不影响 DRQ。

### 22.1 现在的确定结论
- 硬件通路：ADMA(PL330) ← 外部 DRQ ← I2S0（`dmas=<&adma 0>`，peri 0）；厂商亦如此（ESA=ADMA cyclic）。
- 已对齐/排除：variant(i2sv7)、TXR=2、OPCLK、CDCLK、PSR、sclk(101M)、SMMU bypass、异步桥、
  LPASS 中断掩码、BURST、DMA 线号(0)。
- 现象不变：I2S 配置齐全、FIFO 空、serializer 时钟疑似在跑，但**外部 ADMA 收不到 DRQ**。
- **唯一能快速定位的仍是“厂商播放中的 I2S/AHB/CMU/LPASS 寄存器 dump”**（需 Android）。

### 22.2 给用户的可选路径
1. 临时刷 stock boot.img + system（Odin）跑一次抓 dump，再刷回 mainline/Ubuntu（一次性）。
2. 或接受现状，转别的；本文件已完整记录，随时可续。
3. 或按 7420 TRM 核对 I2S 的 DMA request 输出条件（`I2SAHB`/`I2SCON` 之外是否有额外使能）。

### 22.3 本轮所有产物
- 源码改动：`build/linux-6.6/drivers/dma/pl330.c`（mcode SRAM + 7420 强制 BURST）、
  `sound/soc/samsung/i2s.c`（TX-only 改 `2<<txr`；variant 保持 i2sv7）。
- 设备模块：audbus/audclkhi/pl330_sram2/pl330_burst/lpassup/i2sclk/mclk/irq-madera + 各种只读 dump。
- 反编译：`~/Desktop/S6EdgePlus-Linux6-status/stock-g9280.dts`（厂商完整 DTS）、`dump_i2s.sh`。

---

## 23. 续十六：★PL330 已收到 I2S 的 DMA 请求（ES=1），卡在微码握手

### 23.1 决定性数据（`admastat2.ko` 播放中采样）
```
ES(0x24)     = 00000001   <-- 外设事件 0 已置位 = I2S 正在发 DMA 请求！
INTMIS(0x28) = 00000001
CSR0(0x100)  = 00204007 (运行中) -> 00204000 (停止)，低4位=7=DS_ST_WFP
CPC0(0x104)  = 0304701a -> 03047027 -> 0304702f 后**不再前进**
DSR=00000200  FSRC=00000000  FTR=00000000
```
→ **I2S 确实在请求；PL330 的微码 `DMAWFP` 没有消费该事件**（不是 I2S 不发请求！之前的猜测修正）。

### 23.2 微码 dump（`PL330_DEBUG_MCGEN`）
生成的微码（每周期）：
```
DMALP_0 16
DMALP_1 255
DMAFLUSHP 0
DMAWFPS 0        <-- 等外设 0 的 SINGLE 请求
DMALDS
DMASTPS 0
DMALPENDA_1 bjmpto
DMALPENDA_0 bjmpto
DMALP_1 57
...
DMAEND
```
- `DMAWFPS 0` = Wait For Peripheral，**SINGLE**，peri 0，编码正确。
- 已试：`PL330_QUIRK_PERIPH_BURST`（BURST）→ 无效；强制 `cond=SINGLE` → 无效；
  禁用 `DMAFLUSHP`（`PL330_QUIRK_BROKEN_NO_FLUSHP`）→ 无效。
- 事件 pending（ES=1）但 `DMAWFP` 不消费，BURST/SINGLE/noFLUSHP 都不行 → 异常。

### 23.3 结论与下一步
- 问题已从“I2S 不发请求”改判为 **“PL330 收到请求却不推进微码”**。这非常接近硬件层：
  可能 7420 的 ADMA/P L330 与 I2S 的 DMA 请求握手是**边沿/电平**特性，需要厂商 PL330 的
  特定处理（厂商 pl330 与 mainline 同源但可能被改过 `_ldst_peripheral`/`_emit_WFP` 或 quirk）。
- **强烈建议**：抓厂商“播放中”的 `ES/INTMIS/CSR/CPC/DSR` + I2S 寄存器 dump 对照；
  或对照厂商 `drivers/dma/pl330.c` 的 `_emit_WFP`/`_ldst_peripheral`/quirk 与 mainline 的差异
  （若厂商对 7420 用 `DMAWFP` 的 “P/once” 变体或不同 peri 编码）。
- 源码当前改动（build/linux-6.6）：
  - `pl330.c`：mcode→LPASS SRAM；7420 强制 `cond=SINGLE`；7420 加 `BROKEN_NO_FLUSHP`；
    临时 `#define PL330_DEBUG_MCGEN`（会 dump 微码）。
  - `i2s.c`：TX-only 分支 `2<<txr`。
- 设备模块：audbus/audclkhi/pl330_sram2|burst|single|dbg|noflush/lpassup/i2sclk/mclk/admastat2 等。

---

## 24. 续十七：完全对齐厂商微码顺序后仍失败（软件侧已穷尽）

- 厂商 `_ldst_memtodev`：`WFP→LD→STP→FLUSHP`（每轮 FLUSHP）；mainline 原为循环外一次 FLUSHP。
  已把 mainline `_ldst_peripheral` 改成 7420 走厂商顺序（循环内 FLUSHP）→ **仍 `-EIO`、IRQ 62=0**。
- 至此 PL330 侧软件可调项全部试过：cond(SINGLE/BURST)、FLUSHP(外/内/禁用) 都无效。
- 结合 §23：**`ES=1`（I2S 的请求事件已到 PL330）但 `DMAWFP` 不消费、CPC 卡死不动**，
  这已不是 mainline 驱动逻辑能解释的，指向 **7420 硬件/总线层**（请求握手/ interconnect 门控）。

## 25. 最终状态与建议（软件侧到此）

### 25.1 已确认可用
- 声卡注册、codec(WM1840 rev2) probe、I2S 时钟/PSR/MOD(含 TXR=2) 全部正常。
- ADMA(PL330) 绑定、mcode 在 LPASS SRAM 执行、AUD SysMMU 旁路、AUD 门控/异步桥开。
- PL330 能收到 I2S 的 DMA 请求（`ES=1`），微码已按厂商生成。

### 25.2 卡点
- `DMAWFP` 不消费已 pending 的外设事件 → 通道 `DS_ST_WFP` 不动 → ALSA `-EIO`。
- 软件无法再进一步；需要**厂商播放中的 PL330+I2S 寄存器 dump**、或 **7420 TRM**、或厂商
  `pl330.c` 与 mainline 在请求/事件处理上的**编译级差异**（厂商可能对 7420 用了不同 `_emit_WFP`
  的 peri 编码或额外 quirk，未在源码中体现）。

### 25.3 建议
1. （最优）临时刷 stock boot.img+system 跑一次，抓播放中
   `ES/INTMIS/CSR/CPC/DSR/FSRC` + `I2SCON/MOD/PSR/FIC/AHB` + `CMU_AUD` 对照。
2. 或接受当前状态；文档 §1–§25 已完整记录可续。
3. 若继续，重点应是“PL330 事件/请求握手”的硬件级核对，而非再调 I2S/DMA 软件参数。

---

## 26. 续十八：Android 抓寄存器被 KNOX/TIMA 堵死；厂商确认用外部 ADMA

### 26.1 本轮为抓厂商 dump 做的努力
- 刷回 Android（stock boot.img 方案 A），确认声卡/DAI 是 `i2s0-pri`。
- 无 root → 刷 TWRP（heimdall）→ 刷 Magisk v20.4 → Android 已 root（`su -c id` = uid=0）。
- 但：
  - Android 无 `/dev/mem` 节点；`mknod` 后 `open` 返回 **ENXIO**（stock 内核 `CONFIG_DEVMEM=n`）。
  - 自建**读寄存器的内核模块**（用厂商树 + GCC4.9 编译，vermagic 已精确匹配
    `3.10.61-12451430 SMP preempt mod_unload aarch64`）→ `insmod` 报 **Exec format error**，
    dmesg：`TIMA: lkmauth--verification failed` / `unable to load kernel module`
    → **Samsung KNOX/TIMA 强制内核模块签名**，未签名模块被拒。
- 结论：**不重刷/改 stock 内核，Android 侧拿不到寄存器 dump**。

### 26.2 又一个关键确认
- 厂商 `samsung_dma_get_ops()`（`include/linux/dma/dma-pl330.h`）→
  `samsung_dmadev_get_ops()`（`samsung_dma_is_dmadev()` 为真）→ **就是 dmaengine/ADMA(PL330)**。
  → 厂商主播放（EAX/`i2s0-pri`）确实走**外部 ADMA**，与 mainline 的架构一致。
  结合 §21 的 `samsung,tx-buf`/`tx-iommu`/`rx-sram`，是“外部 ADMA + 固定 buffer + IOMMU”。

### 26.3 现状（本会话最终）
- 已定位到：mainline 上 **PL330 收到 I2S 请求（ES=1）却不消费（DMAWFP 不推进）**，
  而 DMA 控制器/线号/厂商架构均一致；寄存器/时钟/微码顺序也都对齐过。
- 剩余唯一能推进的手段：
  1. **kprobe/ftrace**（debugfs，root 可用，无需模块签名）尝试读 I2S 寄存器——复杂、不确定；
  2. 重编 **stock 内核**（关 TIMA、开 `CONFIG_DEVMEM`）再刷——工程量大、有变砖风险；
  3. 暂停，保留现状。
- 所有进展/脚本/模块/源码改动见 §1–§26；`rdreg`/`dump_all.sh`/`vdump_mod/`（厂商内核模块）已备好，
  一旦有 root+DEVMEM 或可加载模块的环境即可直接用。

---

## 27. 续十九：上网调研 Exynos7420 音频（findings）

### 27.1 上游现状
- mainline 没有 Exynos7420 音频；有社区项目 `github.com/Exynos7420/linux`（v6.10 分支，本地也有副本），
  其 DTS 无音频节点（前面 grep 已确认）。
- 最近的可用参考是 **Exynos5420/5250**（同系 AUD/ADMA/I2S/IDMA）。
- 内核邮件列表：Marek Szyprowski 的 *"ARM: dts: exynos: Add audio power domain support to
  Exynos542x"* —— **AUD 电源域包含：GPZ bank 的 pin controller、AudioSS clock controller、
  PL330 ADMA、I2S controller**（`patchwork.kernel.org/patch/9485083/`）。

### 27.2 上游 Exynos5420 音频节点（`arch/arm/boot/dts/samsung/exynos5420.dtsi`）
```
adma: dma-controller@3880000 {
    compatible = "arm,pl330","arm,primecell";
    clocks = <&clock_audss EXYNOS_ADMA>;
    clock-names = "apb_pclk";
    #dma-cells = <1>;
    power-domains = <&mau_pd>;          /* ADMA 在 AUD 电源域！ */
};
i2s0: i2s@3830000 {
    compatible = "samsung,exynos5420-i2s";     /* i2sv6 */
    dmas = <&adma 0>, <&adma 2>, <&adma 1>;
    dma-names = "tx","rx","tx-sec";
    clocks = <&clock_audss EXYNOS_I2S_BUS>,    /* iis */
             <&clock_audss EXYNOS_I2S_BUS>,    /* i2s_opclk0 = 总线时钟! */
             <&clock_audss EXYNOS_SCLK_I2S>;   /* i2s_opclk1 = SCLK_I2S */
    clock-names = "iis","i2s_opclk0","i2s_opclk1";
    #clock-cells = <1>; clock-output-names = "i2s_cdclk0";
    #sound-dai-cells = <1>;
    samsung,idma-addr = <0x03000000>;
    pinctrl-0 = <&i2s0_bus>;
};
```

### 27.3 与我们运行 DTB 的差异（**待改**）
1. **I2S `i2s_opclk0` 映射错**：应为 AUD 总线时钟（厂商 `dout_aclk_aud` / 5420 的 `EXYNOS_I2S_BUS`），
   我们却被映射成 `sclk_i2s`；`i2s_opclk1` 应为 `sclk_i2s`。
2. 缺 `samsung,idma-addr`（5420 用 `0x03000000`；厂商 7420 用 `rx-sram=<0x3045000 0x2000>` 等）。
3. 缺 `pinctrl-0=<&i2s0_bus>`（GPZ0），mainline 缺 AUD pinctrl 节点。
4. ADMA/I2S 缺 `power-domains`（mainline 7420 没有 AUD genpd；我们用 lpassinit/audbus 手动上电）。
5. ADMA 用 `power-domains` 时，PL330 需要 **irq-safe runtime PM**（邮件列表提到）。

### 27.4 结论/建议
- 上游无 Exynos7420 音频，**没有现成可抄的补丁**；只能照 Exynos5420 的结构把 7420 的
  DT（I2S/ADMA/pinctrl/AUD 电源域）补齐，再复测。
- 我们卡在“PL330 收到 I2S 请求(ES=1)却不消费”，与上述 DT 差异（尤其 opclk0/电源域/idma-addr）
  可能相关，值得按 5420 参考**重做一版正确的 DTB**（当前运行 DTB 是前一阶段从厂商 DTB 改的，多处不一致）。
- 设备当前在 Android（已 root）；回主线需刷回 `smp8_audio4_rev1fix.img` 到 sda7 + 视情况恢复 sda18。

---

## 28. 续二十：串口再次随 GNOME 启动而死 —— 合并把 `console=ttyGS0` 带回来了（2026-09-13）✅

**现象**：本轮多次重启后，串口 `getty@ttyGS0` 在 **GNOME 起来那一刻**稳定失联（无任何回显），必须
`systemctl restart serial-getty@ttyGS0` 才恢复；期间按 GNOME「重启」看起来像“死机”（拆解被 wedged 的串口拖住）。

**定位**：
- `journalctl -k` 仍见 `WARNING ... u_serial.c:688 gs_close+0x114`（§14 的 refcount 小 bug，非主因）。
- `/proc/cmdline` = `console=tty0 console=ttyGS0,115200 maxcpus=1 ...` → **§14 的元凶 `console=ttyGS0,115200` 又回来了**
  （本次合并/新镜像的内建 cmdline 带回）。
- cmdline 来源辨析：boot 头 `hdr[64:576]` 为空；运行 DT `chosen/bootargs` 是厂商 `console=ram ...`；
  **真正生效的是内核内建 cmdline**（在 kernel 镜像里，`findcon2.py` 扫到 kernel 字符串偏移 ~0x1268Axx）。
- 结论：`rmcon.py` 只改 kernel 区是对的；改 boot 头/DT bootargs 无效。

**修复**（沿用 §14 的 `rmcon.py`，并顺带改 `maxcpus`）：
- `/root/setcmd.py`：对 `/dev/sda7` 内核内建 cmdline 做**等长**替换
  - `console=ttyGS0,115200`(21B) → 21 个空格
  - `maxcpus=1` → `maxcpus=8`
  然后重算 boot.img 头 `hdr[576:596]` 的 SHA-1（`sha1(k+ks|r+rs|0|dt+ds)`，小端）并写回；`fsync`。
- 运行输出：`console_removed=0 maxcpus_changed=2`（console 上一次已由 `rmcon.py` 去掉）。

**验证**：重启后 `/proc/cmdline` = `console=tty0                       maxcpus=8 loglevel=8 ...`；
`online=0-7`、`nproc=8` **开机即 8 核**（`exynos7420-smp.service` 变成无操作兜底）；串口在 GNOME 起来后
连续 11 次探测全部存活，**不再需要手动重启 getty**。

> 教训：**每次换/合并 boot 镜像后，必须确认内建 cmdline 不含 `console=ttyGS0`**，否则 §14 复发
> （表现为：GNOME 起来后串口失联、按重启像死机）。
> 另：串口传输脚本务必用**分块 base64**（整行过长会被串口截断，把 shell 卡在 `>` 续行，需发 `^C` 解）。
> 无用的 `ttygs0-hold`（常驻 hold 端口）已删除：它不仅没用，还会让 `gs_open` 不再重新 kick 端点、妨碍 getty 重启恢复。

---

## 29. 续二十一：WiFi(BCM4359 PCIe) 全线打通 + sda7 备份（2026-09-13）✅

### 29.1 硬件与拓扑
- BCM4359 combo：**WiFi 走 PCIe1**（FSYS1 combo PHY），BT 走 UART（未做）。
- 寄存器映射（stock 权威）：elbi `0x15660000` / phy `0x15630000` / block(sysreg) `0x1005265c` /
  pmu `0x105c071c` / **dbi `0x157b0000`** / cmu `0x156e0f00` / phy_pcs `0x156f00e4`；
  config `0x1c000000`；mem `0x1c011000..0x1fffffff`；IRQ SPI 205；perst=`gpg2-0`；WL_EN=`gpf4-6`。

### 29.2 mainline 驱动移植（`drivers/pci/controller/dwc/pci-exynos.c`，模块化）
在 5433 基础上扩展 `samsung,exynos7420-pcie`：
1. **访问任何 PCIe 寄存器前**：`devm_ioremap` CMU_FSYS1(`0x156e0000`)+PMU(`0x105c0000`)；
   - 直写 CMU_FSYS1 gate 使能 PCIe1 时钟：ACLK `0x800|=0x01363e00`、PCLK `0x900|=0xbc400000`、
     SCLK11 `0xa04|=0x00011101`、SCLK12 `0xa08|=0x00001110`、SCLK13 `0xa0c|=0x10000000`
     （S-Boot 实测 gate 已全开 `0xffffffff`，写只是兜底）；
   - **PMU `0x105c071c = 1`（PCIe PHY 电源位）** ← **卡死根因**：不写就访问 phy/elbi/dbi 挂总线。
2. inline PHY 配置（移植厂商 `pci-exynos7420_cal.c`）：cmn 26 组 + trsv 41 组写入 +
   PCS/PMA rst(`0x130`/`0x134`) + sysreg 位操作 + phy_pcs 写 `0x2`。
3. ELBI 7420 专有位：`0xF4=1`(APP_REQ_EXIT_L1_MODE)、`0xF0=1`(CORE_RESETN_DISABLE)、
   `0x038=1`(L1_BUG_FIX)、`cmu|=1`。
4. `perst-gpios`（`of_get_named_gpio`）+ `wl-en-gpios`；start_link 顺序 wl-en→perst→LTSSM。
5. **MSI 派发修复（关键）**：brcmfmac 强制 `pci_enable_msi`，但 mainline exynos 把
   `pp->msi_irq[0] = -ENODEV` → DWC 不装 MSI ISR、`PCIE_IRQ_EN_LEVEL` 被清 0 → MSI 永不触发。
   修复：ELBI ISR 里内联 `dw_pcie_read_dbi(PCIE_MSI_INTR0_STATUS 0x830)` +
   `generic_handle_domain_irq`；start_link 置 `PCIE_IRQ_EN_LEVEL |= IRQ_MSI_ENABLE(BIT1)`；
   ISR 再清 `PCIE_IRQ_LEVEL(0x004)`。（`dw_handle_msi_irq` 未导出，故内联。）
6. `CONFIG_PCI_EXYNOS=m` → `pci-exynos.ko`（便于迭代）；开机由 `exynos7420-pcie.service` 加载。

### 29.3 DT（`exynos7420-zenlte.dts`）
根节点 `pcie@157b0000`：`reg-names=dbi/elbi/phy/block/cmu/phy_pcs/config`、`interrupts=<GIC_SPI 205 …>`、
`ranges`（IO `0x1c001000` / MEM `0x1c011000..0x1fffffff` / config `0x1c000000`）、
`dma-ranges=<0x42000000 0 0 0 0 0x1 0>`（4G inbound iATU，DWC 只从 dma-ranges 配 inbound）、
`perst-gpios=<&gpg2 0>`、`wl-en-gpios=<&gpf4 6>`。

### 29.4 内核配置
`CONFIG_PCI_EXYNOS=m`、`CONFIG_BRCMFMAC_PCIE=y`；内建 cmdline `console=tty0 maxcpus=8 ...`（无 ttyGS0）。

### 29.5 固件（关键！）
- Android `bcmdhd_sta.bin_b1`（`9.97.2.3`，bcmdhd/DHD 协议）与 mainline brcmfmac **不兼容**：
  dongle 能起但 `brcmf_msgbuf_query_dcmd` 超时、`cur_etheraddr` 失败、`Dongle setup failed`。
- 换 **NXP/Murata brcmfmac-msgbuf 版 BCM4359B1 固件**（`9.40.109 (r710128 CY)`，
  `Broadcom PCIE MSGBUF driver`）：来源 `github.com/nxp-imx/imx-firmware` →
  `cyw-wifi-bt/1FD_CYW4359/`。放入 `/lib/firmware/brcm/`：
  - `brcmfmac4359-pcie.bin` (613431 B) sha256 `6469cab966e3…54c802`
  - `brcmfmac4359-pcie.txt` (4926 B) sha256 `ba0b8dedad95…28e161`
  - `brcmfmac4359-pcie.clm_blob` (4863 B) sha256 `076e7fb4958e…c945876b`
- 之后 `wlp1s0` 出现，`dmesg`：`Firmware: BCM4359/5 wl0 ... 9.40.109 (r710128 CY)`。

### 29.6 用户态与连接
- 精简 rootfs 缺网络工具 → 装 `iproute2`/`iw`/`wpasupplicant`（+依赖），再装 `network-manager`
  （直接借设备自身网络 `apt-get`，因 WiFi 已通）。
- wpa_supplicant 配置 SSID=`iPhone` + psk；NM：`nmcli con add type wifi ifname wlp1s0 con-name iPhone ssid iPhone`
  + `wifi-sec.psk` → `connected`，IP `172.20.10.3/28`、默认路由 `172.20.10.1`、ping `8.8.8.8` 通、
  `autoconnect=yes`；**GNOME 右上角 WiFi 图标已出现**（NM 提供）。

### 29.7 备份（2026-09-13）
- **sda7 启动镜像**：`/Volumes/xtb/linux-backup-20260912/backup-20260913/sda7_boot_20260913.img`
  （29360128 B，sha256 `f28b2e3d8de6f53f5e10cca0e6ddeab0b0a231fa6d4e6f4ae8c3935df0ecd92b`）。
  内容 = `pcie_test3.img`：内核 Image(`BRCMFMAC_PCIE=y`) + DTBH（含 pcie 节点 + dma-ranges）+ ramdisk；
  **不含 `pci-exynos.ko`**（模块在 rootfs）。
  - 拉取方式：设备本地 `dd` + `python3 -m http.server 8899`，Mac `curl`（14.5s，走 WiFi）。
- **模块**：`/lib/modules/6.6.0/extra/pci-exynos.ko`（120472 B；也在 `/root/pci-exynos.ko`）。
- 固件三件套在设备 `/lib/firmware/brcm/`；用户态 NM/iw/wpasupplicant 已装。

### 29.8 待办
- 蓝牙（BCM4359 UART：DT uart + `hci_bcm` + `BCM4359*.hcd` + `btattach`）。
- 轻量现代浏览器。
- 把 PCIe 驱动/DT/固件固化进内核与新的 rootfs 备份。

## 30. 续二十二：蓝牙(BCM4349B1 / BCM4359) 全线打通（2026-09-13）✅

### 30.0 结论速览
- 蓝牙控制器已 **UP RUNNING**，`hciconfig hci0`：BD `43:49:B1:00:1F:AC`，HCI 4.2，
  固件 `BCM4359B1 37.4MHz Class 2 Murata Type-1FD dLNA-0162` + `BCM4349B1 (002.002.013) build 0370`
  （来自 `brcm/BCM4349B1.hcd`）。重启后自动生效。
- **之前一直失败的根本原因有三个，全部修复。**

### 30.1 ★最关键：蓝牙在 **UART4（AUD/LPASS，0x11460000 / gpz1）**，不在 UART1！
`exynos7420-zenlte_common.dtsi`：
- `serial_1: uart@14C20000 { /* Enable UART channel for debug port */ status="okay"; }` → **UART1 是调试口**
- `serial_4: uart@11460000 { pinctrl-0=<&uart_bt_active &uart_bt_output_sleep &uart_bt_input_sleep>; status="okay"; }` → **蓝牙在 UART4**
- `exynos7420-pinctrl.dtsi`：`uart_bt_active` 在 **pinctrl@114B0000（AUD）**，用 **gpz1-3..0 function 2**。
- 厂商 `drivers/bluetooth/bcm4359.c`：`#define BT_UPORT 4`。
- 厂商 `exynos7420-zenlte_gpio_09.dtsi`：`gpz1-0=BT_UART_TXD / gpz1-1=RXD / gpz1-2=CTS / gpz1-3=RTS`。
- 厂商 serial_4 用 `samsung,lpass-subip`（DOMAIN_AUD），时钟 `<&clock 416/432/455>`（pclk_uart/sclk_uart），
  `uart-sclk-frequency=117MHz`，IRQ SPI 91；AUD pinctrl `pinctrl@114B0000` IRQ SPI 92。
> 早期把它放在 `&serial_1` 是错的，芯片永远不应答（这也解释了为何 DTB 一改 `SERIAL_SAMSUNG=y` 就卡 logo——那是另一个 bug，见 30.2）。

### 30.2 内核修复①：`samsung_tty` 载入/探测挂死（`aclk_peric1_66` 非 critical）
- 现象：内置 `SERIAL_SAMSUNG=y` + 蓝牙 DT → 卡三星 logo；改 `=m` 后 `insmod samsung_tty` 也硬挂。
- 根因（分步探针 `probe_stop=N` 定位）：挂死在 `s3c24xx_serial_probe()` 末尾的
  `clk_disable_unprepare()` —— 关 UART 门控时 CCF 会关掉父时钟 **`aclk_peric1_66`
  （TOP0 `ENABLE_ACLK_TOP03` 0x105d080c bit12）**，而该时钟是 **CMU_PERIC1 寄存器接口**的访问时钟；
  之后再访问 CMU_PERIC1（关 `sclk_uart1`）就挂总线。
- 修复（仿上游对 `aclk_fsys1_200` 的处理）：`drivers/clk/samsung/clk-exynos7.c` 给
  `CLK_ACLK_PERIC1_66`（及 `CLK_ACLK_PERIC0_66`）加 **`CLK_IS_CRITICAL`**。
  （`CLK_IS_CRITICAL` 在 clock 注册时即 enable，见 `drivers/clk/clk.c` 的 `__clk_core_init`，
  与 cmdline 的 `clk_ignore_unused` 无关。）

### 30.3 内核修复②：把 AUD UART4 补进 mainline（exynos7.dtsi 原本只有 serial_0..3）
- `arch/arm64/boot/dts/exynos/exynos7.dtsi`：
  - alias 增加 `pinctrl9 = &pinctrl_aud;`
  - 新增 `pinctrl_aud: pinctrl@114b0000 { compatible="samsung,exynos7-pinctrl"; reg=<0x114b0000 0x1000>; interrupts=<GIC_SPI 92 LEVEL_HIGH>; }`
    （驱动 `pinctrl-exynos-arm64.c` 的 `exynos7_pin_banks9` 已含 gpz0/gpz1，按 of-alias 选实例 9）
  - 新增 `serial_4: serial@11460000 { compatible="samsung,exynos4210-uart"; reg=<0x11460000 0x100>;
    interrupts=<GIC_SPI 91 LEVEL_HIGH>; clocks=<&cmu_aud PCLK_UART>,<&cmu_aud SCLK_UART>;
    clock-names="uart","clk_uart_baud0"; status="disabled"; }`
- `include/dt-bindings/clock/exynos7-clk.h`：AUD 段增加 `PCLK_UART=6`、`SCLK_UART=7`，`AUD_NR_CLK=8`。
- `drivers/clk/samsung/clk-exynos7.c`：AUD CMU 里原本 id=0 的 `pclk_uart`/`sclk_uart` 门控改用具名 ID
  （`ENABLE_PCLK_AUD` bit25 / `ENABLE_SCLK_AUD` bit29）。
- `arch/arm64/boot/dts/exynos/exynos7420-zenlte.dts`：
  - `&pinctrl_aud { uart_bt_active: uart-bt-active { samsung,pins="gpz1-3","gpz1-2","gpz1-1","gpz1-0"; samsung,pin-function=<2>; samsung,pin-pud=<3>; }; };`
  - 蓝牙子节点从 `&serial_1` **移到 `&serial_4`**，并加 **LPO 时钟**：
    `clocks = <&s2mps13_osc S2MPS11_CLK_BT>; clock-names = "lpo";`
    （`hci_bcm` 会 `clk_set_rate(32768)` + enable；`s2mps13_bt` 是 PMIC 给 BCM 的 32.768kHz LPO）
  - `&serial_1 { status = "disabled"; };`

### 30.4 ★另外两个致命阻断（Gemini 定位，均已验证）：AUD Pad Retention + LPASS UART 中断
即使 UART4 寄存器可读写、TX 打空（`UTRSTAT=0x6`），芯片仍 **TX 4 / RX 0**。原因：
1. **AUD Pad Retention 未释放**：AUD 域（gpz0/gpz1）在 PMU 层有 pad retention 隔离，
   冷启/未释放时 gpz1 物理引脚被“按住”，UART 信号出不去/进不来。
   厂商 `lpass_release_pad_reg()`：`PMU 0x105c3028 |= (1<<28)`（PAD_RETENTION_AUD_OPTION）、
   `PMU 0x105c1340 = 1`（GPIO_MODE_AUD_SYS_PWR_REG）。主线无 lpass 驱动 → 从未释放。
2. **LPASS UART 中断屏蔽**：`LPASS 0x11400058`(INTR_CPU_MASK) 是 **pass-through enable**
   （置 1 才放行到 GIC SPI 91），读到 0 表示**全屏蔽**。需写 `bit1`（UART），实测写 `0xff`。
- 用户态验证（无需刷机）：
  `0x105c3028=0x10000000`、`0x105c1340=1`、`0x11400058=0xff`，然后 `rmmod/modprobe hci_uart`
  → 立刻出现 `BCM: chip id 114` → `BCM4349B1` → 固件 Patch → `UP RUNNING`。

### 30.5 持久化：`exynos7420-bt-power.service`
- `/usr/local/bin/exynos7420-bt-power.sh`：用 python mmap `/dev/mem` 写上述 3 个寄存器，
  再 `rmmod hci_uart; modprobe hci_uart` 重跑 Broadcom 初始化。
- `/etc/systemd/system/exynos7420-bt-power.service`：`Type=oneshot`，`Before=bluetooth.service`，
  `WantedBy=multi-user.target`。已 `enable`，重启自动生效。
- （后续可移到内核：给 exynos7 AUD pinctrl 补 retention 数据 + serial_4/lpass 里写寄存器。)

### 30.6 固件与用户态
- `/lib/firmware/brcm/BCM4349B1.hcd`（NXP `BCM4349B1_002.002.014.0162.0370.hcd`，subver 0x420e）。
- bluez 已装：`bluetoothd/btattach/bluetoothctl/hciconfig/hcitool`。
- `CONFIG_BT=m`、`BT_HCIUART=m`（H4/BCM/SERDEV=y）；依赖模块按序：`ecc.ko`→`ecdh_generic.ko`→
  `bluetooth.ko`→`btbcm.ko`/`btqca.ko`→`hci_uart.ko`（已放 `/lib/modules/6.6.0/`，`depmod` 可解析）。

### 30.7 镜像 / 文件
- 新 boot（含时钟修复 + AUD UART DT + LPO）：`WORKING-66bt/boot_bt_lpo.img`（27709472 B）。
- 关键中间产物：`boot_bt_serialm.img`（仅时钟修复）、`boot_bt_uart4.img`（+AUD UART）、`boot_bt_lpo.img`（+LPO）。
- 备份到 `/Volumes/xtb/linux-backup-20260912/backup-20260913/`（见同步）。

### 30.8 待办
- 把 30.3/30.4 的改动固化进内核源码/DT（而非仅 service），并更新 sda7/rootfs 备份。
- 蓝牙配对/音频（SCO/A2DP）实测。
- 轻量现代浏览器。

### 30.9 GNOME 右上角 WiFi/蓝牙开关不显示 → 起 `gsd-rfkill`（2026-09-13）
- 现象：`network-manager`/`bluetooth`（BlueZ）都 active、`wlp1s0` 已连、`hci0` UP，但 GNOME 右上角快速设置里**没有 WiFi/蓝牙开关**。
- 根因：本机 GNOME 会话是**定制直启**（见 S6EdgePlus-Linux6-status.md §15.3：真 `gnome-session` 起不来，
  用 `/root/.bash_profile` 里 `dbus-run-session -- bash -c 'sessionmanager-shim & gsd-power & gnome-shell --wayland --display-server'`）。
  它**只启动了 `gsd-power`**，缺 **`gsd-rfkill`**（GNOME 快速设置的 WiFi/蓝牙/飞行模式依赖 `org.gnome.SettingsDaemon.Rfkill`）。
  注意：该会话用的是 **`dbus-run-session` 的私有总线**（`DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/dbus-XXXX`），
  **不是** `/run/user/0/bus`；`gsd-rfkill` 必须起在这个私有总线上才被 shell 看到。
- 修复：`.bash_profile` 的会话命令里加 `(sleep 12; exec /usr/libexec/gsd-rfkill) &`；重启会话后右上角
  **WiFi 与蓝牙开关出现**。（原文件备份 `/root/.bash_profile.bak-bt`。）
- 诊断要点：从运行中的 `gnome-shell` 读总线：`P=$(pgrep -x gnome-shell); A=$(tr '\0' '\n' </proc/$P/environ | grep '^DBUS_SESSION_BUS_ADDRESS=' | cut -d= -f2-)`，
  再 `DBUS_SESSION_BUS_ADDRESS=$A /usr/libexec/gsd-rfkill`。
- `gsd-rfkill` 会报 `RegisterClient returned "(s)" expected "(o)"`（shim 返回类型不严格），但不影响开关工作。

## 31. 轻量现代浏览器：Epiphany (GNOME Web)（2026-09-13）✅
### 31.1 选型与安装
- 设备：3.8G RAM（空闲 2.8G）、根分区剩 19G、aarch64、GNOME Wayland。
- 选 **Epiphany (GNOME Web)**：apt 直装、WebKitGTK + GTK4、GNOME 原生集成（书签/密码/搜索）。
  `apt-get install -y epiphany-browser`（46.5，拉入 `libwebkit2gtk-4.1-0 2.52.6` / `libjavascriptcoregtk-4.1-0` 等）。
- 备选：Badwolf（更轻的 WebKitGTK，需自编译）、Falkon（QtWebEngine/Chromium，较重）。Midori 不在 noble 源。

### 31.2 启动方式
- 图形：GNOME「活动 → 应用网格」点 **Web**（`/usr/bin/epiphany-browser`）。
- 远程/脚本：`/root/launch-epiphany.sh epiphany-browser [url]` —— 从运行中的 `gnome-shell` 取
  **私有会话总线** `DBUS_SESSION_BUS_ADDRESS`，设 `XDG_RUNTIME_DIR=/run/user/0`、`WAYLAND_DISPLAY=wayland-0`、
  `GDK_BACKEND=wayland`，再 `setsid` 启动。

### 31.3 ★关键网络坑：热点无 IPv6 导致浏览器“卡死”
- 现象：`ping 8.8.8.8` 通、DNS 解析出 `2606:...`（仅 IPv6），但 `curl https://example.com` / 浏览器长时间无响应。
- 根因：**iPhone 热点不提供 IPv6**，系统 `getaddrinfo` 默认优先 IPv6 → 连接一直等超时。
- 修复：`/etc/gai.conf` 加一行 `precedence ::ffff:0:0/96  100`（强制 IPv4 优先）。之后 `getent ahosts example.com`
  返回 IPv4，`curl http://example.com` `200`、`0.6s`，浏览器正常。

### 31.4 渲染与告警
- `GNOME Web` 日志 `Gdk-CRITICAL ... panvk_physical_device.c: Mali-T760 not supported (VK_ERROR_INCOMPATIBLE_DRIVER)`：
  PanVK 不支持 T760，WebKit 回退到 GL/软件合成，不影响使用（性能一般）。
- `a11y bus`/`org.freedesktop.secrets` 告警无害（缺 AT-SPI / keyring；书签/密码暂不持久，可另装 `gnome-keyring`）。

### 31.6 ★窗口化花屏（GTK4/WebKit GPU 加速）修复（2026-09-13）
- 现象：终端(htop/VTE)正常；`设置`、`GNOME Web` 等 **GTK4/WebKit(wl_dmabuf/GL) 应用窗口化时花屏**，全屏正常。
- 根因：这些应用产出 GPU dma-buf，交给 Mutter；Mutter 导入 Exynos 显示控制器时命中
  `exynos_drm_gem_prime_import_sg_table: buffer chunks must be mapped contiguously` —— Exynos DECON 只接受
  **单一连续 DMA 地址**，而本内核**未启用 `CONFIG_EXYNOS_IOMMU`**（Exynos SYSMMU 驱动缺席），导入的 Panfrost
  shmem buffer 是直接物理映射、物理页不连续 → 被拒。终端走软件/shm 路径所以正常。
- 已尝试无效：`MUTTER_DEBUG_FORCE_KMS_MODE=simple`/`USE_KMS_MODIFIERS=0`/`DISABLE_HW_CURSORS=1`（错误照旧）。
- **有效修复（软件渲染，牺牲 GPU 加速）**：会话级环境变量（写入 `/root/.bash_profile`，`gnome-shell` 继承，所有
  app-grid 启动的 GTK4/WebKit 应用都生效）：
  - `WEBKIT_DISABLE_DMABUF_RENDERER=1`
  - `WEBKIT_DISABLE_COMPOSITING_MODE=1`
  - `GSK_RENDERER=cairo`
  另保留 `MUTTER_DEBUG_USE_KMS_MODIFIERS=0`、`MUTTER_DEBUG_DISABLE_HW_CURSORS=1`。
  - 远程单应用启动脚本：`/root/launch-epiphany-soft.sh`（含上述变量）。
- **正解（TODO）**：启用 Exynos SYSMMU/IOMMU（`CONFIG_EXYNOS_IOMMU=y` + DECON 的 SYSMMU DT 节点），让导入 buffer 经
  IOMMU 得到连续 IOVA，即可恢复 GPU 加速；厂商树有对应节点，但 mainline exynos-iommu 对 7420 支持有限。
- 背景：`dmesg` 另有 `panfrost ... gpu sched timeout` 偶发（启动阶段 4 次）。

### 31.7 备份
- `/Volumes/xtb/linux-backup-20260912/backup-20260913/bt/`：`bash_profile.final-browser`、`launch-epiphany-soft.sh`（+ 前述 BT 产物）。

### 31.5 产物
- 设备：`/usr/bin/epiphany-browser`、`/root/launch-epiphany.sh`、`/etc/gai.conf`（IPv4 优先）。
- 备份：`backup-20260913/bt/`（含 launch-epiphany.sh）。
