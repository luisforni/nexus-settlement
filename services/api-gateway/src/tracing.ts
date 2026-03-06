import { NodeSDK } from '@opentelemetry/sdk-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-proto';
import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';
import { Resource } from '@opentelemetry/resources';
import { W3CTraceContextPropagator } from '@opentelemetry/core';
import { CompositePropagator, W3CBaggagePropagator } from '@opentelemetry/core';

const otlpEndpoint =
  process.env.OTEL_EXPORTER_OTLP_ENDPOINT ?? 'http://otel-collector:4318';

const sdk = new NodeSDK({
  resource: new Resource({
    'service.name': process.env.OTEL_SERVICE_NAME ?? 'api-gateway',
    'service.version': '1.0.0',
    'deployment.environment': process.env.ENVIRONMENT ?? 'development',
  }),
  traceExporter: new OTLPTraceExporter({
    url: `${otlpEndpoint}/v1/traces`,
  }),
  instrumentations: [
    getNodeAutoInstrumentations({

      '@opentelemetry/instrumentation-fs': { enabled: false },

      '@opentelemetry/instrumentation-dns': { enabled: false },
    }),
  ],
  textMapPropagator: new CompositePropagator({
    propagators: [
      new W3CTraceContextPropagator(),
      new W3CBaggagePropagator(),
    ],
  }),
});

if (process.env.NODE_ENV !== 'test') {
  sdk.start();
}

process.on('SIGTERM', () => {
  sdk.shutdown().catch(() => undefined);
});
