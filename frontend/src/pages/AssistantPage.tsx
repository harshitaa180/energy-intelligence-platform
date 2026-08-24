/**
 * The conversational surface.
 *
 * The assistant is grounded: it is handed the platform's computed snapshot and answers
 * only from it. That snapshot is viewable here, so any answer can be checked against
 * the numbers it was given.
 */

import { useEffect, useRef, useState } from 'react'
import { Bot, Info, Send, User } from 'lucide-react'

import { AnswerText } from '../components/AnswerText'
import {
  Callout,
  Card,
  CardHeader,
  ErrorState,
  PageHeader,
  Skeleton,
} from '../components/primitives'
import { useSite } from '../components/SiteContext'
import { useAsync } from '../hooks/useApi'
import { api } from '../services/api'
import type { AssistantAnswer } from '../types/api'
import { dateLabel } from '../utils/format'

interface Turn {
  role: 'user' | 'assistant'
  content: string
  meta?: { source: string; llm: boolean; note?: string; grounding?: string }
}

export function AssistantPage() {
  const { siteId, date, currentSite } = useSite()
  const status = useAsync(() => api.assistantStatus(), [])
  const [turns, setTurns] = useState<Turn[]>([])
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showContext, setShowContext] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)

  // A new site means a new subject; the previous conversation no longer applies.
  useEffect(() => {
    setTurns([])
  }, [siteId])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns, busy])

  async function send(text: string) {
    const trimmed = text.trim()
    if (!trimmed || !siteId || busy) return

    const history = turns.map((turn) => ({ role: turn.role, content: turn.content }))
    setTurns((current) => [...current, { role: 'user', content: trimmed }])
    setQuestion('')
    setBusy(true)
    setError(null)

    try {
      const answer: AssistantAnswer = await api.ask({
        site_id: siteId,
        question: trimmed,
        date: date ?? undefined,
        history,
      })
      setTurns((current) => [
        ...current,
        {
          role: 'assistant',
          content: answer.answer,
          meta: {
            source: answer.source,
            llm: answer.llm_available,
            note: answer.note,
            grounding: answer.grounding_note,
          },
        },
      ])
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The assistant could not answer.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="AI energy assistant"
        title={currentSite?.display_name ?? 'Assistant'}
        description={
          date
            ? `Answers are grounded in this platform's computed snapshot for ${dateLabel(date)}.`
            : undefined
        }
        action={
          <button type="button" className="btn-secondary py-1.5" onClick={() => setShowContext((v) => !v)}>
            {showContext ? 'Hide' : 'Show'} the data it sees
          </button>
        }
      />

      {status.data && !status.data.configured ? (
        <Callout tone="warning" icon={<Info size={16} />}>
          {status.data.reason}
        </Callout>
      ) : null}

      {showContext ? <ContextViewer siteId={siteId} date={date} /> : null}

      <div className="grid gap-6 lg:grid-cols-4">
        <Card className="flex min-h-[560px] flex-col lg:col-span-3">
          <CardHeader
            title="Conversation"
            action={
              status.data ? (
                <span className="chip bg-ink-100 text-ink-500">
                  {status.data.configured ? `${status.data.provider} · ${status.data.model}` : 'Rule-based'}
                </span>
              ) : null
            }
          />

          <div className="flex-1 space-y-4 overflow-y-auto p-5">
            {turns.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
                <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-accent-50 text-accent-700">
                  <Bot size={20} />
                </span>
                <p className="text-sm font-medium text-ink-700">Ask about this site's energy</p>
                <p className="max-w-md text-sm text-ink-500">
                  The assistant can only use the figures this platform computed — measured
                  consumption, the model's expected energy, the forecast, the tariff and the
                  optimiser. It will say when something is unavailable rather than guess.
                </p>
              </div>
            ) : (
              turns.map((turn, index) => (
                <div
                  key={index}
                  className={`flex gap-3 ${turn.role === 'user' ? 'justify-end' : ''}`}
                >
                  {turn.role === 'assistant' ? (
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-accent-50 text-accent-700">
                      <Bot size={15} />
                    </span>
                  ) : null}
                  <div className={`max-w-[75%] ${turn.role === 'user' ? 'order-first' : ''}`}>
                    <div
                      className={`rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                        turn.role === 'user'
                          ? 'bg-ink-900 text-white'
                          : 'bg-ink-50 text-ink-700 ring-1 ring-inset ring-ink-200/70'
                      }`}
                    >
                      {turn.role === 'assistant' ? (
                        <AnswerText text={turn.content} />
                      ) : (
                        turn.content
                      )}
                    </div>
                    {turn.meta ? (
                      <p className="mt-1.5 px-1 text-[11px] leading-relaxed text-ink-400">
                        {turn.meta.llm ? turn.meta.grounding : turn.meta.note}
                      </p>
                    ) : null}
                  </div>
                  {turn.role === 'user' ? (
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-ink-100 text-ink-500">
                      <User size={15} />
                    </span>
                  ) : null}
                </div>
              ))
            )}

            {busy ? (
              <div className="flex gap-3">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-accent-50 text-accent-700">
                  <Bot size={15} />
                </span>
                <div className="w-56 space-y-2 rounded-2xl bg-ink-50 p-4">
                  <Skeleton className="h-3 w-full" />
                  <Skeleton className="h-3 w-4/5" />
                </div>
              </div>
            ) : null}

            {error ? <ErrorState message={error} /> : null}
            <div ref={endRef} />
          </div>

          <form
            className="flex gap-2 border-t border-ink-100 p-4"
            onSubmit={(event) => {
              event.preventDefault()
              void send(question)
            }}
          >
            <label className="sr-only" htmlFor="assistant-input">
              Your question
            </label>
            <input
              id="assistant-input"
              className="field"
              placeholder="Why is my consumption high?"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              disabled={busy}
            />
            <button type="submit" className="btn-primary" disabled={busy || !question.trim()}>
              <Send size={15} />
              Ask
            </button>
          </form>
        </Card>

        <Card className="h-fit">
          <CardHeader title="Suggested questions" />
          <ul className="space-y-1.5 p-4">
            {(status.data?.suggested_prompts ?? []).map((prompt) => (
              <li key={prompt}>
                <button
                  type="button"
                  className="w-full rounded-lg px-3 py-2 text-left text-sm text-ink-600 transition-colors hover:bg-ink-50 hover:text-ink-900 disabled:opacity-50"
                  onClick={() => void send(prompt)}
                  disabled={busy}
                >
                  {prompt}
                </button>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  )
}

function ContextViewer({ siteId, date }: { siteId: string | null; date: string | null }) {
  const { data, loading, error } = useAsync(async () => {
    const response = await fetch(
      `/api/assistant/context?site_id=${siteId}${date ? `&date=${date}` : ''}`,
    )
    return (await response.json()) as Record<string, unknown>
  }, [siteId, date])

  return (
    <Card>
      <CardHeader
        title="The snapshot the assistant is given"
        subtitle="Every figure it can quote is in here. Anything absent, it must report as unavailable."
      />
      <div className="p-5">
        {error ? (
          <ErrorState message={error} />
        ) : loading || !data ? (
          <Skeleton className="h-48 w-full" />
        ) : (
          <pre className="max-h-96 overflow-auto rounded-xl bg-ink-900 p-4 font-mono text-[11px] leading-relaxed text-ink-100">
            {JSON.stringify(data, null, 2)}
          </pre>
        )}
      </div>
    </Card>
  )
}
