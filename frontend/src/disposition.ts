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
    dot: 'var(--violet)',
    fg: '#c4b5fd',
    bg: 'rgba(139, 92, 246, 0.14)',
    border: 'rgba(139, 92, 246, 0.35)',
  },
  Interested: {
    label: 'Interested',
    dot: 'var(--green)',
    fg: '#86efac',
    bg: 'rgba(34, 197, 94, 0.12)',
    border: 'rgba(34, 197, 94, 0.32)',
  },
  'Follow-up Required': {
    label: 'Follow-up required',
    dot: 'var(--amber)',
    fg: '#fcd34d',
    bg: 'rgba(245, 158, 11, 0.12)',
    border: 'rgba(245, 158, 11, 0.32)',
  },
  'Not Interested': {
    label: 'Not interested',
    dot: 'var(--slate-muted)',
    fg: '#94a3b8',
    bg: 'rgba(100, 116, 139, 0.14)',
    border: 'rgba(100, 116, 139, 0.32)',
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