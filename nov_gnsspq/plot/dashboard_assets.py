#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
################################################################################

MIT License

Copyright (c) 2026 NovAtel Inc.

This project is licensed under the MIT License. A copy of the license is
available in the LICENSE file included with this repository.

This software may incorporate or depend upon third-party software components
that are subject to separate license terms. Users are responsible for
complying with any applicable third-party licenses.

NovAtel® and other product names, logos, and trademarks referenced in this
project are the property of their respective owners. No rights or licenses to
NovAtel trademarks are granted under the MIT License.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, AS MORE FULLY SET FORTH IN THE LICENSE FILE.
################################################################################

Static CSS and JavaScript assets for the nov_gnsspq interactive HTML dashboard.
"""


DASHBOARD_CSS: str = """\
.threshold-panel {
  background: #252e3f;
  border-bottom: 1px solid #3a4558;
  padding: 6px 12px;
  font-size: 13px;
  color: #c9d1de;
}

.threshold-toggle {
  background: transparent;
  border: none;
  cursor: pointer;
  color: #8892a4;
  font-size: 13px;
  padding: 2px 4px;
}

.threshold-toggle:hover {
  color: #c9d1de;
}

.threshold-body {
  display: none;
  margin-top: 6px;
}

.threshold-form {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.threshold-form input[type="number"],
.threshold-form input[type="text"] {
  background: #1b2232;
  border: 1px solid #3a4558;
  color: #c9d1de;
  border-radius: 3px;
  padding: 3px 6px;
  font-size: 12px;
  width: 90px;
}

.threshold-form label {
  color: #8892a4;
  font-size: 12px;
}

.threshold-add-btn {
  background: #2d3a52;
  border: 1px solid #3a4558;
  color: #c9d1de;
  border-radius: 3px;
  padding: 3px 10px;
  cursor: pointer;
  font-size: 12px;
}

.threshold-add-btn:hover {
  background: #4a9ff5;
  border-color: #4a9ff5;
  color: #fff;
}

.threshold-list {
  display: flex;
  flex-direction: row;
  flex-wrap: wrap;
  gap: 4px;
}

.threshold-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #1b2232;
  border: 1px solid #3a4558;
  border-radius: 10px;
  padding: 2px 8px;
  font-size: 12px;
  color: #c9d1de;
}

.threshold-label {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.threshold-remove {
  background: transparent;
  border: none;
  cursor: pointer;
  color: #8892a4;
  font-size: 14px;
  line-height: 1;
  padding: 0 2px;
}

.threshold-remove:hover {
  color: #e05c5c;
}
"""


DASHBOARD_JS: str = """\
(function () {
  'use strict';

  var thresholdState    = {};
  var originalShapes    = {};
  var originalAnnotations = {};

  function _buildThresholdShapes(thresholds) {
    var shapes = [], annotations = [];
    for (var i = 0; i < thresholds.length; i++) {
      var t = thresholds[i], v = t.value;
      if (t.axis === 'H') {
        shapes.push({type:'line', x0:0, x1:1, xref:'paper',
          y0:v, y1:v, yref:'y',
          line:{color:'#e05c5c', dash:'dash', width:1}});
        if (t.label) annotations.push({
          xref:'paper', x:1, xanchor:'right',
          yref:'y', y:v, yanchor:'bottom',
          text:t.label, showarrow:false,
          font:{color:'#e05c5c', size:11}});
      } else {
        shapes.push({type:'line', x0:v, x1:v, xref:'x',
          y0:0, y1:1, yref:'paper',
          line:{color:'#e05c5c', dash:'dash', width:1}});
        if (t.label) annotations.push({
          xref:'x', x:v, xanchor:'left',
          yref:'paper', y:1, yanchor:'top',
          text:t.label, showarrow:false,
          font:{color:'#e05c5c', size:11}});
      }
    }
    return {shapes:shapes, annotations:annotations};
  }

  window.applyThresholds = function (tabId) {
    var panel = document.getElementById('panel-' + tabId);
    if (!panel) return;
    var divs = panel.querySelectorAll('.plotly-graph-div');
    var thresholds = thresholdState[tabId] || [];
    var built = _buildThresholdShapes(thresholds);
    divs.forEach(function (gd) {
      var origShapes = originalShapes[gd.id] || [];
      var origAnnotations = originalAnnotations[gd.id] || [];
      Plotly.relayout(gd, {
        shapes: origShapes.concat(built.shapes),
        annotations: origAnnotations.concat(built.annotations)
      });
    });
  };

  window.addThreshold = function (tabId, axis, value, label) {
    if (!thresholdState[tabId]) thresholdState[tabId] = [];
    thresholdState[tabId].push({axis:axis, value:value, label:label});
    window.applyThresholds(tabId);
    _renderThresholdList(tabId);
  };

  window.removeThreshold = function (tabId, idx) {
    if (!thresholdState[tabId]) return;
    thresholdState[tabId].splice(idx, 1);
    window.applyThresholds(tabId);
    _renderThresholdList(tabId);
  };

  window.submitThreshold = function (tabId) {
    var valInput = document.getElementById('threshold-value-' + tabId);
    var labelInput = document.getElementById('threshold-label-' + tabId);
    var axisEl = document.querySelector(
      '#threshold-form-' + tabId + ' input[name="axis"]:checked');
    var axis = axisEl ? axisEl.value : 'H';
    var rawVal = valInput ? valInput.value.trim() : '';
    var v = parseFloat(rawVal);
    if (rawVal === '' || isNaN(v)) {
      if (valInput) {
        valInput.style.outline = '2px solid #e05c5c';
        setTimeout(function () { valInput.style.outline = ''; }, 600);
      }
      return;
    }
    var label = (labelInput ? labelInput.value.trim() : '') || '';
    window.addThreshold(tabId, axis, v, label);
    if (valInput)   valInput.value   = '';
    if (labelInput) labelInput.value = '';
  };

  window.toggleThresholdPanel = function (tabId) {
    var body = document.getElementById('threshold-body-' + tabId);
    var btn  = document.getElementById('threshold-toggle-' + tabId);
    if (!body) return;
    var isOpen = body.style.display === 'block';
    body.style.display = isOpen ? 'none' : 'block';
    if (btn) btn.textContent = isOpen ? 'Thresholds \\u25b8' : 'Thresholds \\u25be';
  };

  function _renderThresholdList(tabId) {
    var list = document.getElementById('threshold-list-' + tabId);
    if (!list) return;
    list.innerHTML = '';
    var thresholds = thresholdState[tabId] || [];
    thresholds.forEach(function (t, i) {
      var item = document.createElement('div');
      item.className = 'threshold-item';
      var dispLabel = t.label || (t.axis + '=' + t.value);
      var labelSpan = document.createElement('span');
      labelSpan.className = 'threshold-label';
      labelSpan.textContent = dispLabel;
      var removeBtn = document.createElement('button');
      removeBtn.className = 'threshold-remove';
      removeBtn.textContent = '×';
      removeBtn.addEventListener('click', (function (idx) {
        return function () { window.removeThreshold(tabId, idx); };
      }(i)));
      item.appendChild(labelSpan);
      item.appendChild(removeBtn);
      list.appendChild(item);
    });
  }

  function _initStash(gd) {
    if (originalShapes[gd.id] !== undefined) return;
    originalShapes[gd.id] = (gd.layout && gd.layout.shapes) ? gd.layout.shapes.slice() : [];
    originalAnnotations[gd.id] = (gd.layout && gd.layout.annotations) ? gd.layout.annotations.slice() : [];
  }

  function _binarySearch(arr, target) {
    if (!arr || !arr.length) return -1;
    var lo = 0, hi = arr.length - 1;
    while (lo < hi) {
      var mid = (lo + hi) >> 1;
      if (arr[mid] < target) lo = mid + 1; else hi = mid;
    }
    if (lo > 0 && Math.abs(arr[lo-1] - target) < Math.abs(arr[lo] - target)) return lo - 1;
    return lo;
  }

  function _getTabId(gd) {
    var panel = gd.closest ? gd.closest('.tab-panel')
      : (function (el) {
          while (el && !el.classList.contains('tab-panel')) el = el.parentElement;
          return el;
        }(gd));
    return panel ? panel.getAttribute('data-tab-id') : '';
  }

  function _onHover(gd, eventData) {
    if (!eventData || !eventData.points || !eventData.points.length) return;
    var pt = eventData.points[0];
    var srcTrace = gd.data[pt.curveNumber];
    var isScatterSrc = srcTrace && srcTrace.meta && srcTrace.meta.cross_highlight;
    var timestamp;
    if (isScatterSrc) {
      if (!srcTrace.customdata || pt.pointNumber === undefined) return;
      timestamp = srcTrace.customdata[pt.pointNumber];
    } else {
      timestamp = pt.x;
    }
    if (timestamp === undefined || timestamp === null) return;

    var xaxisKeys = {};
    for (var i = 0; i < gd.data.length; i++) {
      var tr = gd.data[i];
      if (!tr.meta || !tr.meta.cross_highlight) xaxisKeys[tr.xaxis || 'x'] = true;
    }

    var tabId = _getTabId(gd);
    var origShapes = originalShapes[gd.id] || [];
    var thresholds = thresholdState[tabId] || [];
    var builtThresh = _buildThresholdShapes(thresholds);
    var hoverShapes = origShapes.concat(builtThresh.shapes);
    Object.keys(xaxisKeys).forEach(function (key) {
      hoverShapes.push({type:'line', x0:timestamp, x1:timestamp, xref:key,
        y0:0, y1:1, yref:'paper',
        line:{color:'#8892a4', dash:'dot', width:1}});
    });
    Plotly.relayout(gd, {shapes: hoverShapes});

    for (var j = 0; j < gd.data.length; j++) {
      var t = gd.data[j];
      if (t.meta && t.meta.cross_highlight && t.customdata && t.customdata.length) {
        var matchIdx = _binarySearch(t.customdata, timestamp);
        if (matchIdx >= 0) {
          Plotly.Fx.hover(gd, [{curveNumber:j, pointNumber:matchIdx}]);
        }
      }
    }
  }

  function _onUnhover(gd) {
    var tabId = _getTabId(gd);
    window.applyThresholds(tabId);
    try { Plotly.Fx.hover(gd, []); } catch (e) {}
  }

  function _initHoverListeners(gd) {
    gd.on('plotly_hover',   function (e) { _onHover(gd, e); });
    gd.on('plotly_unhover', function ()  { _onUnhover(gd); });
  }

  window.nov_gnsspq_onTabActivated = function (id) {
    var panel = document.getElementById('panel-' + id);
    if (!panel) return;
    panel.querySelectorAll('.plotly-graph-div').forEach(function (gd) {
      try { Plotly.relayout(gd, {}); } catch (e) {}
    });
  };

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.plotly-graph-div').forEach(function (gd) {
      _initStash(gd);
      _initHoverListeners(gd);
    });
  });
}());
"""
