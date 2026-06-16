import React, { useEffect, useRef } from 'react';
import { createChart, ColorType, CandlestickSeries, HistogramSeries } from 'lightweight-charts';
import type { IChartApi } from 'lightweight-charts';

interface ChartData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  value?: number; // for volume
}

interface TradingViewChartProps {
  data: ChartData[];
  width?: number | string;
  height?: number;
  colors?: {
    backgroundColor?: string;
    textColor?: string;
    upColor?: string;
    downColor?: string;
  };
}

export function TradingViewChart({
  data,
  width = '100%',
  height = 400,
  colors = {
    backgroundColor: 'transparent',
    textColor: '#9ca3af',
    upColor: '#10b981',
    downColor: '#ef4444',
  }
}: TradingViewChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;
    setError(null);

    let chartInstance: IChartApi | null = null;
    try {
      // Create chart
      const chart = createChart(chartContainerRef.current, {
        autoSize: true,
        layout: {
          background: { type: ColorType.Solid, color: colors.backgroundColor || 'transparent' },
          textColor: colors.textColor,
        },
        grid: {
          vertLines: { color: 'rgba(255, 255, 255, 0.05)' },
          horzLines: { color: 'rgba(255, 255, 255, 0.05)' },
        },
        height: height,
        timeScale: {
          timeVisible: true,
          borderColor: 'rgba(255, 255, 255, 0.1)',
        },
        rightPriceScale: {
          borderColor: 'rgba(255, 255, 255, 0.1)',
        },
      });

      // Ensure data is sorted by time ascending
      const sortedData = [...data].sort((a, b) => new Date(a.time).getTime() - new Date(b.time).getTime());

      // Remove duplicates by time
      const uniqueData = [];
      const seenTimes = new Set();
      for (const item of sortedData) {
        if (!seenTimes.has(item.time)) {
          seenTimes.add(item.time);
          uniqueData.push(item);
        }
      }

      // Add Candlestick Series
      const candlestickSeries = chart.addSeries(CandlestickSeries, {
        upColor: colors.upColor,
        downColor: colors.downColor,
        borderVisible: false,
        wickUpColor: colors.upColor,
        wickDownColor: colors.downColor,
      });
      const candleData = uniqueData.map(d => ({
        time: d.time,
        open: d.open,
        high: d.high,
        low: d.low,
        close: d.close,
      }));
      candlestickSeries.setData(candleData);

      // Add Volume Series as Histogram
      const volumeSeries = chart.addSeries(HistogramSeries, {
        color: 'rgba(156, 163, 175, 0.5)',
        priceFormat: { type: 'volume' },
        priceScaleId: '', // set as an overlay
      });
      
      // Scale volume down to bottom 20%
      volumeSeries.priceScale().applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
      });
      
      const volumeData = uniqueData.map(d => ({
        time: d.time,
        value: d.value || 0,
        color: d.close >= d.open ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'
      }));
      volumeSeries.setData(volumeData);

      chart.timeScale().fitContent();
      chartInstance = chart;
      chartRef.current = chart;

      return () => {
        chart.remove();
      };
    } catch (e: any) {
      console.error("TradingView Chart Error:", e);
      setError(e.message);
      if (chartInstance) {
        chartInstance.remove();
      }
    }
  }, [data, height, colors]);

  if (error) {
    return <div style={{ color: 'red', padding: '10px', fontFamily: 'monospace', fontSize: '11px' }}>Error: {error}</div>;
  }

  return (
    <div
      ref={chartContainerRef}
      style={{ width, height, position: 'relative' }}
      className="tv-chart-container"
    />
  );
}
