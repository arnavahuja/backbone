import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type RowSelectionState,
  type SortingState,
} from '@tanstack/react-table'
import clsx from 'clsx'
import { useState } from 'react'

declare module '@tanstack/react-table' {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData, TValue> {
    numeric?: boolean
  }
}

interface Props<T> {
  data: T[]
  columns: ColumnDef<T>[]
  getRowId?: (row: T) => string
  onRowClick?: (row: T) => void
  selectable?: boolean
  selection?: RowSelectionState
  onSelectionChange?: (s: RowSelectionState) => void
  initialSorting?: SortingState
  dense?: boolean
  empty?: string
}

/** Sortable table; numeric columns (``meta.numeric``) are right-aligned and monospaced. */
export function DataTable<T>({
  data,
  columns,
  getRowId,
  onRowClick,
  selectable = false,
  selection,
  onSelectionChange,
  initialSorting = [],
  dense = false,
  empty = 'No rows',
}: Props<T>) {
  const [sorting, setSorting] = useState<SortingState>(initialSorting)
  const table = useReactTable({
    data,
    columns,
    state: { sorting, ...(selection ? { rowSelection: selection } : {}) },
    onSortingChange: setSorting,
    enableRowSelection: selectable,
    onRowSelectionChange: (updater) => {
      if (!onSelectionChange) return
      const next = typeof updater === 'function' ? updater(selection ?? {}) : updater
      onSelectionChange(next)
    },
    getRowId,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })
  const pad = dense ? 'px-2 py-1' : 'px-3 py-2'
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id} className="border-b border-border">
              {selectable && (
                <th className={clsx(pad, 'w-8')}>
                  <input
                    type="checkbox"
                    aria-label="Select all"
                    className="accent-accent"
                    checked={table.getIsAllRowsSelected()}
                    onChange={table.getToggleAllRowsSelectedHandler()}
                  />
                </th>
              )}
              {hg.headers.map((h) => {
                const numeric = h.column.columnDef.meta?.numeric
                const sorted = h.column.getIsSorted()
                return (
                  <th
                    key={h.id}
                    scope="col"
                    className={clsx(
                      pad,
                      'select-none whitespace-nowrap text-2xs font-medium uppercase tracking-wide text-muted',
                      numeric ? 'text-right' : 'text-left',
                      h.column.getCanSort() && 'cursor-pointer hover:text-secondary',
                    )}
                    onClick={h.column.getToggleSortingHandler()}
                    aria-sort={
                      sorted === 'asc' ? 'ascending' : sorted === 'desc' ? 'descending' : 'none'
                    }
                  >
                    {flexRender(h.column.columnDef.header, h.getContext())}
                    {sorted === 'asc' ? ' ▲' : sorted === 'desc' ? ' ▼' : ''}
                  </th>
                )
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.length === 0 && (
            <tr>
              <td
                colSpan={columns.length + (selectable ? 1 : 0)}
                className="px-3 py-8 text-center text-muted"
              >
                {empty}
              </td>
            </tr>
          )}
          {table.getRowModel().rows.map((row) => (
            <tr
              key={row.id}
              className={clsx(
                'border-b border-border/60 last:border-0',
                onRowClick && 'cursor-pointer hover:bg-elevated',
                row.getIsSelected() && 'bg-accent/5',
              )}
              onClick={() => onRowClick?.(row.original)}
            >
              {selectable && (
                <td className={pad} onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    aria-label="Select row"
                    className="accent-accent"
                    checked={row.getIsSelected()}
                    onChange={row.getToggleSelectedHandler()}
                  />
                </td>
              )}
              {row.getVisibleCells().map((cell) => (
                <td
                  key={cell.id}
                  className={clsx(
                    pad,
                    cell.column.columnDef.meta?.numeric && 'text-right font-mono tabular-nums',
                  )}
                >
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
