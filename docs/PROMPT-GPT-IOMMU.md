# 求助：Exynos7420 (S6 Edge+ / SM-G9280 "zenlte") mainline Linux 6.6 显示 IOMMU 挂载问题

## 一、目标

设备：三星 Galaxy S6 Edge+ SM-G9280（Exynos7420，zenlte），运行 mainline Linux 6.6（Ubuntu 24.04 ARM64）。
WiFi/蓝牙（UART4/LPASS）/浏览器/桌面均已可用。当前唯一目标：

**让 Exynos DECON（显示控制器 0x13930000）挂到 SysMMU/IOMMU 上，从而接受 Panfrost 输出的非连续 dma-buf，恢复 GNOME 硬件加速合成。**

现状是软件渲染（WEBKIT_DISABLE_DMABUF_RENDERER=1 等绕过），DECON 报
`buffer chunks must be mapped contiguously`，拒收非连续 dma-buf。

## 二、硬件事实

- Exynos7420 SysMMU 为 **v6**：`0x13a00034`(REG_MMU_VERSION) 实测 `0x60020014`。
  mainline 解码 `MMU_RAW_VER=(reg>>21)&0x7ff` → `0x300` → major=6, minor=0，
  命中 `MMU_MAJ_VER < 7` 分支 → `sysmmu_v5_variant`（v6 与 v5 寄存器布局一致，不走 v7 的 CAPA/VCR）。
- DISP 两个 SYSMMU：`13a00000`(RO, SPI 176)、`13a10000`(RW, SPI 179)。
- 运行期实测：时钟门 `0x13ad0804/0x13ad0904 = 0xffffffff`（全开）；
  DISP 电源域 `0x105c4080=0xf`、`0x105c4084=0x3000f`（已上电）。
- 厂商事实：`pd_disp` 寄存器基址是 **0x105c4080**（mainline 原写的 0x105c4120 是错的）；
  `LOCAL_PWR_CFG=0xf`；`OPTION(base+0x8)=0x0102`。
  DISP 上电序列：TOP0 `0x080c` bit28、`0x0a20` bits28/24/20/16/12、VPP `0x13ed0800` bits0-3、
  PMU `0x1450/1490/14d0/1510/1550/1590` 清位。

## 三、软件现状（内核树，已改动）

1. `drivers/iommu/exynos-iommu.c`
   - `exynos_iommu_ops` 补 `.owner = THIS_MODULE`。
     原因：模块化时 `iommu_device_register()`（`drivers/iommu/iommu.c:257`）有
     `WARN_ON(is_module_address((unsigned long)ops) && !ops->owner)` → 直接返回 `-EINVAL(-22)`。
     反汇编确认栈顶 `exynos_sysmmu_probe+0x210` 正是 `bl iommu_device_register` 的返回地址。
   - probe 中**不再调用** `__sysmmu_get_version()`（它会 `clk_prepare_enable` 后读 `REG_MMU_VERSION` 再关时钟）。
     改为静态：`data->version = MAKE_MMU_VER(6,0); data->variant = &sysmmu_v5_variant;`
     （条件 arm64 && compatible "samsung,exynos-sysmmu"）。
   - probe 失败回滚：`err_dma_set_mask:` 处补 `pm_runtime_disable(dev); if (dma_dev==dev) dma_dev=NULL;`
   - 由 `core_initcall` 改为 `module_init/module_exit`。
2. `drivers/iommu/Kconfig`：`EXYNOS_IOMMU` 由 `bool` 改 `tristate`。
3. `drivers/clk/samsung/clk-exynos7.c`：新增 4 个 DISP SYSMMU 门控
   （`CLK_ACLK_DISP_RO_SYSMMU`/`..RW`/`CLK_PCLK_DISP_RO_SYSMMU`/`..RW`，
   CMU_DISP 块 `0x0804/0x0808/0x0904/0x0908` bit0）；目前这 4 个门与 `top_aclk_disp_400`
   挂着 `CLK_IS_CRITICAL`（原厂是 0，待定）。
4. `include/dt-bindings/clock/exynos7-clk.h`：新增 4 个 ID（12–15），`DISP_NR_CLK=16`。
5. `arch/arm64/boot/dts/exynos/exynos7.dtsi`：
   - 新增 `sysmmu_disp_ro@13a00000`(SPI 176)、`sysmmu_disp_rw@13a10000`(SPI 179)，
     `compatible="samsung,exynos-sysmmu"`、`#iommu-cells=<0>`、`power-domains=<&pd_disp>`、clocks/clock-names(aclk/pclk)。
   - DECON 加 `iommus = <&sysmmu_disp_ro>, <&sysmmu_disp_rw>`。
   - `pd_disp` 改为 `power-domain@105c4080` + `compatible="samsung,exynos7420-pd"`。
6. `drivers/pmdomain/samsung/exynos-pm-domains.c`：新增 `samsung,exynos7420-pd` 匹配 +
   DISP pre/post 上下电序列（见上）。

## 四、现象

- **模块（=m）**：开机正常进桌面（DECON probe 时 IOMMU 模块未加载 →
  `iommu_get_domain_for_dev()` 返回 NULL → `priv->mapping=NULL` → 不用 IOMMU，显示正常）。
  运行期 `insmod exynos-iommu.ko` → 两个 SYSMMU 成功 bind
  （`/sys/bus/platform/drivers/exynos-sysmmu/` 出现两设备），串口不阻塞。
  但 DECON 早已 probe 完，`exynos_drm_register_dma()` 只在 probe 跑一次，不会重新挂 IOMMU → GPU 加速仍不生效。
- **内建（=y）**：开机卡在 bootloader logo（已试两版：早期无 .owner/无静态版本；以及已有 .owner+静态版本），
  串口疑似也不通（未最终确认是否只是 DECON deferred probe 导致黑/停 logo，而内核其实活着）。

## 五、原厂对比（/Volumes/kernel_build/kernel，3.10.61）

- `sysmmu_disp_ro/rw` 节点：**没有 power-domains**，只有 clocks/clock-names(aclk/pclk)；
  另有 `qos`、`sysmmu,block-when-stop`、`pb-info`。
- probe（`drivers/iommu/exynos-iommu-v6.c:1722`）：不读版本寄存器；时钟只 `clk_prepare()`（不 enable）；
  `pm_runtime_enable()`；无电源域操作。
- 时钟：DISP SYSMMU 门 flags=0（非 critical）；父时钟是 `usermux_aclk_disp_400`
  （USERMUX，父 `top_aclk_disp_400`）；DECON 的 `aclk_decon_ext` 同样挂 `usermux_aclk_disp_400`。
- 原厂另有 `domain-clients = <&decon_0>, <&decon_1>, <&vg_0>...` 的 IOMMU domain 概念。

## 六、请逐条分析并给出方案

1. **内建（=y）为什么会在 core_initcall 阶段卡死整机？**
   mainline 6.6 `bus_set_iommu(&platform_bus_type, &exynos_iommu_ops)` → `iommu_bus_init()`
   → `bus_for_each_dev(bus, NULL, NULL, iommu_probe_device)` 会立刻对所有 platform 设备做 IOMMU 探测（含 DECON/SYSMMU）。
   请指出这条路径上**哪些点真正访问 SYSMMU/DECON 硬件**（`exynos_iommu_of_xlate`、`iommu_probe_device`、
   `exynos_iommu_attach_device`、`__sysmmu_enable`、默认 domain 创建…），以及为何此时时钟/电源域尚未就绪。
   给出最小、干净的修法（让 IOMMU 探测延后到显示子系统起来之后 / 让 DECON 的 attach 延后 /
   用 DT 依赖让内核自动排序 等）。
2. **是否应像原厂那样去掉 SYSMMU 节点的 `power-domains`？**
   加了 `<&pd_disp>` 后，probe 失败时 genpd 会 `genpd_queue_power_off_work()` 把 DECON 正在用的 DISP 域断电
   （`0x105c4080` 写 0）→ DECON AXI 读事务卡死 → 整机雪崩。请确认机制并给出正确做法
   （去掉 power-domains？还是把 DECON 也放进同域让 genpd 计数正确？）。
3. **内建卡 logo 会不会其实不是内核挂死，而是 DECON 因 `iommus` 依赖 IOMMU 而 `-EPROBE_DEFER`，
   加上我们的 cmdline 有 `deferred_probe_timeout=0`，导致 DECON 永不 probe、屏幕停在 logo，而内核/串口其实活着？**
   如何验证与修（去掉 `deferred_probe_timeout=0`？）。
4. **若内建始终不可行，模块（=m）+ 开机服务方案**：DECON probe 完之后加载 `exynos-iommu.ko`，
   再让 DECON 重新 probe 一次挂上 IOMMU（rmmod/insmod exynosdrm，或写一个小 platform driver 晚些触发
   `exynos_drm_register_dma()`）。请评估可行性、竞态与更优雅的替代（把 `exynos_drm_register_dma()` 改成可延迟/可重入？）。

## 七、期望输出

- 对第六节 4 个问题的逐条分析（指名具体函数/行号/机制）。
- 一份**最小改动 patch 清单**（文件 + 具体改法），目标：开机即让 DECON 经 IOMMU 做 DMA 映射，
  `exynos_drm_gem` 不再报 `buffer chunks must be mapped contiguously`，GNOME 硬件加速合成正常。
- 需要我补充抓取的证据清单（dmesg/寄存器/DT 等）。

## 八、可提供的额外证据（如需请说明要哪一项）

- 完整 dmesg（模块版开机 + 运行期 insmod 前后）。
- `exynos_sysmmu_probe` 反汇编。
- 我们 DTS 中 sysmmu/decon/pd_disp 节点的完整内容。
- 原厂 `exynos-iommu-v6.c` 相关函数全文。
- 时钟树 `clk_summary`。
