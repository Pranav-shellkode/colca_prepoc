import type { Disposition } from './api'

export const DISPOSITIONS: Disposition[] = [
  'Interested',
  'Not Interested',
  'Follow-up Required',
  'Meeting Booked',
]

interface DispositionStyle {
  label: string
  dot: string
  fg: string
  bg: string
  border: string
}

const STYLES: Record<Disposition, DispositionStyle> = {
  'Meeting Booked': {
    label: 'Meeting booked',
    dot: 'var(--gold)',
    fg: '#fcc057',
    bg: 'rgba(252, 192, 87, 0.14)',
    border: 'rgba(252, 192, 87, 0.35)',
  },
  Interested: {
    label: 'Interested',
    dot: 'var(--teal-mid)',
    fg: '#5fb8ab',
    bg: 'rgba(45, 127, 116, 0.16)',
    border: 'rgba(45, 127, 116, 0.38)',
  },
  'Follow-up Required': {
    label: 'Follow-up required',
    dot: 'var(--olive)',
    fg: '#c7c785',
    bg: 'rgba(166, 166, 93, 0.14)',
    border: 'rgba(166, 166, 93, 0.34)',
  },
  'Not Interested': {
    label: 'Not interested',
    dot: 'var(--slate-muted)',
    fg: '#9db3b3',
    bg: 'rgba(92, 122, 122, 0.16)',
    border: 'rgba(92, 122, 122, 0.34)',
  },
}

export function dispositionStyle(outcome: Disposition | null | undefined): DispositionStyle {
  if (outcome && STYLES[outcome]) return STYLES[outcome]
  return {
    label: 'Pending',
    dot: 'var(--text-3)',
    fg: 'var(--text-3)',
    bg: 'transparent',
    border: 'var(--border)',
  }
}