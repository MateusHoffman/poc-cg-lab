"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

type Span = {
  name: string;
  duration_ms: number;
  trace_id: string;
  attributes: Record<string, string | number | boolean>;
};

type Phase = {
  name: string;
  duration_ms: number;
  detail: Record<string, unknown>;
};

type AuditEvent = {
  trace_id: string;
  session_id: string;
  client_message?: string;
  query: string;
  response?: string;
  intent: string;
  latency_ms: number;
  pii_redactions: number;
  faithful: boolean;
  hallucinated: string[];
  cache_hit: boolean;
  model: string;
  logs?: string[];
  phases?: Phase[];
  spans: Span[];
};

export default function AuditPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/backend/api/audit", { cache: "no-store" });
      if (!response.ok) throw new Error(`Falha ${response.status}`);
      const body = (await response.json()) as { events: AuditEvent[] };
      setEvents(body.events ?? []);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Falha ao ler a auditoria");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <main className="log">
      <header className="log-head">
        <div>
          <h1>Auditoria</h1>
          <p>
            <Link href="/">Voltar ao estoque</Link>
          </p>
          <p>{loading ? "Lendo consultas" : `${events.length} consultas`}</p>
        </div>
        <button type="button" onClick={() => void load()}>
          Atualizar
        </button>
      </header>

      {error ? <p>{error}</p> : null}
      {!loading && events.length === 0 ? (
        <p>Nenhuma consulta ainda. Faça uma pergunta no estoque e volte aqui.</p>
      ) : null}

      {events.map((event) => {
        const phases = event.phases ?? [];
        const phaseSum = Math.round(phases.reduce((total, phase) => total + phase.duration_ms, 0) * 100) / 100;
        const scale = Math.max(event.latency_ms, 1);
        const spanScale = Math.max(...event.spans.map((span) => span.duration_ms), 1);
        return (
          <article className="event-card" key={event.trace_id}>
            <p>{event.client_message ?? event.query}</p>
            <div className="facts">
              <p>
                <span>Trace</span>
                {event.trace_id}
              </p>
              <p>
                <span>Sessão</span>
                {event.session_id}
              </p>
              <p>
                <span>Intenção</span>
                {event.intent}
              </p>
              <p>
                <span>Latência</span>
                {event.latency_ms} ms
              </p>
              <p>
                <span>Modelo</span>
                {event.model}
              </p>
              <p>
                <span>Cache</span>
                {event.cache_hit ? "hit" : "miss"}
              </p>
              <p>
                <span>PII</span>
                {event.pii_redactions}
              </p>
              <p>
                <span>Fidelidade</span>
                {event.faithful ? "fiel" : "revisar"}
              </p>
              <p>
                <span>Alucinações</span>
                {event.hallucinated.length ? event.hallucinated.join(", ") : "nenhuma"}
              </p>
              <p>
                <span>Soma das fases</span>
                {phaseSum} ms
              </p>
            </div>

            {event.logs?.length ? (
              <ol className="story">
                {event.logs.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ol>
            ) : null}

            {event.response ? (
              <div className="final-answer">
                <span>Resposta final</span>
                <p>{event.response}</p>
              </div>
            ) : null}

            {phases.map((phase) => (
              <section className="phase" key={`${event.trace_id}-${phase.name}`}>
                <p>
                  {phase.name}
                  <strong> {phase.duration_ms} ms</strong>
                </p>
                <i style={{ width: `${Math.max(4, (phase.duration_ms / scale) * 100)}%` }} />
                <pre>{JSON.stringify(phase.detail, null, 2)}</pre>
              </section>
            ))}

            <p className="span-note">
              Os spans abaixo são aninhados. A busca e o sandbox já estão dentro de agent.run,
              por isso somá-los passa do tempo do agente. A latência da consulta é a soma das fases.
              O streaming da resposta é a fase que faltava nos spans antigos.
            </p>
            <ul className="audit">
              {event.spans.map((span, index) => (
                <li key={`${event.trace_id}-${span.name}-${index}`}>
                  <span>{span.name}</span>
                  <span>{span.duration_ms} ms</span>
                  <i style={{ width: `${Math.max(6, (span.duration_ms / spanScale) * 100)}%` }} />
                  <span className="attrs">
                    {Object.entries(span.attributes)
                      .map(([key, value]) => `${key}=${String(value)}`)
                      .join("  ")}
                  </span>
                </li>
              ))}
            </ul>
          </article>
        );
      })}
    </main>
  );
}
