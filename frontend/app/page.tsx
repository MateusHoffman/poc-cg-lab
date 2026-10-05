"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

type Vehicle = {
  id: string;
  brand: string;
  model: string;
  year: number;
  price: number;
  km: number;
  fuel: string;
  transmission: string;
  body: string;
  city: string;
};

type Finance = {
  months: number;
  down_ratio: number;
  down_payment: number;
  principal: number;
  installment: number;
  code: string;
};

type Span = {
  name: string;
  duration_ms: number;
  trace_id: string;
};

type Metrics = {
  trace_id: string;
  latency_ms: number;
  intent: string;
  cache_hit: boolean;
  pii_redactions: number;
  model: string;
  tokens_estimated: number;
  tokens_saved: number;
  faithful: boolean;
  sandbox_used: boolean;
  vector_backend: string;
  session_backend: string;
  query: string;
  spans: Span[];
};

type Turn = {
  role: "user" | "agent";
  text: string;
  safeQuery?: string;
};

const PROMPTS = [
  { label: "Hatches até 90 mil", query: "Quero um hatch automático até 90 mil" },
  { label: "Comparar Polo e Onix", query: "Compare Polo e Onix" },
  { label: "Financiar o Polo", query: "Simule o financiamento do Polo em 48x com 20% de entrada" },
  {
    label: "Pedido com PII",
    query: "Meu CPF é 123.456.789-09 e meu email é ana@example.com. Qual o melhor SUV até 150 mil?",
  },
  { label: "Fora do estoque", query: "Quero um carro que voa movido a plutônio" },
];

const MODELS = ["offline-template", "llama3.1:8b"] as const;

const money = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const km = new Intl.NumberFormat("pt-BR");

export default function HomePage() {
  const [sessionId, setSessionId] = useState("demo");
  const [query, setQuery] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [finance, setFinance] = useState<Finance | null>(null);
  const [recommendationId, setRecommendationId] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [status, setStatus] = useState("Estoque pronto para consulta.");
  const [busy, setBusy] = useState(false);
  const [model, setModel] = useState<(typeof MODELS)[number]>("offline-template");

  useEffect(() => {
    const savedModel = sessionStorage.getItem("cg-model");
    if (savedModel === "offline-template" || savedModel === "llama3.1:8b") {
      setModel(savedModel);
    }
    const existing = sessionStorage.getItem("cg-session");
    if (existing) {
      setSessionId(existing);
      return;
    }
    const created = `web-${crypto.randomUUID().slice(0, 8)}`;
    sessionStorage.setItem("cg-session", created);
    setSessionId(created);
  }, []);

  async function ask(nextQuery: string) {
    const text = nextQuery.trim();
    if (!text || busy) return;
    setBusy(true);
    setQuery("");
    setFinance(null);
    setVehicles([]);
    setRecommendationId(null);
    setTurns((current) => [...current, { role: "user", text }]);
    setTurns((current) => [...current, { role: "agent", text: "" }]);
    setStatus("Consultando o agente...");

    try {
      const response = await fetch("/backend/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: text, session_id: sessionId, model }),
      });
      if (!response.ok || !response.body) {
        throw new Error(`Falha ${response.status}`);
      }
      await readSse(response, (event, data) => {
        if (event === "status") {
          setStatus(String(data.message ?? ""));
          if (data.safe_query && data.safe_query !== text) {
            setTurns((current) => {
              const copy = [...current];
              const lastUser = [...copy].reverse().find((turn) => turn.role === "user");
              if (lastUser) lastUser.safeQuery = String(data.safe_query);
              return copy;
            });
          }
        }
        if (event === "ui") {
          setVehicles(data.vehicles ?? []);
          setFinance(data.finance ?? null);
          setRecommendationId(data.recommendation_id ?? null);
        }
        if (event === "token") {
          setTurns((current) => {
            const copy = [...current];
            const last = copy[copy.length - 1];
            if (last?.role === "agent") {
              copy[copy.length - 1] = { ...last, text: last.text + String(data.text ?? "") };
            }
            return copy;
          });
        }
        if (event === "metrics") {
          setMetrics(data as Metrics);
          setStatus(data.faithful ? "Resposta fiel ao inventário." : "Guardrail marcou a resposta.");
        }
      });
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Falha ao consultar o agente");
    } finally {
      setBusy(false);
    }
  }

  const featured = vehicles.find((vehicle) => vehicle.id === recommendationId) ?? vehicles[0];
  const companions = vehicles.filter((vehicle) => vehicle.id !== featured?.id).slice(0, 2);

  return (
    <main className="app">
      <section className="pit" aria-label="Painel da consulta">
        <div className="pit-brand">
          <strong>CG/lab AutoAgent</strong>
          <span>
            Sessão {sessionId} <Link href="/audit">Auditoria</Link>
          </span>
        </div>
        <div className="pit-stat">
          <strong>{metrics ? `${metrics.latency_ms} ms` : "—"}</strong>
          <span>{metrics ? metrics.trace_id.slice(0, 8) : "Latência"}</span>
        </div>
        <div className="pit-stat">
          <label className="pit-model">
            <span className="sr-only">Modelo</span>
            <select
              value={model}
              disabled={busy}
              onChange={(event) => {
                const next = event.target.value as (typeof MODELS)[number];
                setModel(next);
                sessionStorage.setItem("cg-model", next);
              }}
            >
              {MODELS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <span>
            {metrics && metrics.model !== model && metrics.model !== "cache"
              ? `última resposta: ${metrics.model}`
              : metrics
                ? `${metrics.tokens_estimated} tokens`
                : "Modelo"}
          </span>
        </div>
        <div className="pit-stat">
          <strong>{metrics ? String(metrics.pii_redactions) : "0"}</strong>
          <span>Redações de PII</span>
        </div>
        <div className="pit-stat">
          <strong>{metrics?.faithful === false ? "revisar" : "ok"}</strong>
          <span>{metrics ? `${metrics.vector_backend} / ${metrics.session_backend}` : "Backends"}</span>
        </div>
      </section>

      <section className="stage">
        <div className="conversation">
          <h1>Pergunte ao estoque.</h1>
          <p className="lede">
            O agente classifica a intenção, consulta a memória vetorial e, quando o pedido é
            financeiro, calcula a parcela num sandbox isolado.
          </p>
          <div className="prompts">
            {PROMPTS.map((prompt) => (
              <button key={prompt.label} type="button" onClick={() => ask(prompt.query)} disabled={busy}>
                {prompt.label}
              </button>
            ))}
          </div>
          <div className="thread" aria-live="polite">
            {turns.map((turn, index) => (
              <article key={`${turn.role}-${index}`} className={`bubble ${turn.role}`}>
                {turn.text}
                {turn.safeQuery ? <div className="redacted">Enviado ao modelo: {turn.safeQuery}</div> : null}
              </article>
            ))}
          </div>
          <p className="status-line">{status}</p>
          <form
            className="composer"
            onSubmit={(event) => {
              event.preventDefault();
              void ask(query);
            }}
          >
            <label className="sr-only" htmlFor="query" style={{ position: "absolute", left: "-999px" }}>
              O que você procura?
            </label>
            <input
              id="query"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Ex.: compare o resultado com o Tracker"
              autoComplete="off"
            />
            <button className="send" type="submit" disabled={busy || !query.trim()}>
              {busy ? "Consultando" : "Enviar"}
            </button>
          </form>
        </div>

        <aside className="sticker" aria-label="Ficha do veículo">
          {featured ? (
            <>
              <div className="sticker-head">
                <div>
                  <p>
                    {featured.brand} {featured.model}
                  </p>
                  <p>
                    {featured.year}, {featured.city}
                  </p>
                </div>
                <p className="price">{money.format(featured.price)}</p>
              </div>
              <div className="sticker-body">
                <div className="spec-row">
                  <p>
                    <span>Quilometragem</span>
                    {km.format(featured.km)} km
                  </p>
                  <p>
                    <span>Câmbio</span>
                    {featured.transmission === "automatico" ? "Automático" : "Manual"}
                  </p>
                  <p>
                    <span>Combustível</span>
                    {featured.fuel}
                  </p>
                  <p>
                    <span>Carroceria</span>
                    {featured.body}
                  </p>
                </div>
                {companions.length > 0 ? (
                  <div className="spec-row">
                    {companions.map((vehicle) => (
                      <p key={vehicle.id}>
                        <span>
                          {vehicle.brand} {vehicle.model}
                        </span>
                        {money.format(vehicle.price)}, {km.format(vehicle.km)} km
                      </p>
                    ))}
                  </div>
                ) : null}
                {finance ? (
                  <div className="finance">
                    <p>
                      {finance.months}x com entrada de {Math.round(finance.down_ratio * 100)}% (
                      {money.format(finance.down_payment)})
                    </p>
                    <p>Parcela estimada {money.format(finance.installment)}</p>
                    <code>{finance.code}</code>
                  </div>
                ) : null}
                {recommendationId ? <p className="recommendation">Recomendação do agente</p> : null}
              </div>
            </>
          ) : (
            <div className="empty-sticker">
              <p>A ficha aparece quando o agente devolve um veículo do inventário.</p>
              <p>Preço, parcela e comparação saem da ferramenta, não de um texto solto do modelo.</p>
            </div>
          )}
          {metrics ? <Audit metrics={metrics} model={model} /> : null}
        </aside>
      </section>
    </main>
  );
}

function Audit({ metrics, model }: { metrics: Metrics; model: string }) {
  const scale = Math.max(...metrics.spans.map((span) => span.duration_ms), 1);
  const answeredWith = metrics.model === "cache" ? model : metrics.model;
  return (
    <section className="audit" aria-label="Auditoria da consulta">
      <p>
        {answeredWith} · {metrics.intent} em {metrics.latency_ms} ms
        {metrics.cache_hit ? ", cache" : ""}
        {metrics.faithful ? ", fiel" : ", revisar"}
      </p>
      <p className="audit-query">{metrics.query}</p>
      <ul>
        {metrics.spans.map((span) => (
          <li key={`${span.name}-${span.duration_ms}`}>
            <span>{span.name}</span>
            <span>{span.duration_ms} ms</span>
            <i style={{ width: `${Math.max(6, (span.duration_ms / scale) * 100)}%` }} />
          </li>
        ))}
      </ul>
    </section>
  );
}

async function readSse(response: Response, onEvent: (event: string, data: SseData) => void) {
  const reader = response.body?.getReader();
  if (!reader) return;
  const decoder = new TextDecoder();
  let buffer = "";
  const flush = (finalChunk: boolean) => {
    buffer = buffer.replace(/\r\n/g, "\n");
    const parts = buffer.split("\n\n");
    buffer = finalChunk ? "" : (parts.pop() ?? "");
    const complete = finalChunk ? parts.filter(Boolean) : parts;
    for (const part of complete) {
      let event = "message";
      let data = "";
      for (const line of part.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;
      onEvent(event, JSON.parse(data) as SseData);
    }
  };
  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      flush(true);
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    flush(false);
  }
}

type SseData = {
  message?: string;
  text?: string;
  safe_query?: string;
  vehicles?: Vehicle[];
  finance?: Finance | null;
  recommendation_id?: string | null;
  faithful?: boolean;
} & Partial<Metrics>;
