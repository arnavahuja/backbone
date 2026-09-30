import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface CompareState {
  selected: string[]
  toggle: (id: string) => void
  setSelected: (ids: string[]) => void
  clear: () => void
}

/** Runs selected for comparison (persisted in the browser). */
export const useCompareStore = create<CompareState>()(
  persist(
    (set) => ({
      selected: [],
      toggle: (id) =>
        set((s) => ({
          selected: s.selected.includes(id)
            ? s.selected.filter((x) => x !== id)
            : [...s.selected, id],
        })),
      setSelected: (ids) => set({ selected: ids }),
      clear: () => set({ selected: [] }),
    }),
    { name: 'backbone-compare', version: 1 },
  ),
)
