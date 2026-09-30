/**
 * Parameter forms generated from JSON Schema (react-jsonschema-form with themed templates).
 * Never hand-code a form for a specific plugin: every plugin form goes through here.
 */
import Form, { type FormProps } from '@rjsf/core'
import type {
  ArrayFieldTemplateProps,
  BaseInputTemplateProps,
  FieldTemplateProps,
  ObjectFieldTemplateProps,
  RJSFSchema,
  RegistryWidgetsType,
  WidgetProps,
} from '@rjsf/utils'
import validator from '@rjsf/validator-ajv8'
import clsx from 'clsx'
import type { ChangeEvent } from 'react'
import { Button } from './ui'

export type JsonObject = Record<string, unknown>

function FieldTemplate(props: FieldTemplateProps) {
  const { id, label, required, rawDescription, children, rawErrors, hidden, schema } = props
  if (hidden) return <div className="hidden">{children}</div>
  const isRoot = id === 'root'
  const isBool = schema.type === 'boolean'
  const isContainer = schema.type === 'object' || schema.type === 'array'
  return (
    <div className={clsx(!isRoot && 'mb-3')}>
      {!isRoot && !isBool && !isContainer && label && (
        <label htmlFor={id} className="mb-1 block text-xs font-medium text-secondary">
          {label}
          {required && <span className="text-muted"> *</span>}
        </label>
      )}
      {children}
      {!isRoot && rawDescription && !isBool && (
        <p className="mt-1 text-2xs text-muted">{rawDescription}</p>
      )}
      {rawErrors?.map((e) => (
        <p key={e} className="mt-1 text-2xs text-negative">
          {e}
        </p>
      ))}
    </div>
  )
}

function ObjectFieldTemplate({ properties, title, idSchema }: ObjectFieldTemplateProps) {
  const isRoot = idSchema.$id === 'root'
  return (
    <fieldset className={clsx(!isRoot && 'rounded-md border border-border p-3')}>
      {!isRoot && title && <legend className="px-1 text-xs text-secondary">{title}</legend>}
      <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
        {properties.map((p) => (
          <div key={p.name}>{p.content}</div>
        ))}
      </div>
    </fieldset>
  )
}

function ArrayFieldTemplate({ items, canAdd, onAddClick, title }: ArrayFieldTemplateProps) {
  return (
    <div className="rounded-md border border-border p-3">
      {title && <div className="mb-2 text-xs text-secondary">{title}</div>}
      {items.map((item) => (
        <div key={item.key} className="mb-2 flex items-start gap-2">
          <div className="flex-1">{item.children}</div>
          {item.hasRemove && (
            <Button
              size="sm"
              variant="ghost"
              onClick={item.onDropIndexClick(item.index)}
              aria-label="Remove"
            >
              ✕
            </Button>
          )}
        </div>
      ))}
      {canAdd && (
        <Button size="sm" onClick={onAddClick}>
          + Add
        </Button>
      )}
    </div>
  )
}

const inputClass =
  'h-9 w-full rounded-md border border-border bg-canvas px-2.5 text-sm text-primary ' +
  'focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent'

function BaseInputTemplate(props: BaseInputTemplateProps) {
  const { id, required, disabled, readonly, onChange, onBlur, onFocus, schema } = props
  const value: unknown = props.value
  const rawType: unknown = props.type
  const inputType = typeof rawType === 'string' ? rawType : 'text'
  const numeric = schema.type === 'number' || schema.type === 'integer'
  const handle = (e: ChangeEvent<HTMLInputElement>) => {
    const raw = e.target.value
    if (raw === '') {
      onChange(undefined)
      return
    }
    onChange(numeric ? Number(raw) : raw)
  }
  return (
    <input
      id={id}
      name={id}
      className={clsx(inputClass, numeric && 'font-mono tabular-nums')}
      type={numeric ? 'number' : inputType}
      step={schema.type === 'integer' ? 1 : 'any'}
      value={typeof value === 'number' || typeof value === 'string' ? String(value) : ''}
      required={required}
      disabled={disabled || readonly}
      onChange={handle}
      onBlur={(e) => onBlur(id, e.target.value)}
      onFocus={(e) => onFocus(id, e.target.value)}
    />
  )
}

function CheckboxWidget({ id, value, onChange, label, disabled, schema }: WidgetProps) {
  return (
    <label
      htmlFor={id}
      className="inline-flex cursor-pointer items-center gap-2 text-sm text-secondary"
      title={schema.description}
    >
      <input
        id={id}
        type="checkbox"
        className="h-4 w-4 accent-accent"
        checked={Boolean(value)}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      {label}
    </label>
  )
}

function SelectWidget({ id, value, onChange, options, disabled }: WidgetProps) {
  const enumOptions = (options.enumOptions ?? []) as { value: unknown; label: string }[]
  const index = enumOptions.findIndex((o) => o.value === value)
  return (
    <select
      id={id}
      className={inputClass}
      value={index >= 0 ? String(index) : ''}
      disabled={disabled}
      onChange={(e) => onChange(enumOptions[Number(e.target.value)]?.value)}
    >
      {index < 0 && <option value="">—</option>}
      {enumOptions.map((o, i) => (
        <option key={o.label} value={String(i)}>
          {o.label}
        </option>
      ))}
    </select>
  )
}

const templates: FormProps['templates'] = {
  FieldTemplate,
  ObjectFieldTemplate,
  ArrayFieldTemplate,
  BaseInputTemplate,
  ErrorListTemplate: () => null,
  ButtonTemplates: { SubmitButton: () => null },
}

const widgets: RegistryWidgetsType = { CheckboxWidget, SelectWidget }

interface Props {
  schema: JsonObject
  value: JsonObject
  onChange: (value: JsonObject, valid: boolean) => void
  disabled?: boolean
}

/** Auto-generated parameter form for any plugin's JSON Schema. */
export function SchemaForm({ schema, value, onChange, disabled = false }: Props) {
  const rjsfSchema = { ...schema, title: '', description: '' } as RJSFSchema
  const hasFields = Object.keys((schema.properties as JsonObject | undefined) ?? {}).length > 0
  if (!hasFields) return <p className="text-sm text-muted">No parameters.</p>
  return (
    <Form
      schema={rjsfSchema}
      formData={value}
      validator={validator}
      templates={templates}
      widgets={widgets}
      disabled={disabled}
      liveValidate
      showErrorList={false}
      noHtml5Validate
      onChange={(e) => {
        const data = (e.formData ?? {}) as JsonObject
        onChange(data, e.errors.length === 0)
      }}
    />
  )
}
