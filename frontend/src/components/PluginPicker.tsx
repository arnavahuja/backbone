import type { Plugin } from '@/api/hooks'
import { SchemaForm, type JsonObject } from './SchemaForm'
import { Badge, Label, Select } from './ui'

export interface PluginChoice {
  name: string
  params: JsonObject
}

interface Props {
  label: string
  plugins: Plugin[]
  value: PluginChoice | null
  onChange: (value: PluginChoice | null) => void
  allowNone?: boolean
  noneLabel?: string
  id: string
}

/** Choose a plugin of one kind and edit its parameters through the generated form. */
export function PluginPicker({
  label,
  plugins,
  value,
  onChange,
  allowNone = false,
  noneLabel = 'None',
  id,
}: Props) {
  const selected = plugins.find((p) => p.name === value?.name)
  return (
    <div className="space-y-3">
      <div>
        <Label htmlFor={id}>{label}</Label>
        <Select
          id={id}
          value={value?.name ?? ''}
          onChange={(e) => onChange(e.target.value ? { name: e.target.value, params: {} } : null)}
        >
          {allowNone && <option value="">{noneLabel}</option>}
          {!allowNone && !value && <option value="">Select…</option>}
          {plugins.map((p) => (
            <option key={p.name} value={p.name}>
              {p.name} {p.origin === 'user' ? '(user)' : ''}
            </option>
          ))}
        </Select>
      </div>
      {selected && (
        <div className="space-y-3">
          <p className="text-xs text-secondary">{selected.description}</p>
          <div className="flex flex-wrap gap-1">
            {selected.capabilities.map((c) => (
              <Badge key={c}>{c}</Badge>
            ))}
            {selected.implements.map((c) => (
              <Badge key={c} tone="accent">
                {c}
              </Badge>
            ))}
          </div>
          <SchemaForm
            schema={selected.params_schema}
            value={value?.params ?? {}}
            onChange={(params) => onChange({ name: selected.name, params })}
          />
        </div>
      )}
    </div>
  )
}
