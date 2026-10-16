import * as React from "react"

import { cn } from "@/lib/utils"

type TouchControlProps = {
  id?: string
  disabled?: boolean
  "aria-describedby"?: string
}

interface TouchControlRowProps
  extends Omit<React.ComponentProps<"label">, "children"> {
  label: React.ReactNode
  description?: React.ReactNode
  control: React.ReactElement<TouchControlProps>
  disabled?: boolean
  disabledReason?: React.ReactNode
}

function TouchControlRow({
  className,
  label,
  description,
  control,
  disabled = false,
  disabledReason,
  ...props
}: TouchControlRowProps) {
  const generatedId = React.useId()
  const controlId = control.props.id ?? `touch-control-${generatedId}`
  const isDisabled = disabled || control.props.disabled === true
  const descriptionId = description ? `${controlId}-description` : undefined
  const reasonId = isDisabled && disabledReason ? `${controlId}-disabled-reason` : undefined
  const describedBy = [
    control.props["aria-describedby"],
    descriptionId,
    reasonId,
  ].filter(Boolean).join(" ") || undefined

  return (
    <label
      htmlFor={controlId}
      data-slot="touch-control-row"
      data-disabled={isDisabled || undefined}
      className={cn(
        "flex min-h-11 w-full cursor-pointer items-center gap-3 rounded-lg px-2 py-2 text-sm",
        "has-focus-visible:ring-3 has-focus-visible:ring-ring/50",
        isDisabled && "cursor-not-allowed",
        className
      )}
      {...props}
    >
      <span className="min-w-0 flex-1">
        <span className={cn("block font-medium", isDisabled && "text-muted-foreground")}>
          {label}
        </span>
        {description && (
          <span
            id={descriptionId}
            className="mt-0.5 block text-xs text-muted-foreground"
          >
            {description}
          </span>
        )}
        {isDisabled && disabledReason && (
          <span
            id={reasonId}
            data-slot="touch-control-disabled-reason"
            className="mt-1 block text-xs text-muted-foreground"
          >
            {disabledReason}
          </span>
        )}
      </span>
      {React.cloneElement(control, {
        id: controlId,
        disabled: isDisabled,
        "aria-describedby": describedBy,
      })}
    </label>
  )
}

export { TouchControlRow }
