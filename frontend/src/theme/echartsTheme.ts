import { seriesPalette, tokens } from './tokens'

/**
 * ECharts theme overriding every library default color (ECharts' default palette contains
 * purple, which is not allowed).
 */
export const ECHARTS_THEME_NAME = 'backbone'

const axisCommon = {
  axisLine: { lineStyle: { color: tokens.border } },
  axisTick: { lineStyle: { color: tokens.border } },
  axisLabel: { color: tokens.text.secondary, fontSize: 11 },
  splitLine: { lineStyle: { color: tokens.bg.elevated } },
  nameTextStyle: { color: tokens.text.muted, fontSize: 11 },
}

export const echartsTheme = {
  color: [...seriesPalette],
  backgroundColor: 'transparent',
  textStyle: { color: tokens.text.primary, fontFamily: 'Inter, system-ui, sans-serif' },
  title: { textStyle: { color: tokens.text.primary, fontSize: 13, fontWeight: 500 } },
  legend: {
    textStyle: { color: tokens.text.secondary, fontSize: 11 },
    inactiveColor: tokens.text.muted,
  },
  tooltip: {
    backgroundColor: tokens.bg.elevated,
    borderColor: tokens.border,
    textStyle: { color: tokens.text.primary, fontSize: 12 },
    axisPointer: {
      lineStyle: { color: tokens.text.muted },
      crossStyle: { color: tokens.text.muted },
      label: { backgroundColor: tokens.bg.elevated, color: tokens.text.primary },
    },
  },
  categoryAxis: axisCommon,
  valueAxis: axisCommon,
  timeAxis: axisCommon,
  logAxis: axisCommon,
  dataZoom: {
    backgroundColor: tokens.bg.surface,
    borderColor: tokens.border,
    fillerColor: tokens.fill.accentSoft,
    handleStyle: { color: tokens.accent, borderColor: tokens.accent },
    moveHandleStyle: { color: tokens.border },
    dataBackground: {
      lineStyle: { color: tokens.text.muted },
      areaStyle: { color: tokens.bg.elevated },
    },
    selectedDataBackground: {
      lineStyle: { color: tokens.accent },
      areaStyle: { color: tokens.fill.accentMedium },
    },
    textStyle: { color: tokens.text.secondary },
    brushStyle: { color: tokens.fill.accentSoft },
    emphasis: { handleStyle: { color: tokens.accent } },
  },
  visualMap: { textStyle: { color: tokens.text.secondary } },
  radar: {
    axisName: { color: tokens.text.secondary },
    splitLine: { lineStyle: { color: tokens.border } },
    splitArea: { areaStyle: { color: [tokens.bg.surface, tokens.bg.base] } },
    axisLine: { lineStyle: { color: tokens.border } },
  },
  boxplot: { itemStyle: { color: tokens.bg.elevated, borderColor: tokens.accent } },
  markArea: { itemStyle: { color: tokens.fill.negativeBand } },
}
