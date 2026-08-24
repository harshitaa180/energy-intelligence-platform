/**
 * Render an assistant answer.
 *
 * The system prompt asks for short paragraphs, `- ` bullets and occasional `**bold**`,
 * so this handles exactly that and nothing more. Rendering the text raw showed literal
 * asterisks; pulling in a full markdown library to fix that would be a large dependency
 * for three constructs, and would also happily render headings, tables and raw HTML that
 * the prompt forbids and the layout is not designed for.
 */

import type { ReactNode } from 'react'

/** Split on `**bold**`, keeping the delimiters so alternate segments are emphasised. */
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, index) =>
    part.startsWith('**') && part.endsWith('**') && part.length > 4 ? (
      <strong key={index} className="font-semibold text-ink-900">
        {part.slice(2, -2)}
      </strong>
    ) : (
      <span key={index}>{part}</span>
    ),
  )
}

const BULLET = /^\s*[-*•]\s+/

export function AnswerText({ text }: { text: string }) {
  const lines = text.split('\n')
  const blocks: ReactNode[] = []
  let bullets: string[] = []

  const flushBullets = () => {
    if (!bullets.length) return
    blocks.push(
      <ul key={`ul-${blocks.length}`} className="mt-2 space-y-1">
        {bullets.map((item, index) => (
          <li key={index} className="flex gap-2">
            <span className="mt-[0.55em] h-1 w-1 shrink-0 rounded-full bg-ink-400" />
            <span>{inline(item)}</span>
          </li>
        ))}
      </ul>,
    )
    bullets = []
  }

  for (const line of lines) {
    if (BULLET.test(line)) {
      bullets.push(line.replace(BULLET, ''))
      continue
    }
    flushBullets()
    if (!line.trim()) continue
    blocks.push(
      <p key={`p-${blocks.length}`} className={blocks.length ? 'mt-2' : ''}>
        {inline(line)}
      </p>,
    )
  }
  flushBullets()

  return <>{blocks}</>
}
