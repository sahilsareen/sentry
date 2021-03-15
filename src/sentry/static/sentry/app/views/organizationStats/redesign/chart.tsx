import React from 'react';
import Color from 'color';
import moment from 'moment';

import BaseChart from 'app/components/charts/baseChart';
import Legend from 'app/components/charts/components/legend';
// import MarkLine from 'app/components/charts/components/markLine';
import Tooltip from 'app/components/charts/components/tooltip';
import xAxis from 'app/components/charts/components/xAxis';
import OptionSelector from 'app/components/charts/optionSelector';
import barSeries from 'app/components/charts/series/barSeries';
// import lineSeries from 'app/components/charts/series/lineSeries';
import {
  ChartContainer,
  ChartControls,
  HeaderTitleLegend,
  InlineContainer,
  SectionValue,
} from 'app/components/charts/styles';
import Panel from 'app/components/panels/panel';
import ChartPalette from 'app/constants/chartPalette';
import {IconCalendar} from 'app/icons';
import {t} from 'app/locale';
import {SelectValue} from 'app/types';
import {formatAbbreviatedNumber} from 'app/utils/formatters';
import theme from 'app/utils/theme';

import {DataCategory} from './types';

// import {GIGABYTE} from 'getsentry/constants';
// import {
//   BillingStat,
//   BillingStats,
//   DataCategory,
//   DetailedSubscription,
// } from 'getsentry/types';
// import {formatReservedWithUnits, formatUsageWithUnits} from 'getsentry/utils/billing';

const COLOR_ERRORS = ChartPalette[4][3];
const COLOR_ERRORS_DROPPED = Color(COLOR_ERRORS).lighten(0.25).string();

const COLOR_TRANSACTIONS = ChartPalette[4][2];
const COLOR_TRANSACTIONS_DROPPED = Color(COLOR_TRANSACTIONS).lighten(0.25).string();

const COLOR_ATTACHMENTS = ChartPalette[4][1];
const COLOR_ATTACHMENTS_DROPPED = Color(COLOR_ATTACHMENTS).lighten(0.5).string();
const COLOR_PROJECTED = theme.gray200;

const chartTypeOptions: SelectValue<string>[] = [
  {
    label: 'Summary',
    value: 'summary',
    disabled: false,
  },
  {
    label: 'Day-to-Day',
    value: 'day',
    disabled: false,
  },
];

const chartDisplayOptions: SelectValue<DataCategory>[] = [
  {
    label: 'Errors',
    value: DataCategory.ERRORS,
    disabled: false,
  },
  {
    label: 'Transactions',
    value: DataCategory.TRANSACTIONS,
    disabled: false,
  },
  {
    label: 'Attachments',
    value: DataCategory.ATTACHMENTS,
    disabled: false,
  },
];

enum SeriesTypes {
  ACCEPTED = 'Accepted',
  DROPPED = 'Dropped',
  PROJECTED = 'Projected',
}

type DroppedBreakdown = {
  other: number;
  overQuota: number;
  spikeProtection: number;
};

/**
 * Avoid passing in the entire DetailedSubscription as this might be reused in
 * Org Stats page
 */
type Props = {
  hasTransactions: boolean;
  hasAttachments: boolean;
  usagePeriodStart: string;
  usagePeriodEnd: string;
  usagePeriodToday: string;

  // // Quotas
  // reservedAttachments: DetailedSubscription['reservedAttachments'];
  // reservedErrors: DetailedSubscription['reservedErrors'];
  // reservedEvents: DetailedSubscription['reservedEvents'];
  // reservedTransactions: DetailedSubscription['reservedTransactions'];

  // Stats
  statsAttachments: BillingStats;
  statsErrors: BillingStats;
  statsTransactions: BillingStats;
};

type State = {
  isUnlimitedQuota: boolean;

  xAxisDates: string[];
  xAxisIndexToday: number;
  chartDisplay: DataCategory;
  chartType: string;
};

class ReservedUsageChart extends React.Component<Props, State> {
  state: State = {
    isUnlimitedQuota: false,

    xAxisDates: [],
    xAxisIndexToday: 0,
    chartDisplay: DataCategory.ERRORS,
    chartType: 'summary',
  };

  static getDerivedStateFromProps(props: Props) {
    const {usagePeriodStart, usagePeriodEnd, usagePeriodToday} = props;

    const today = moment(usagePeriodToday);
    const xAxisDates = getDateRange(usagePeriodStart, usagePeriodEnd);
    const xAxisIndexToday = Math.abs(today.diff(usagePeriodStart, 'd'));

    return {
      xAxisDates,
      xAxisIndexToday,
    };
  }

  mapStatsToChart(stats: BillingStats = []) {
    const {xAxisDates, xAxisIndexToday} = this.state;
    const isCumulative = this.state.chartType === 'summary';
    let sumAccepted = 0;
    let sumDropped = 0;
    let sumOther = 0;
    let sumOverQuota = 0;
    let sumSpikeProtection = 0;
    const chartData: Record<string, any[]> = {
      acceptedStats: [],
      droppedStats: [],
      projectedStats: [],
    };

    xAxisDates.forEach((date, i) => {
      const stat = stats.find(
        s =>
          date === getDateFromMoment(moment(s.date)) ||
          date === getDateFromUnixTimestamp(Number(s.ts))
      );

      const isProjected = stat?.isProjected || stat?.projected || i > xAxisIndexToday;
      const accepted = stat ? stat.accepted : 0;
      const dropped = stat ? stat.dropped.total : 0;

      sumDropped = isCumulative ? sumDropped + dropped : dropped;
      sumAccepted = isCumulative ? sumAccepted + accepted : accepted;
      if (stat?.dropped.overQuota) {
        sumOverQuota = isCumulative
          ? sumOverQuota + stat.dropped.overQuota
          : stat.dropped.overQuota;
      }
      if (stat?.dropped.spikeProtection) {
        sumSpikeProtection = isCumulative
          ? sumSpikeProtection + stat.dropped.spikeProtection
          : stat.dropped.spikeProtection;
      }
      sumOther = Math.max(sumDropped - sumOverQuota - sumSpikeProtection, 0);

      if (!isProjected) {
        chartData.acceptedStats.push({
          value: [date, sumAccepted],
          tooltip: {show: false},
        });
        chartData.droppedStats.push({
          value: [date, sumDropped],
          tooltip: {show: false},
          dropped: {
            other: sumOther,
            overQuota: sumOverQuota,
            spikeProtection: sumSpikeProtection,
          } as DroppedBreakdown,
        });
      } else {
        chartData.projectedStats.push({
          value: [date, sumAccepted],
          tooltip: {show: false},
          itemStyle: {opacity: 0.6},
        });
      }
    });

    return chartData;
  }

  handleSelectorForType(value: string) {
    this.setState({chartType: value});
  }

  handleSelectorForDisplay(value: DataCategory) {
    // const {
    //   reservedErrors,
    //   reservedEvents,
    //   reservedTransactions,
    //   reservedAttachments,
    // } = this.props;

    // let isUnlimitedQuota = false;
    // if (value === DataCategory.ERRORS) {
    //   isUnlimitedQuota = reservedEvents === 0 || reservedErrors === 0;
    // }
    // if (value === DataCategory.TRANSACTIONS) {
    //   isUnlimitedQuota = reservedTransactions === 0;
    // }
    // if (value === DataCategory.ATTACHMENTS) {
    //   isUnlimitedQuota = reservedAttachments === 0;
    // }

    this.setState({
      // isUnlimitedQuota,
      chartDisplay: value,
    });
  }

  get chartColors() {
    const {chartDisplay} = this.state;

    if (chartDisplay === DataCategory.ERRORS) {
      return [COLOR_ERRORS, COLOR_ERRORS_DROPPED, COLOR_PROJECTED];
    }

    if (chartDisplay === DataCategory.ATTACHMENTS) {
      return [COLOR_ATTACHMENTS, COLOR_ATTACHMENTS_DROPPED, COLOR_PROJECTED];
    }
    return [COLOR_TRANSACTIONS, COLOR_TRANSACTIONS_DROPPED, COLOR_PROJECTED];
  }

  get chartData() {
    const {
      // reservedErrors,
      // reservedEvents,
      // reservedTransactions,
      // reservedAttachments,
      statsErrors,
      // statsTransactions,
      // statsAttachments,
    } = this.props;
    const {xAxisDates, chartDisplay} = this.state;

    const display = chartDisplayOptions.find(o => o.value === chartDisplay);
    if (!display) {
      throw new Error('Selected item is not supported');
    }

    const {label} = display;
    // const {label, value} = display;

    // if (value === DataCategory.ERRORS) {
    return {
      chartLabel: label,
      chartData: this.mapStatsToChart(statsErrors),
      xAxisData: xAxisDates,
      yAxisMinInterval: 1000,
      yAxisFormatter: formatAbbreviatedNumber,
      // yAxisQuotaLine: reservedErrors || reservedEvents,
      tooltipValueFormatter: (val: number) => val.toLocaleString(),
    };
    // }

    // if (value === DataCategory.TRANSACTIONS) {
    //   return {
    //     chartLabel: label,
    //     chartData: this.mapStatsToChart(statsTransactions),
    //     xAxisData: xAxisDates,
    //     yAxisMinInterval: 1000,
    //     yAxisFormatter: formatAbbreviatedNumber,
    //     // yAxisQuotaLine: reservedTransactions || 0,
    //     tooltipValueFormatter: (val: number) => val.toLocaleString(),
    //   };
    // }

    // return {
    //   chartLabel: label,
    //   chartData: this.mapStatsToChart(statsAttachments),
    //   xAxisData: xAxisDates,
    //   yAxisMinInterval: 1 * GIGABYTE,
    //   yAxisFormatter: (val: number) =>
    //     formatUsageWithUnits(val, DataCategory.ATTACHMENTS, {
    //       isAbbreviated: true,
    //       useUnitScaling: true,
    //     }),
    //   yAxisQuotaLine: reservedAttachments === null ? 0 : reservedAttachments * GIGABYTE,
    //   tooltipValueFormatter: (val: number) =>
    //     formatUsageWithUnits(val, DataCategory.ATTACHMENTS, {useUnitScaling: true}),
    // };
  }

  // get chartQuotaLineLabel() {
  //   const {chartDisplay} = this.state;
  //   const {
  //     reservedErrors,
  //     reservedEvents,
  //     reservedTransactions,
  //     reservedAttachments,
  //   } = this.props;

  //   if (chartDisplay === DataCategory.ERRORS) {
  //     return formatReservedWithUnits(reservedErrors || reservedEvents, chartDisplay, {
  //       isAbbreviated: true,
  //     });
  //   }

  //   if (chartDisplay === DataCategory.TRANSACTIONS) {
  //     return formatReservedWithUnits(reservedTransactions, chartDisplay, {
  //       isAbbreviated: true,
  //     });
  //   }

  //   return formatReservedWithUnits(reservedAttachments, chartDisplay);
  // }

  renderFooter() {
    const {
      hasTransactions,
      hasAttachments,
      statsTransactions,
      statsAttachments,
      usagePeriodStart,
      usagePeriodEnd,
    } = this.props;

    const hasUsage = (item: BillingStat) => item.total > 0 && !item.isProjected;

    // Leave the options enabled if the current plan has all 3 datacategories
    // or if the account tracked usage in the current billing period.
    const hasOrUsedTransactions = hasTransactions || statsTransactions.some(hasUsage);
    const hasOrUsedAttachments = hasAttachments || statsAttachments.some(hasUsage);

    const displayOptions = chartDisplayOptions.map(option => {
      if (
        option.value === DataCategory.ERRORS ||
        (option.value === DataCategory.TRANSACTIONS && hasOrUsedTransactions) ||
        (option.value === DataCategory.ATTACHMENTS && hasOrUsedAttachments)
      ) {
        return option;
      }
      return {
        ...option,
        tooltip: t(
          'Your plan does not include %s. Migrate to our latest plans to access new features.',
          option.value
        ),
        disabled: true,
      };
    });

    return (
      <ChartControls>
        <InlineContainer>
          <SectionValue>
            <IconCalendar />
          </SectionValue>
          <SectionValue>
            {moment(usagePeriodStart).format('ll')}
            {' — '}
            {moment(usagePeriodEnd).format('ll')}
          </SectionValue>
        </InlineContainer>
        <InlineContainer>
          <OptionSelector
            title={t('Type')}
            selected={this.state.chartType}
            options={chartTypeOptions}
            onChange={(val: string) => this.handleSelectorForType(val)}
          />
          <OptionSelector
            title={t('Display')}
            menuWidth="135px"
            selected={this.state.chartDisplay}
            options={displayOptions}
            onChange={(val: string) => this.handleSelectorForDisplay(val as DataCategory)}
          />
        </InlineContainer>
      </ChartControls>
    );
  }

  render() {
    // const {isUnlimitedQuota} = this.state;
    const {
      chartData,
      xAxisData,
      yAxisMinInterval,
      yAxisFormatter,
      // yAxisQuotaLine,
      tooltipValueFormatter,
    } = this.chartData;

    // const isCumulative = this.state.chartType === 'summary';

    const legendSeries = [
      {
        name: SeriesTypes.ACCEPTED,
      },
      {
        name: SeriesTypes.DROPPED,
      },
      {
        name: SeriesTypes.PROJECTED,
      },
    ];

    const tooltip = Tooltip({
      // Trigger to axis prevents tooltip from redrawing when hovering
      // over individual bars
      trigger: 'axis',
      // Custom tooltip implementation as we show a breakdown for dropped results.
      formatter(series) {
        const seriesList = Array.isArray(series) ? series : [series];
        const time = seriesList[0]?.value?.[0];
        return [
          '<div class="tooltip-series">',
          seriesList
            .map(s => {
              const label = s.seriesName ?? '';
              const value = tooltipValueFormatter(s.value?.[1]);

              const dropped = s.data.dropped as DroppedBreakdown | undefined;
              if (typeof dropped === 'undefined' || value === '0') {
                return `<div><span class="tooltip-label">${s.marker} <strong>${label}</strong></span> ${value}</div>`;
              }
              const other = tooltipValueFormatter(dropped.other);
              const overQuota = tooltipValueFormatter(dropped.overQuota);
              const spikeProtection = tooltipValueFormatter(dropped.spikeProtection);
              // Used to shift breakdown over the same amount as series markers.
              const indent = '<span style="display: inline-block; width: 15px"></span>';
              const labels = [
                `<div><span class="tooltip-label">${s.marker} <strong>${t(
                  'Dropped'
                )}</strong></span> ${value}</div>`,
                `<div><span class="tooltip-label">${indent} <strong>${t(
                  'Over Quota'
                )}</strong></span> ${overQuota}</div>`,
                `<div><span class="tooltip-label">${indent} <strong>${t(
                  'Spike Protection'
                )}</strong></span> ${spikeProtection}</div>`,
                `<div><span class="tooltip-label">${indent} <strong>${t(
                  'Other'
                )}</strong></span> ${other}</div>`,
              ];
              return labels.join('');
            })
            .join(''),
          '</div>',
          `<div class="tooltip-date">${time}</div>`,
          `<div class="tooltip-arrow"></div>`,
        ].join('');
      },
    });

    return (
      <Panel id="usage-chart">
        <ChartContainer>
          <HeaderTitleLegend>{t('Current Usage Period')}</HeaderTitleLegend>
          <BaseChart
            colors={this.chartColors}
            grid={{bottom: '3px', left: '0px', right: '10px', top: '40px'}}
            xAxis={xAxis({
              show: true,
              type: 'category',
              name: 'Date',
              boundaryGap: true,
              data: xAxisData,
              truncate: 6,
              axisTick: {
                interval: 6,
                alignWithLabel: true,
              },
              axisLabel: {
                interval: 6,
              },
              theme,
            })}
            yAxis={{
              min: 0,
              minInterval: yAxisMinInterval,
              axisLabel: {
                formatter: yAxisFormatter,
                color: theme.chartLabel,
              },
            }}
            series={[
              barSeries({
                name: SeriesTypes.ACCEPTED,
                data: chartData.acceptedStats,
                barMinHeight: 1,
                stack: 'usage',
                legendHoverLink: false,
              }),
              barSeries({
                name: SeriesTypes.DROPPED,
                data: chartData.droppedStats,
                stack: 'usage',
                legendHoverLink: false,
              }),
              barSeries({
                name: SeriesTypes.PROJECTED,
                data: chartData.projectedStats,
                barMinHeight: 1,
                stack: 'usage',
                legendHoverLink: false,
              }),
              // lineSeries({
              //   name: 'Quota Line',
              //   markLine: MarkLine({
              //     silent: true,
              //     lineStyle: {
              //       color:
              //         !isCumulative || isUnlimitedQuota ? 'transparent' : theme.gray300,
              //       type: 'dashed',
              //     },
              //     data: [{yAxis: isCumulative ? yAxisQuotaLine : 0}] as any,
              //     precision: 1,
              //     label: {
              //       show: isCumulative ? true : false,
              //       position: 'insideStartTop',
              //       formatter: `Plan Quota (${this.chartQuotaLineLabel})`,
              //       color: theme.chartLabel,
              //       fontSize: 10,
              //     } as any, // TODO(ts): This is either invalid or not typed fully
              //   }),
              // }),
            ]}
            tooltip={tooltip}
            onLegendSelectChanged={() => {}}
            legend={Legend({
              right: 10,
              top: 5,
              data: legendSeries,
              theme,
            })}
          />
        </ChartContainer>
        {/* {this.renderFooter()} */}
      </Panel>
    );
  }
}

export default ReservedUsageChart;

function getDateFromUnixTimestamp(timestamp: number) {
  const date = moment.unix(timestamp);
  return getDateFromMoment(date);
}

function getDateFromMoment(m: moment.Moment) {
  return m.format('MMM D');
}

function getDateRange(dateStart: string, dateEnd: string): string[] {
  const range: string[] = [];
  const start = moment(dateStart);
  const end = moment(dateEnd);

  while (!start.isAfter(end, 'd')) {
    range.push(getDateFromMoment(start));
    start.add(1, 'd');
  }

  return range;
}

export type BillingStat = {
  ts: string;
  date: string;
  total: number;
  accepted: number;
  filtered: number;
  dropped: {
    total: number;
    overQuota?: number;
    spikeProtection?: number;
    other?: number; // Calculated in UsageDetailItem
  };
  projected?: boolean; // TODO(chart-cleanup): Used by v1 only
  isProjected?: boolean;
};
export type BillingStats = BillingStat[];
