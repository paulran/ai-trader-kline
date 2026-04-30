let mainChart, volumeChart, indicatorChart;
let candlestickSeries, volumeSeries;
let indicatorSeriesMap = {};
let currentData = [];
let currentSignals = [];
let currentIndicators = {};
let visibleIndicators = {};
let tooltipVisible = false;
let currentTooltipContent = '';
let signalPopupVisible = false;
let currentDataTimeMin = 0;
let currentDataTimeMax = 0;
let isLoadingData = false;
let lastHoveredSignalTime = null;

const chartColors = {
    up: '#4ade80',
    down: '#f87171',
    SMA5: '#ffd700',
    SMA10: '#ff69b4',
    SMA20: '#00bfff',
    SMA60: '#ff4500',
    EMA12: '#9370db',
    EMA26: '#20b2aa',
    BBUpper: '#ff6b6b',
    BBMiddle: '#ffd93d',
    BBLower: '#6bcb77',
    RSI: '#ff69b4',
    MACD: '#00bfff',
    MACDSignal: '#ff6b6b',
    MACDHist: '#4ade80'
};

function calculateSMA(data, window) {
    const result = [];
    for (let i = 0; i < data.length; i++) {
        if (i < window - 1) {
            result.push(null);
        } else {
            let sum = 0;
            for (let j = 0; j < window; j++) {
                sum += data[i - j];
            }
            result.push(sum / window);
        }
    }
    return result;
}

function calculateEMA(data, span) {
    const result = [];
    const multiplier = 2 / (span + 1);
    let ema = data[0];
    result[0] = ema;
    
    for (let i = 1; i < data.length; i++) {
        ema = (data[i] - ema) * multiplier + ema;
        result.push(ema);
    }
    return result;
}

function calculateRSI(closePrices, period = 14) {
    const result = [];
    const deltas = [];
    
    for (let i = 1; i < closePrices.length; i++) {
        deltas.push(closePrices[i] - closePrices[i - 1]);
    }
    
    for (let i = 0; i < closePrices.length; i++) {
        if (i < period) {
            result.push(null);
        } else {
            let gains = 0;
            let losses = 0;
            
            for (let j = i - period + 1; j <= i; j++) {
                const delta = closePrices[j] - closePrices[j - 1];
                if (delta > 0) {
                    gains += delta;
                } else if (delta < 0) {
                    losses += Math.abs(delta);
                }
            }
            
            if (losses === 0) {
                result.push(100);
            } else if (gains === 0) {
                result.push(0);
            } else {
                const rs = (gains / period) / (losses / period);
                const rsi = 100 - (100 / (1 + rs));
                result.push(rsi);
            }
        }
    }
    return result;
}

function calculateMACD(closePrices, fastPeriod = 12, slowPeriod = 26, signalPeriod = 9) {
    const emaFast = calculateEMA(closePrices, fastPeriod);
    const emaSlow = calculateEMA(closePrices, slowPeriod);
    
    const macd = [];
    for (let i = 0; i < closePrices.length; i++) {
        if (i < slowPeriod - 1) {
            macd.push(null);
        } else {
            macd.push(emaFast[i] - emaSlow[i]);
        }
    }
    
    const validMacd = [];
    const validIndices = [];
    for (let i = 0; i < macd.length; i++) {
        if (macd[i] !== null) {
            validMacd.push(macd[i]);
            validIndices.push(i);
        }
    }
    
    const signal = [];
    if (validMacd.length > 0) {
        const emaSignal = calculateEMA(validMacd, signalPeriod);
        let signalIdx = 0;
        for (let i = 0; i < macd.length; i++) {
            if (signalIdx < validIndices.length && i === validIndices[signalIdx]) {
                signal.push(emaSignal[signalIdx]);
                signalIdx++;
            } else {
                signal.push(null);
            }
        }
    } else {
        for (let i = 0; i < macd.length; i++) {
            signal.push(null);
        }
    }
    
    const hist = [];
    for (let i = 0; i < macd.length; i++) {
        if (macd[i] !== null && signal[i] !== null) {
            hist.push(macd[i] - signal[i]);
        } else {
            hist.push(null);
        }
    }
    
    return {
        MACD: macd,
        MACD_signal: signal,
        MACD_hist: hist,
        EMA_12: emaFast,
        EMA_26: emaSlow
    };
}

function calculateBollingerBands(closePrices, window = 20, stdDev = 2) {
    const sma = calculateSMA(closePrices, window);
    const upper = [];
    const lower = [];
    
    for (let i = 0; i < closePrices.length; i++) {
        if (i < window - 1) {
            upper.push(null);
            lower.push(null);
        } else {
            let sum = 0;
            for (let j = 0; j < window; j++) {
                sum += closePrices[i - j];
            }
            const mean = sum / window;
            
            let variance = 0;
            for (let j = 0; j < window; j++) {
                variance += Math.pow(closePrices[i - j] - mean, 2);
            }
            variance = variance / window;
            const std = Math.sqrt(variance);
            
            upper.push(mean + stdDev * std);
            lower.push(mean - stdDev * std);
        }
    }
    
    return {
        BB_upper: upper,
        BB_middle: sma,
        BB_lower: lower
    };
}

function calculateAllIndicators(data) {
    if (!data || data.length === 0) {
        return {};
    }
    
    const closePrices = data.map(d => d.close);
    
    const sma5 = calculateSMA(closePrices, 5);
    const sma10 = calculateSMA(closePrices, 10);
    const sma20 = calculateSMA(closePrices, 20);
    const sma60 = calculateSMA(closePrices, 60);
    
    const macdResult = calculateMACD(closePrices);
    const rsi = calculateRSI(closePrices, 14);
    const bbResult = calculateBollingerBands(closePrices, 20, 2);
    
    return {
        SMA_5: sma5,
        SMA_10: sma10,
        SMA_20: sma20,
        SMA_60: sma60,
        EMA_12: macdResult.EMA_12,
        EMA_26: macdResult.EMA_26,
        RSI: rsi,
        MACD: macdResult.MACD,
        MACD_signal: macdResult.MACD_signal,
        MACD_hist: macdResult.MACD_hist,
        BB_upper: bbResult.BB_upper,
        BB_middle: bbResult.BB_middle,
        BB_lower: bbResult.BB_lower
    };
}

function showError(message) {
    const errorEl = document.getElementById('errorMessage');
    errorEl.textContent = message;
    errorEl.style.display = 'block';
    setTimeout(() => {
        errorEl.style.display = 'none';
    }, 5000);
}

function parseURLParams() {
    const params = new URLSearchParams(window.location.search);
    return {
        exchange: params.get('exchange') || 'OKX',
        type: params.get('type') || 'SPOT',
        symbol: params.get('symbol') || 'BTC-USDT',
        period: params.get('period') || '1m',
        start_time: params.get('start_time') || '',
        end_time: params.get('end_time') || ''
    };
}

function formatTime(timestamp) {
    const date = new Date(timestamp * 1000);
    return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function initCharts() {
    const mainChartEl = document.getElementById('mainChart');
    const volumeChartEl = document.getElementById('volumeChart');
    const indicatorChartEl = document.getElementById('indicatorChart');

    try {
        mainChart = LightweightCharts.createChart(mainChartEl, {
            layout: {
                background: { type: 'solid', color: '#1a1a2e' },
                textColor: '#aaa'
            },
            grid: {
                vertLines: { color: '#16213e' },
                horzLines: { color: '#16213e' }
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal
            },
            rightPriceScale: {
                borderColor: '#0f3460'
            },
            timeScale: {
                borderColor: '#0f3460',
                timeVisible: true,
                secondsVisible: false
            },
            handleScroll: true,
            handleScale: true
        });

        volumeChart = LightweightCharts.createChart(volumeChartEl, {
            layout: {
                background: { type: 'solid', color: '#1a1a2e' },
                textColor: '#aaa'
            },
            grid: {
                vertLines: { color: '#16213e' },
                horzLines: { color: '#16213e' }
            },
            rightPriceScale: {
                borderColor: '#0f3460'
            },
            timeScale: {
                visible: false
            },
            handleScroll: true,
            handleScale: true
        });

        indicatorChart = LightweightCharts.createChart(indicatorChartEl, {
            layout: {
                background: { type: 'solid', color: '#1a1a2e' },
                textColor: '#aaa'
            },
            grid: {
                vertLines: { color: '#16213e' },
                horzLines: { color: '#16213e' }
            },
            rightPriceScale: {
                borderColor: '#0f3460'
            },
            timeScale: {
                visible: false
            },
            handleScroll: true,
            handleScale: true
        });

        candlestickSeries = mainChart.addCandlestickSeries({
            upColor: chartColors.up,
            downColor: chartColors.down,
            borderUpColor: chartColors.up,
            borderDownColor: chartColors.down,
            wickUpColor: chartColors.up,
            wickDownColor: chartColors.down
        });

        volumeSeries = volumeChart.addHistogramSeries({
            priceFormat: {
                type: 'volume'
            }
        });

        mainChart.timeScale().subscribeVisibleTimeRangeChange(onTimeRangeChanged);

        const resizeObserver = new ResizeObserver(() => {
            mainChart.applyOptions({ width: mainChartEl.clientWidth, height: mainChartEl.clientHeight });
            volumeChart.applyOptions({ width: volumeChartEl.clientWidth, height: volumeChartEl.clientHeight });
            indicatorChart.applyOptions({ width: indicatorChartEl.clientWidth, height: indicatorChartEl.clientHeight });
        });

        resizeObserver.observe(mainChartEl);
        resizeObserver.observe(volumeChartEl);
        resizeObserver.observe(indicatorChartEl);

        mainChart.subscribeCrosshairMove(onCrosshairMove);

        console.log('图表初始化成功');
    } catch (error) {
        console.error('图表初始化失败:', error);
        showError('图表初始化失败: ' + error.message);
    }
}

let lastLoadTime = 0;
const LOAD_COOLDOWN = 500;

function onTimeRangeChanged() {
    try {
        const timeRange = mainChart.timeScale().getVisibleRange();
        if (timeRange) {
            volumeChart.timeScale().setVisibleRange(timeRange);
            indicatorChart.timeScale().setVisibleRange(timeRange);
        }

        if (currentData.length > 0 && !isLoadingData) {
            const now = Date.now();
            if (now - lastLoadTime < LOAD_COOLDOWN) {
                return;
            }

            const visibleFrom = timeRange.from;
            const visibleTo = timeRange.to;

            const dataThreshold = 10;
            const firstDataTime = currentData[0].time;
            const lastDataTime = currentData[currentData.length - 1].time;

            let needLoadBefore = false;
            let needLoadAfter = false;

            if (visibleFrom <= firstDataTime + dataThreshold * 60) {
                needLoadBefore = true;
            }
            if (visibleTo >= lastDataTime - dataThreshold * 60) {
                needLoadAfter = true;
            }

            if (needLoadBefore || needLoadAfter) {
                loadMoreData(needLoadBefore, needLoadAfter);
            }
        }
    } catch (e) {
    }
}

async function loadMoreData(loadBefore, loadAfter) {
    if (isLoadingData || currentData.length === 0) {
        return;
    }

    isLoadingData = true;
    lastLoadTime = Date.now();

    const exchange = document.getElementById('exchange').value;
    const instType = document.getElementById('instType').value;
    const symbol = document.getElementById('symbol').value;
    const period = document.getElementById('period').value;

    const firstDataTime = currentData[0].time;
    const lastDataTime = currentData[currentData.length - 1].time;

    let url = `/api/klines?exchange=${exchange}&type=${instType}&symbol=${encodeURIComponent(symbol)}&period=${period}`;

    if (loadBefore) {
        const beforeTime = firstDataTime - 24 * 60 * 60;
        url += `&end_time=${firstDataTime - 1}&start_time=${beforeTime}`;
    } else if (loadAfter) {
        const afterTime = lastDataTime + 24 * 60 * 60;
        url += `&start_time=${lastDataTime + 1}&end_time=${afterTime}`;
    }

    try {
        console.log('请求更多数据:', url);
        const response = await fetch(url);

        if (!response.ok) {
            throw new Error(`HTTP错误: ${response.status}`);
        }

        const result = await response.json();

        if (result.success && result.data && result.data.length > 0) {
            const newData = result.data;
            const newSignals = result.signals || [];

            let mergedData = [...currentData];
            let mergedSignals = [...currentSignals];

            if (loadBefore) {
                const existingTimes = new Set(currentData.map(d => d.time));
                const newDataToAdd = newData.filter(d => !existingTimes.has(d.time));
                mergedData = [...newDataToAdd, ...currentData];
            } else {
                const existingTimes = new Set(currentData.map(d => d.time));
                const newDataToAdd = newData.filter(d => !existingTimes.has(d.time));
                mergedData = [...currentData, ...newDataToAdd];
            }

            const existingSignalTimes = new Set(currentSignals.map(s => s.time));
            const newSignalsToAdd = newSignals.filter(s => !existingSignalTimes.has(s.time));
            mergedSignals = [...currentSignals, ...newSignalsToAdd];

            mergedData.sort((a, b) => a.time - b.time);
            mergedSignals.sort((a, b) => a.time - b.time);

            currentData = mergedData;
            currentSignals = mergedSignals;
            currentIndicators = calculateAllIndicators(currentData);

            if (currentData.length > 0) {
                currentDataTimeMin = currentData[0].time;
                currentDataTimeMax = currentData[currentData.length - 1].time;
            }

            candlestickSeries.setData(currentData);

            const volumeData = currentData.map(d => ({
                time: d.time,
                value: d.volume,
                color: d.close >= d.open ? chartColors.up : chartColors.down
            }));
            volumeSeries.setData(volumeData);

            createSignalMarkers();

            updateMainChartIndicators();
            updateIndicators();

            console.log('已合并更多数据，总数据量:', currentData.length);
            document.getElementById('dataInfo').textContent = 
                `数据: ${exchange} | ${symbol} | ${period} | ${currentData.length} 条K线 | ${currentSignals.length} 个信号`;
        }
    } catch (error) {
        console.error('加载更多数据失败:', error);
    } finally {
        isLoadingData = false;
    }
}

function hideTooltip() {
    const tooltip = document.getElementById('tooltip');
    tooltip.style.display = 'none';
    tooltipVisible = false;
    currentTooltipContent = '';
}

function hideSignalPopup() {
    const popup = document.getElementById('signalPopup');
    popup.style.display = 'none';
    signalPopupVisible = false;
}

function showTooltip(content, x, y) {
    const tooltip = document.getElementById('tooltip');

    const chartRect = document.getElementById('mainChart').getBoundingClientRect();
    let left = x + 15;
    let top = y + 15;

    if (left + 280 > window.innerWidth) {
        left = x - 295;
    }
    if (top + 200 > window.innerHeight) {
        top = y - 215;
    }

    if (left < 10) left = 10;
    if (top < 10) top = 10;

    if (content === currentTooltipContent && tooltipVisible) {
        tooltip.style.left = left + 'px';
        tooltip.style.top = top + 'px';
        return;
    }

    currentTooltipContent = content;
    tooltip.innerHTML = content;
    tooltip.style.display = 'block';
    tooltipVisible = true;
    tooltip.style.left = left + 'px';
    tooltip.style.top = top + 'px';
}

function showSignalPopup(signal, x, y) {
    const popup = document.getElementById('signalPopup');
    const isBuy = signal.action_name === 'Buy';

    popup.className = 'signal-popup ' + (isBuy ? 'buy' : 'sell');

    let html = `
        <div class="title">
            ${isBuy ? '▲ 买入信号' : '▼ 卖出信号'}
        </div>
        <div class="row">
            <span class="label">时间:</span>
            <span class="value">${formatTime(signal.time)}</span>
        </div>
        <div class="row">
            <span class="label">置信度:</span>
            <span class="value">${(signal.confidence * 100).toFixed(2)}%</span>
        </div>
    `;

    if (signal.remark) {
        html += `
            <div class="remark-box">
                <div class="remark-label">📝 备注信息</div>
                <div class="remark-text">${signal.remark}</div>
            </div>
        `;
    }

    popup.innerHTML = html;
    popup.style.display = 'block';
    signalPopupVisible = true;

    const chartRect = document.getElementById('mainChart').getBoundingClientRect();
    let left = x + 20;
    let top = y - 10;

    if (left + 280 > window.innerWidth) {
        left = x - 320;
    }

    popup.style.left = left + 'px';
    popup.style.top = top + 'px';
}

function onCrosshairMove(param) {
    if (!param.time || !param.point) {
        hideTooltip();
        hideSignalPopup();
        return;
    }

    const klineData = currentData.find(d => d.time === param.time);
    if (!klineData) {
        hideTooltip();
        hideSignalPopup();
        return;
    }

    const signal = currentSignals.find(s => s.time === param.time);

    let tooltipHtml = `
        <div class="title">${formatTime(param.time)}</div>
        <div class="row">
            <span class="label">开盘:</span>
            <span class="value">${klineData.open.toFixed(2)}</span>
        </div>
        <div class="row">
            <span class="label">最高:</span>
            <span class="value">${klineData.high.toFixed(2)}</span>
        </div>
        <div class="row">
            <span class="label">最低:</span>
            <span class="value">${klineData.low.toFixed(2)}</span>
        </div>
        <div class="row">
            <span class="label">收盘:</span>
            <span class="value">${klineData.close.toFixed(2)}</span>
        </div>
        <div class="row">
            <span class="label">成交量:</span>
            <span class="value">${klineData.volume.toFixed(2)}</span>
        </div>
    `;

    if (signal) {
        const actionClass = signal.action_name === 'Buy' ? 'buy' : 'sell';
        const actionText = signal.action_name === 'Buy' ? '买入' : '卖出';
        tooltipHtml += `
            <div class="row">
                <span class="label">信号:</span>
                <span class="value ${actionClass}">${actionText}</span>
            </div>
            <div class="row">
                <span class="label">置信度:</span>
                <span class="value">${(signal.confidence * 100).toFixed(2)}%</span>
            </div>
        `;

        if (signal.remark) {
            tooltipHtml += `
                <div class="remark-box">
                    <div class="remark-label">📝 备注</div>
                    <div class="remark-text">${signal.remark}</div>
                </div>
            `;
        }
    }

    const chartRect = document.getElementById('mainChart').getBoundingClientRect();
    const x = chartRect.left + param.point.x;
    const y = chartRect.top + param.point.y;

    showTooltip(tooltipHtml, x, y);
}

function createIndicatorSeries(type) {
    if (indicatorSeriesMap[type]) {
        return indicatorSeriesMap[type];
    }

    const series = {};

    switch(type) {
        case 'RSI':
            series.RSI = indicatorChart.addLineSeries({
                color: chartColors.RSI,
                lineWidth: 1
            });
            break;

        case 'MACD':
            series.MACD = indicatorChart.addLineSeries({
                color: chartColors.MACD,
                lineWidth: 1
            });
            series.MACDSignal = indicatorChart.addLineSeries({
                color: chartColors.MACDSignal,
                lineWidth: 1
            });
            series.MACDHist = indicatorChart.addHistogramSeries({});
            break;
    }

    indicatorSeriesMap[type] = series;
    return series;
}

function updateIndicators() {
    for (const key in indicatorSeriesMap) {
        const series = indicatorSeriesMap[key];
        for (const s in series) {
            try {
                indicatorChart.removeSeries(series[s]);
            } catch(e) {}
        }
    }
    indicatorSeriesMap = {};

    const showRSI = document.getElementById('showRSI').checked;
    const showMACD = document.getElementById('showMACD').checked;
    const indicatorChartEl = document.getElementById('indicatorChart');

    if (showRSI || showMACD) {
        indicatorChartEl.style.display = 'block';
    } else {
        indicatorChartEl.style.display = 'none';
        return;
    }

    const timeData = currentData.map(d => d.time);

    if (showRSI && currentIndicators.RSI) {
        const series = createIndicatorSeries('RSI');
        const rsiData = [];
        const rsiValues = currentIndicators.RSI;

        for (let i = 0; i < timeData.length; i++) {
            if (rsiValues[i] !== null && rsiValues[i] !== undefined) {
                rsiData.push({
                    time: timeData[i],
                    value: rsiValues[i]
                });
            }
        }
        series.RSI.setData(rsiData);
    }

    if (showMACD && currentIndicators.MACD) {
        const series = createIndicatorSeries('MACD');
        const macdData = [];
        const signalData = [];
        const histData = [];

        const macdValues = currentIndicators.MACD;
        const signalValues = currentIndicators.MACD_signal;
        const histValues = currentIndicators.MACD_hist;

        for (let i = 0; i < timeData.length; i++) {
            if (macdValues[i] !== null && macdValues[i] !== undefined) {
                macdData.push({
                    time: timeData[i],
                    value: macdValues[i]
                });
            }
            if (signalValues[i] !== null && signalValues[i] !== undefined) {
                signalData.push({
                    time: timeData[i],
                    value: signalValues[i]
                });
            }
            if (histValues[i] !== null && histValues[i] !== undefined) {
                histData.push({
                    time: timeData[i],
                    value: histValues[i],
                    color: histValues[i] >= 0 ? chartColors.up : chartColors.down
                });
            }
        }

        series.MACD.setData(macdData);
        series.MACDSignal.setData(signalData);
        series.MACDHist.setData(histData);
    }
}

function updateMainChartIndicators() {
    for (const key in visibleIndicators) {
        if (visibleIndicators[key] && mainChart) {
            try {
                mainChart.removeSeries(visibleIndicators[key]);
            } catch(e) {}
        }
    }
    visibleIndicators = {};

    const showSMA5 = document.getElementById('showSMA5').checked;
    const showSMA10 = document.getElementById('showSMA10').checked;
    const showSMA20 = document.getElementById('showSMA20').checked;
    const showSMA60 = document.getElementById('showSMA60').checked;
    const showEMA12 = document.getElementById('showEMA12').checked;
    const showEMA26 = document.getElementById('showEMA26').checked;
    const showBB = document.getElementById('showBB').checked;

    const timeData = currentData.map(d => d.time);

    const indicatorConfigs = [
        { id: 'SMA5', show: showSMA5, data: currentIndicators.SMA_5, color: chartColors.SMA5 },
        { id: 'SMA10', show: showSMA10, data: currentIndicators.SMA_10, color: chartColors.SMA10 },
        { id: 'SMA20', show: showSMA20, data: currentIndicators.SMA_20, color: chartColors.SMA20 },
        { id: 'SMA60', show: showSMA60, data: currentIndicators.SMA_60, color: chartColors.SMA60 },
        { id: 'EMA12', show: showEMA12, data: currentIndicators.EMA_12, color: chartColors.EMA12 },
        { id: 'EMA26', show: showEMA26, data: currentIndicators.EMA_26, color: chartColors.EMA26 }
    ];

    indicatorConfigs.forEach(config => {
        if (config.show && config.data) {
            const series = mainChart.addLineSeries({
                color: config.color,
                lineWidth: 1,
                priceLineVisible: false,
                lastValueVisible: false
            });

            const data = [];
            for (let i = 0; i < timeData.length; i++) {
                if (config.data[i] !== null && config.data[i] !== undefined) {
                    data.push({
                        time: timeData[i],
                        value: config.data[i]
                    });
                }
            }
            series.setData(data);
            visibleIndicators[config.id] = series;
        }
    });

    if (showBB && currentIndicators.BB_upper && currentIndicators.BB_middle && currentIndicators.BB_lower) {
        const upperSeries = mainChart.addLineSeries({
            color: chartColors.BBUpper,
            lineWidth: 1,
            priceLineVisible: false,
            lastValueVisible: false
        });
        const middleSeries = mainChart.addLineSeries({
            color: chartColors.BBMiddle,
            lineWidth: 1,
            priceLineVisible: false,
            lastValueVisible: false
        });
        const lowerSeries = mainChart.addLineSeries({
            color: chartColors.BBLower,
            lineWidth: 1,
            priceLineVisible: false,
            lastValueVisible: false
        });

        const upperData = [];
        const middleData = [];
        const lowerData = [];

        for (let i = 0; i < timeData.length; i++) {
            if (currentIndicators.BB_upper[i] !== null && currentIndicators.BB_upper[i] !== undefined) {
                upperData.push({ time: timeData[i], value: currentIndicators.BB_upper[i] });
                middleData.push({ time: timeData[i], value: currentIndicators.BB_middle[i] });
                lowerData.push({ time: timeData[i], value: currentIndicators.BB_lower[i] });
            }
        }

        upperSeries.setData(upperData);
        middleSeries.setData(middleData);
        lowerSeries.setData(lowerData);

        visibleIndicators['BBUpper'] = upperSeries;
        visibleIndicators['BBMiddle'] = middleSeries;
        visibleIndicators['BBLower'] = lowerSeries;
    }
}

function createSignalMarkers() {
    if (!candlestickSeries || currentSignals.length === 0) {
        document.getElementById('legendBox').style.display = 'none';
        return;
    }

    const markers = [];
    const klineMap = new Map();

    currentData.forEach((kline, index) => {
        klineMap.set(kline.time, {
            index: index,
            low: kline.low,
            high: kline.high,
            open: kline.open,
            close: kline.close
        });
    });

    currentSignals.forEach(signal => {
        const klineInfo = klineMap.get(signal.time);
        if (!klineInfo) return;

        const isBuy = signal.action_name === 'Buy';

        let position;
        if (isBuy) {
            position = 'belowBar';
        } else {
            position = 'aboveBar';
        }

        const marker = {
            time: signal.time,
            position: position,
            color: isBuy ? chartColors.up : chartColors.down,
            shape: isBuy ? 'arrowUp' : 'arrowDown',
            text: isBuy ? '买' : '卖',
            size: 2
        };

        markers.push(marker);
    });

    if (markers.length > 0) {
        candlestickSeries.setMarkers(markers);
        document.getElementById('legendBox').style.display = 'block';
        console.log(`已设置 ${markers.length} 个信号标记`);
    } else {
        candlestickSeries.setMarkers([]);
        document.getElementById('legendBox').style.display = 'none';
    }
}

async function loadData() {
    const exchange = document.getElementById('exchange').value;
    const instType = document.getElementById('instType').value;
    const symbol = document.getElementById('symbol').value;
    const period = document.getElementById('period').value;
    const startTime = document.getElementById('startTime').value;
    const endTime = document.getElementById('endTime').value;

    document.getElementById('status').textContent = '加载中...';
    document.getElementById('status').style.color = '#ffd700';

    let url = `/api/klines?exchange=${exchange}&type=${instType}&symbol=${encodeURIComponent(symbol)}&period=${period}`;
    if (startTime) url += `&start_time=${startTime}`;
    if (endTime) url += `&end_time=${endTime}`;

    const newParams = new URLSearchParams();
    newParams.set('exchange', exchange);
    newParams.set('type', instType);
    newParams.set('symbol', symbol);
    newParams.set('period', period);
    if (startTime) newParams.set('start_time', startTime);
    if (endTime) newParams.set('end_time', endTime);

    window.history.replaceState({}, '', `${window.location.pathname}?${newParams.toString()}`);

    try {
        console.log('请求URL:', url);
        const response = await fetch(url);

        if (!response.ok) {
            throw new Error(`HTTP错误: ${response.status}`);
        }

        const result = await response.json();
        console.log('API返回:', result);

        if (!result.success) {
            document.getElementById('status').textContent = '加载失败';
            document.getElementById('status').style.color = '#f87171';
            document.getElementById('dataInfo').textContent = result.message || '未找到数据';
            showError(result.message || '未找到数据');
            return;
        }

        currentData = result.data;
        currentSignals = result.signals;
        currentIndicators = calculateAllIndicators(currentData);

        if (currentData.length > 0) {
            currentDataTimeMin = currentData[0].time;
            currentDataTimeMax = currentData[currentData.length - 1].time;
        }

        console.log('K线数据数量:', currentData.length);
        console.log('信号数量:', currentSignals.length);
        console.log('时间范围:', new Date(currentDataTimeMin * 1000).toLocaleString(), '-', new Date(currentDataTimeMax * 1000).toLocaleString());

        if (currentData.length === 0) {
            document.getElementById('status').textContent = '无数据';
            document.getElementById('status').style.color = '#f87171';
            document.getElementById('dataInfo').textContent = '没有找到K线数据';
            showError('没有找到K线数据，请检查参数是否正确');
            return;
        }

        candlestickSeries.setData(currentData);

        const volumeData = currentData.map(d => ({
            time: d.time,
            value: d.volume,
            color: d.close >= d.open ? chartColors.up : chartColors.down
        }));
        volumeSeries.setData(volumeData);

        createSignalMarkers();

        updateMainChartIndicators();
        updateIndicators();

        if (currentData.length > 0) {
            mainChart.timeScale().fitContent();
            volumeChart.timeScale().fitContent();
            indicatorChart.timeScale().fitContent();
        }

        document.getElementById('dataInfo').textContent = 
            `数据: ${result.metadata.exchange} | ${result.metadata.symbol} | ${result.metadata.period} | ${result.metadata.count} 条K线 | ${result.signals.length} 个信号`;

        document.getElementById('status').textContent = '加载完成';
        document.getElementById('status').style.color = '#4ade80';

    } catch (error) {
        console.error('加载数据失败:', error);
        document.getElementById('status').textContent = '加载错误';
        document.getElementById('status').style.color = '#f87171';
        showError('加载数据失败: ' + error.message);
    }
}

function bindEvents() {
    document.getElementById('loadBtn').addEventListener('click', (e) => {
        console.log('点击加载按钮');
        loadData();
    });

    document.querySelectorAll('.indicator-toggle').forEach(el => {
        el.addEventListener('change', () => {
            updateMainChartIndicators();
            updateIndicators();
        });
    });

    document.querySelectorAll('#exchange, #instType, #symbol, #period, #startTime, #endTime').forEach(el => {
        el.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                loadData();
            }
        });
    });
}

function init() {
    console.log('页面初始化...');
    console.log('LightweightCharts可用:', typeof LightweightCharts);

    const params = parseURLParams();

    document.getElementById('exchange').value = params.exchange;
    document.getElementById('instType').value = params.type;
    document.getElementById('symbol').value = params.symbol;
    document.getElementById('period').value = params.period;

    if (params.start_time) {
        document.getElementById('startTime').value = params.start_time;
    }
    if (params.end_time) {
        document.getElementById('endTime').value = params.end_time;
    }

    bindEvents();
    initCharts();
    loadData();
}

window.addEventListener('DOMContentLoaded', init);