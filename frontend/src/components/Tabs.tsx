import { For } from 'solid-js'
import type { MediaKind } from '../types'

interface Props {
  kind: MediaKind
  onKind: (kind: MediaKind) => void
  counts: Partial<Record<MediaKind, number>>
}

const TABS: { value: MediaKind; label: string }[] = [
  { value: 'movies', label: 'Movies' },
  { value: 'series', label: 'Series' },
]

export default function Tabs(props: Props) {
  // Left/right arrows move between tabs the way a real tablist does; each tab is
  // still a plain button, so Tab and Enter work as usual.
  const step = (delta: number) => {
    const index = TABS.findIndex((tab) => tab.value === props.kind)
    const next = TABS[(index + delta + TABS.length) % TABS.length]
    props.onKind(next.value)
  }

  return (
    <nav class="tabs" role="tablist" aria-label="Library">
      <For each={TABS}>
        {(tab) => (
          <button
            type="button"
            role="tab"
            class="tab"
            classList={{ active: props.kind === tab.value }}
            aria-selected={props.kind === tab.value}
            tabIndex={props.kind === tab.value ? 0 : -1}
            onClick={() => props.onKind(tab.value)}
            onKeyDown={(event) => {
              if (event.key === 'ArrowRight') step(1)
              if (event.key === 'ArrowLeft') step(-1)
            }}
          >
            {tab.label}
            {props.counts[tab.value] !== undefined && (
              <span class="tab-count">{props.counts[tab.value]}</span>
            )}
          </button>
        )}
      </For>
    </nav>
  )
}
