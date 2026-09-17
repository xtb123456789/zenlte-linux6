# 求助（第二轮）：Exynos7420 mainline 6.6 内建 EXYNOS_IOMMU=y 必卡开机 logo —— 请全面排查

> 上一轮你给的结论/最小 patch 清单我**已全部实施**，但内建（=y）**仍然卡 bootloader logo**。
> 模块（=m）+ 运行期 insmod 一切正常。请做一次彻底排查，给出**可执行的调试步骤 + 最终 patch**。

## 0. 环境与工具（便于你给命令/补丁）

- 设备：三星 Galaxy S6 Edge+ SM-G9280（Exynos7420，zenlte），mainline Linux 6.6（Ubuntu 24.04 ARM64）。
- 内核树：`/Volumes/kernel_build/linux-6.6`；厂商树：`/Volumes/kernel_build/kernel`（3.10.61）。
- 构建：`gmake ARCH=arm64 CROSS_COMPILE=<aarch64-...-> -j8 Image modules dtbs`。
- 刷机：TWRP + adb：`dd if=boot.img of=/dev/block/sda7 bs=4096`；rootfs 在 TWRP 下挂 `/dev/block/sda18` 到 `/mnt/rootfs`（系统内路径 `/lib/modules/6.6.0/extra/exynosdrm.ko`）。
- 串口：`/dev/cu.usbmodem2301`（115200），有 shell（登录后可用 `echo`/`dmesg` 验证）。
- 启动 cmdline：内核 `CONFIG_CMDLINE_FORCE=y`，DTB `chosen/bootargs` 里带 `deferred_probe_timeout=0`。
- 显示：DECON 0x13930000，SimpleFB 先点亮，随后 exynosdrm 模块接管（模块在 rootfs 里）。
- 备份：已知可启动镜像 `boot_bt_iommu_mod2.img`（=m 版），已知可用旧显示驱动 `/root/exynosdrm.ko.bak`。

## 1. 硬件事实（已实测）

- SysMMU 为 **v6**：`0x13a00034`(REG_MMU_VERSION) = `0x60020014`；解码 `MMU_RAW_VER=(reg>>21)&0x7ff = 0x300` → major 6 / minor 0 → mainline 走 `MMU_MAJ_VER<7` 分支 = `sysmmu_v5_variant`（v6 与 v5 寄存器布局一致，不涉及 v7 CAPA/VCR）。
- DISP SYSMMU：`13a00000`(RO, SPI 176)、`13a10000`(RW, SPI 179)。DECON：`13930000`。
- 运行期实测（模块版 insmod 成功后）：`0x13ad0804/0x13ad0904 = 0xffffffff`（时钟门全开）；DISP 域 `0x105c4080=0xf`、`0x105c4084=0x3000f`。
- 厂商：`pd_disp` 基址 **0x105c4080**（mainline 原写 0x105c4120 错）；`LOCAL_PWR_CFG=0xf`；`OPTION=0x0102`；DISP 上电序列 TOP0 `0x080c`bit28、`0x0a20`bits28/24/20/16/12、VPP `0x13ed0800`bits0-3、PMU `0x1450/1490/14d0/1510/1550/1590` 清位。

## 2. 当前内核改动（= 你上轮建议 + 更早的修复，全部已实施）

1. `drivers/iommu/exynos-iommu.c`
   - `exynos_iommu_ops` 已加 `.owner = THIS_MODULE`（修复模块化时 `iommu_device_register()` 的 `WARN_ON(is_module_address(ops) && !ops->owner)` → `-EINVAL(-22)`）。
   - `exynos_sysmmu_probe()` 不再调用 `__sysmmu_get_version()`，改为静态：
     `if (IS_ENABLED(CONFIG_ARM64) && of_device_is_compatible(dev->of_node, "samsung,exynos-sysmmu")) { data->version = MAKE_MMU_VER(6,0); data->variant = &sysmmu_v5_variant; } else { __sysmmu_get_version(data); }`
     （即 probe 阶段不碰时钟、不读寄存器。）
   - `err_dma_set_mask:` 回滚补 `pm_runtime_disable(dev); if (dma_dev == dev) dma_dev = NULL;`。
   - 由 `core_initcall` 改为 `module_init/module_exit`。
   - `exynos_iommu_attach_device()` **未改**（仍是 probe/attach 时就 `__sysmmu_enable()`）。
2. `drivers/iommu/Kconfig`：`EXYNOS_IOMMU` `bool → tristate`。
3. `drivers/clk/samsung/clk-exynos7.c`：新增 4 个 DISP SYSMMU 门控（`CLK_ACLK_DISP_RO_SYSMMU`/`..RW`/`CLK_PCLK_DISP_RO_SYSMMU`/`..RW`，CMU_DISP `0x0804/0x0808/0x0904/0x0908` bit0），**flags 已按原厂改为 0（撤掉 CLK_IS_CRITICAL）**；父时钟 `top_aclk_disp_400`（原厂经 USERMUX）。
4. `include/dt-bindings/clock/exynos7-clk.h`：新增 4 个 ID（12–15），`DISP_NR_CLK=16`。
5. `arch/arm64/boot/dts/exynos/exynos7.dtsi`
   - `sysmmu_disp_ro@13a00000`(SPI176)、`sysmmu_disp_rw@13a10000`(SPI179)：`compatible="samsung,exynos-sysmmu"`、`#iommu-cells=<0>`、clocks/clock-names(aclk/pclk)，**已删除 `power-domains`**。
   - `decon@13930000`：**已加 `power-domains = <&pd_disp>;`**，并保留 `iommus = <&sysmmu_disp_ro>, <&sysmmu_disp_rw>;`。
   - `pd_disp` → `power-domain@105c4080`、`compatible="samsung,exynos7420-pd"`。
6. `drivers/pmdomain/samsung/exynos-pm-domains.c`：新增 `samsung,exynos7420-pd` 匹配 + DISP pre/post 上下电序列。
7. `drivers/gpu/drm/exynos/exynos_drm_dma.c`：`exynos_drm_register_dma()` 里当
   `IS_ENABLED(CONFIG_IOMMU_DMA)` 且 `iommu_get_domain_for_dev(priv->dma_dev)` 返回 NULL
   且 `dev`/`priv->dma_dev` 的 DT 有 `iommus` 时，返回 `-EPROBE_DEFER`（不再缓存"无 IOMMU"状态）。

## 3. 决定性实验对比（请重点分析）

| 镜像 | CONFIG_EXYNOS_IOMMU | DT/时钟/驱动改动 | 结果 |
|---|---|---|---|
| `boot_bt_iommu_mod2.img` | **=m** | 同上（含 sysmmu 节点 + decon iommus） | **开机正常进桌面**；之后 `insmod exynos-iommu.ko` 两 SYSMMU 成功 bind，串口不阻塞 |
| `boot_bt_iommu9.img` | **=y** | 同上（+ 你上轮全部建议） | **卡 bootloader logo** |

**两张镜像除 `CONFIG_EXYNOS_IOMMU=y/m` 外无其他差异**（同一份 DT、同一份 clk、同一份驱动源码）。
→ 卡死几乎可以确定发生在 **内建的 init 阶段**：`exynos_iommu_init()`（core_initcall）
→ `platform_driver_register(&exynos_sysmmu_driver)`
→ `bus_set_iommu(&platform_bus_type, &exynos_iommu_ops)`
→ `iommu_bus_init()` → `bus_for_each_dev(bus, NULL, NULL, iommu_probe_device)`。

模块版同一段代码在**桌面已起来、DISP 时钟/电源域已就绪**时执行，完全正常。
所以问题不是"能不能 probe"，而是**执行时机**：内建时这段扫描发生在显示子系统点亮之前。

## 4. 需要你排查/回答的问题

1. **请把 Linux 6.6 这段路径逐行展开**：
   `bus_set_iommu()` → `iommu_bus_init()` → `bus_for_each_dev(..., iommu_probe_device)`
   → `__iommu_probe_device()` → `of_iommu_configure()`/`exynos_iommu_of_xlate()`
   → 默认 domain 建立 → `exynos_iommu_attach_device()` → `__sysmmu_enable()`。
   明确指出**到底哪一步第一次真正读写 SYSMMU/DECON 硬件寄存器**（给出函数名+行号级别的判断），
   并说明 6.6 里默认 domain 是在 `iommu_probe_device()` 阶段就 attach，还是延迟到驱动 `iommu_attach_device()`。
   如果 6.6 的 `bus_for_each_dev(iommu_probe_device)` 在 core_initcall 时就会对 **尚未 probe 的 DECON**
   建立 fwspec/domain 并触发 `__sysmmu_enable()`，请给出源码依据。
2. **为什么 `__sysmmu_enable()` 在此时访问会整机卡死**？请结合：
   SYSMMU 的 aclk/pclk 此刻可能未使能（DISP 时钟树由 DECON 打开）、DISP 电源域可能未上电、
   SYSMMU 处在 DECON 正在扫描的 AXI 通路上（bootloader logo 还在显示）。
   请解释"时钟未开时读 SYSMMU 寄存器"具体会造成什么（总线挂起 / SError / AXI 无响应 / CPU 停在 D 状态），
   以及为什么模块版（时钟已开）就没事。
3. **给出能过开机的最终修法**，并评估以下候选（可多选/组合，给出你推荐的顺序与理由）：
   - a) `exynos_iommu_attach_device()` 在 master 未 runtime-PM active / SYSMMU 时钟未 ready 时返回 `-EPROBE_DEFER`（怎么判断？`pm_runtime_active(dev)`？`clk_is_enabled()`？`pm_runtime_get_sync` 会不会反而死锁？）。注意 attach 是 IOMMU core 调的，返回 `-EPROBE_DEFER` 会被 core 怎样处理？
   - b) 把 `__sysmmu_enable()` 的硬件操作**延迟到 master 第一次真正需要 DMA 映射时**（对齐厂商做法：vendor probe 只 `clk_prepare()` 不 enable、不读版本，enable 在 master 上电流程里做）。
   - c) `exynos_iommu_init()` 换更晚的 initcall / 或延迟 `bus_set_iommu()` 到显示子系统就绪（怎么判定"就绪"？）。
   - d) 保持 `=m`，但用 initramfs/early module 在 DECON probe 前加载 IOMMU（是否可行？Ubuntu 的 initramfs 里放模块的注意事项？）。注意我们已有 `-EPROBE_DEFER` 改动，理论上 DECON 会等 IOMMU。
   - e) 别的更干净的方案（例如让 SYSMMU 的 clock/power-domain 依赖通过 DT 正确建模，让内核自动排序；或让 `of_iommu_configure()` 失败时 DECON 先以无 IOMMU 方式起来、后补 attach）。
4. **调试方案**：请给出一套**能定位卡死点**的最小实验序列（越具体越好，最好能直接照做）：
   - 例：把 `bus_set_iommu()` 临时注释掉编译 → 是否还能卡？（隔离变量）
   - 例：在 `exynos_iommu_init`、`bus_set_iommu`、`iommu_bus_init`、`exynos_iommu_of_xlate`、`exynos_iommu_attach_device`、`__sysmmu_enable` 各插一条 `pr_info`，用串口 console 看最后停在哪一条。
   - 例：如何拿到卡死瞬间的现场（串口 console 是否够？需要 pstore/ramoops 吗？`sysrq` 还能用吗？卡死时 USB 是否还活着？）。
   - 例：如何在内建版上确认"内核其实活着但 DECON 永久 deferred"（`/sys/kernel/debug/devices_deferred`、`/proc/interrupts`、串口登录）——这一步我们**还没完成**，请给出可操作的验证流程。
5. **请特别澄清**：内建卡 logo 时，串口 shell 是否应该还能用？
   （我们之前在另一次内建卡死中观察到"串口命令不返回"；但没能确定是内核死锁还是 DECON deferred。
   请给出判断标准，以及两种情况各自对应的修法。）
6. **`deferred_probe_timeout=0`**：我们 cmdline 有它。它是否会让 DECON 的 `-EPROBE_DEFER` 变成"永久放弃"？
   如果移除它，DECON 会不会在内建版上等到 IOMMU/时钟就绪后自己起来？请给出确切结论与验证方法。

## 5. 期望输出格式

1. **根因判定**：内建卡死的确切机制（函数/行号级）。
2. **调试步骤**：按顺序可执行的最小实验清单（每步：改什么、怎么看结果、结论分支）。
3. **最终 patch**：文件级 diff（可直接应用），目标是内建 `=y` 也能开机，并且 DECON 经 IOMMU 做 DMA 映射。
4. **验证清单**：开机后应检查哪些 sysfs/debugfs/寄存器/dmesg 关键字，确认 GPU 加速合成真的生效
   （`exynos_drm_gem` 不再报 `buffer chunks must be mapped contiguously`、GNOME 滑动流畅）。

## 6. 附：可随时提供的原始材料（需要请点名）

- 内建卡死前的完整串口输出（如果你认为值得，我可以再刷一次 iommu9 专门抓串口）。
- `exynos_iommu_attach_device()`、`__sysmmu_enable()`、`exynos_iommu_of_xlate()` 的 6.6 源码原文。
- 我们 DTS 里 sysmmu/decon/pd_disp 节点最终内容 + 反编译 DTB 片段。
- 模块版完整 dmesg（开机 + insmod 前后）。
- `exynos_sysmmu_probe` 反汇编（模块版）。
- 时钟树 `clk_summary`（模块版 insmod 后）。
