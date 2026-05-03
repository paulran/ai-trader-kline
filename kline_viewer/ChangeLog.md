## v1.0.1
1. 时序问题解决 ： volumeSeries.setData() 先于 candlestickSeries.setData() 执行，所以当 onTimeRangeChanged 回调被触发时， volumeChart 已经有数据，时间刻度已正确初始化。
2. 空值检查增强 ：
    - mainChart 存在性检查
    - from / to 的 NaN 和 Infinity 检查
    - volumeChart 存在性检查
    - indicatorChart 存在性检查 + indicatorSeriesMap 非空检查

## v1.0.2
1. 原代码使用**时间范围（Time Range）**同步图表。修复方案使用**逻辑范围（Logical Range）**同步图表，这是 Lightweight Charts 的最佳实践。
2. 采用 统一覆盖层 的方案：
    1. 隐藏原有的十字线垂直线 ：在三个图表的配置中添加 crosshair.vertLine.visible: false
    2. 创建统一的覆盖层 ：在 HTML 中添加 crosshairOverlay div，在 CSS 中定义其样式
    3. 在覆盖层中绘制垂直线 ：使用 JavaScript 动态创建垂直线元素
    4. 同步垂直线位置 ：当鼠标在任意图表上移动时，计算鼠标位置相对于图表容器的坐标，更新覆盖层垂直线的位置
-- 3. 不再依赖各图表的 param.time ，而是使用主图表的时间刻度来计算时间点。--
4. 统一价格刻度宽度：为三个图表的 rightPriceScale 添加了 minimumWidth: 80 ，确保它们的价格刻度宽度相同。
5. 确保指标数据包含所有时间点：修改了指标数据的添加逻辑，将条件从 !== null && !== undefined 改为 !== undefined ，这样即使值是 null ，也会被添加到数据中。

