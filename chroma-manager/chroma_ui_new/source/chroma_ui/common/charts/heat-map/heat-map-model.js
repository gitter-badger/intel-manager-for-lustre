//
// INTEL CONFIDENTIAL
//
// Copyright 2013-2014 Intel Corporation All Rights Reserved.
//
// The source code contained or described herein and all documents related
// to the source code ("Material") are owned by Intel Corporation or its
// suppliers or licensors. Title to the Material remains with Intel Corporation
// or its suppliers and licensors. The Material contains trade secrets and
// proprietary and confidential information of Intel or its suppliers and
// licensors. The Material is protected by worldwide copyright and trade secret
// laws and treaty provisions. No part of the Material may be used, copied,
// reproduced, modified, published, uploaded, posted, transmitted, distributed,
// or disclosed in any way without Intel's prior express written permission.
//
// No license under any patent, copyright, trade secret or other intellectual
// property right is granted to or conferred upon you by disclosure or delivery
// of the Materials, either expressly, by implication, inducement, estoppel or
// otherwise. Any license under such intellectual property rights must be
// express and approved by Intel in writing.


angular.module('charts').factory('heatMapModelFactory', ['d3', 'chartParamMixins', 'chartUtils', heatMapModelFactory]);


function heatMapModelFactory (d3, chartParamMixins, chartUtils) {
  'use strict';

  var MODEL_SEL = 'heat-map-model',
    ROW_SEL = 'row',
    CELL_SEL = 'cell';

  return function getModel() {
    var config = {
      x: d3.scale.linear(),
      y: d3.scale.ordinal(),
      z: d3.scale.linear().interpolate(d3.interpolateRgb),
      width: 960,
      height: 400,
      showXAxis: true,
      showYAxis: true,
      showLegend: true,
      lowColor: '#fbecec',
      highColor: '#d9534f',
      onMouseOver: _.noop,
      onMouseMove: _.noop,
      onMouseOut: _.noop,
      onMouseClick: _.noop,
      margin: {top: 0, right: 0, bottom: 0, left: 0},
      transitionDuration: 250
    };

    chartParamMixins(config, chart);

    function chart (selection) {
      var margin = chart.margin(),
        x = chart.x(),
        y = chart.y(),
        z = chart.z(),
        cl = chartUtils.cl;

      selection.each(function render (data) {
        var container = d3.select(this);
        var availableWidth = (chart.width() || parseInt(container.style('width'), 10)) - margin.left - margin.right,
          availableHeight = (chart.height() || parseInt(container.style('height'), 10)) - margin.top - margin.bottom;

        var values = _.cloneDeep(_.pluck(data, 'values')),
          keys = _.pluck(data, 'key'),
          mergedValues = d3.merge(values),
          domain = d3.extent(mergedValues, getProp('z')),
          dateExtent = d3.extent(mergedValues, getProp('x'));

        chart.destroy = function () {
          container.remove();
          container = selection = null;
        };

        if (mergedValues.length === 0) {
          container.selectAll(cl(MODEL_SEL)).remove();
          return;
        }

        x.domain(dateExtent).range([0, availableWidth]);

        y.domain(keys).rangePoints([0, availableHeight], 1.0);

        z.domain(domain).range([chart.lowColor(), chart.highColor()]);

        // data join
        var heatMapModel = container.selectAll(cl(MODEL_SEL))
          .data([data]);

        // Create the structure on enter.
        heatMapModel.enter()
          .append('g')
          .attr('class', MODEL_SEL);

        heatMapModel.select('rect')
          .attr('width', availableWidth)
          .attr('height', availableHeight);

        d3.select(cl(MODEL_SEL)).on('mouseover', getMouseHandler(chart.onMouseOver()));

        d3.select(cl(MODEL_SEL)).on('mousemove', getMouseHandler(chart.onMouseMove()));

        d3.select(cl(MODEL_SEL)).on('mouseout', getMouseHandler(chart.onMouseOut()));

        d3.select(cl(MODEL_SEL)).on('click', getMouseHandler(chart.onMouseClick()));

        var gridHeight = availableHeight / keys.length;

        var row = heatMapModel
          .selectAll(cl(ROW_SEL)).data(_.identity);

        row.enter()
          .append('g')
          .attr('class', ROW_SEL);

        row.transition().duration(chart.transitionDuration()).attr('transform', function (d) {
          return chartUtils.translator(0, Math.max(y(d.key) - (gridHeight / 2), 0));
        });

        row.exit().remove();

        var cell = row.selectAll(cl(CELL_SEL))
          .data(function (d) {
            var cloned = _.cloneDeep(d.values),
              size = availableWidth / cloned.length;

            return cloned.map(function (value) {
              value.key = d.key;
              value.size = size;
              value.size = size;

              return value;
            });
          });

        cell.enter().append('rect')
          .attr('class', CELL_SEL)
          .attr('stroke', '#EEE')
          .attr('fill', function (d) { return z(d.z); });

        cell.transition().duration(chart.transitionDuration())
          .attr('x', function (d) { return x(d.x); })
          .attr('stroke', '#EEE')
          .attr('width', getProp('size'))
          .attr('height', function() { return gridHeight; })
          .attr('fill', function (d) { return z(d.z); });

        cell.exit().transition().duration(chart.transitionDuration()).remove();
      });
    }

    function getMouseHandler (func) {
      return function () {
        var target = d3.select(d3.event.target).filter(chartUtils.cl(CELL_SEL)).node();

        if (!target)
          return;

        var data = target.__data__;
        func(data, target);
      };
    }

    var getProp = _.curry(function getProp(prop, d) {
      return d[prop];
    });

    chart.destroy = _.noop;

    return chart;
  };
}