// static/otel-init.js
// Browser-side OpenTelemetry initialization.
// Only activates when <meta name="otel-endpoint"> is present in the page.
(function() {
  'use strict';
  var meta = document.querySelector('meta[name="otel-endpoint"]');
  if (!meta) return;

  var endpoint = meta.getAttribute('content');
  var serviceName = document.querySelector('meta[name="otel-service-name"]');
  serviceName = serviceName ? serviceName.getAttribute('content') : 'Browser';

  var provider = new opentelemetry.sdk.trace.web.WebTracerProvider();

  var OtelBatchExporter = {
    _batch: [],
    _timer: null,
    export: function(spans, resultCallback) {
      for (var i = 0; i < spans.length; i++) {
        this._batch.push(_spanToJson(spans[i]));
      }
      if (!this._timer) {
        this._timer = setTimeout(this._flush.bind(this), 2000);
      }
      resultCallback({ code: 0 });
    },
    _flush: function() {
      this._timer = null;
      if (!this._batch.length) return;
      var payload = JSON.stringify(this._batch);
      this._batch = [];
      navigator.sendBeacon(endpoint, payload);
    },
    shutdown: function() { this._flush(); }
  };

  function _spanToJson(span) {
    var ctx = span.spanContext();
    return {
      name: span.name,
      trace_id: ctx.traceId,
      span_id: ctx.spanId,
      parent_span_id: span.parentSpanId || '',
      start_time: span.startTime,
      end_time: span.endTime,
      attributes: span.attributes || {},
      resource: { 'service.name': serviceName }
    };
  }

  provider.addSpanProcessor(
    new opentelemetry.sdk.trace.web.SimpleSpanProcessor(OtelBatchExporter)
  );
  provider.register();

  var fetchInstrumentation = new opentelemetry.instrumentation.fetch.FetchInstrumentation({
    propagateTraceHeaderCorsUrls: [/.*/],
    clearTimingResources: false,
  });
  fetchInstrumentation.setTracerProvider(provider);
  fetchInstrumentation.enable();

  window._otelWsTraceparent = null;
  window._otelExtractWsTrace = function(msg) {
    if (msg && msg._traceparent) {
      window._otelWsTraceparent = msg._traceparent;
    }
  };

  console.log('[otel] Browser tracing initialized, service=' + serviceName);
})();
