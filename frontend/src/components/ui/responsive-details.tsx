import * as React from "react"
import { Popover as PopoverPrimitive } from "radix-ui"

import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

const finePointerQuery = "(hover: hover) and (pointer: fine)"

function useFinePointer() {
  const [isFinePointer, setIsFinePointer] = React.useState(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(finePointerQuery).matches
      : false
  )

  React.useEffect(() => {
    if (typeof window.matchMedia !== "function") return
    const query = window.matchMedia(finePointerQuery)
    const update = (event: MediaQueryListEvent) => setIsFinePointer(event.matches)
    query.addEventListener("change", update)
    return () => query.removeEventListener("change", update)
  }, [])

  return isFinePointer
}

interface ResponsiveDetailsProps {
  children: React.ReactElement
  content: React.ReactNode
  label?: string
  className?: string
  touchTrigger?: React.ReactElement
  contentVariant?: React.ComponentProps<typeof TooltipContent>["variant"]
  tooltipSide?: React.ComponentProps<typeof TooltipContent>["side"]
  tooltipSideOffset?: number
  popoverSide?: React.ComponentProps<typeof PopoverPrimitive.Content>["side"]
  popoverSideOffset?: number
}

function ResponsiveDetails({
  children,
  content,
  label = "Details",
  className,
  touchTrigger,
  contentVariant = "inverted",
  tooltipSide = "top",
  tooltipSideOffset = 6,
  popoverSide = "top",
  popoverSideOffset = 8,
}: ResponsiveDetailsProps) {
  const isFinePointer = useFinePointer()

  if (isFinePointer) {
    return (
      <div data-slot="responsive-details" data-mode="fine" className={className}>
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>{children}</TooltipTrigger>
            <TooltipContent
              variant={contentVariant}
              side={tooltipSide}
              sideOffset={tooltipSideOffset}
            >
              {content}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>
    )
  }

  return (
    <div data-slot="responsive-details" data-mode="touch" className={cn("relative", className)}>
      {children}
      <PopoverPrimitive.Root>
        <span
          data-slot="responsive-details-touch-trigger"
          className="inline-flex"
          onClick={(event) => event.stopPropagation()}
        >
          <PopoverPrimitive.Trigger asChild>
            {touchTrigger ?? (
              <Button type="button" size="sm" variant="outline">
                {label}
              </Button>
            )}
          </PopoverPrimitive.Trigger>
        </span>
        <PopoverPrimitive.Portal>
          <PopoverPrimitive.Content
            data-slot="responsive-details-panel"
            role="dialog"
            aria-label={label}
            side={popoverSide}
            sideOffset={popoverSideOffset}
            collisionPadding={8}
            className={cn(
              "z-50 max-h-[calc(100dvh-2rem)] w-[min(24rem,calc(100vw-2rem))] overflow-y-auto overscroll-y-contain bg-popover text-popover-foreground outline-none",
              contentVariant === "panel"
                ? "rounded-md p-0"
                : "rounded-xl border border-border p-4 text-sm shadow-lg"
            )}
          >
            {content}
            <PopoverPrimitive.Arrow
              data-slot="responsive-details-arrow"
              className="fill-popover"
            />
          </PopoverPrimitive.Content>
        </PopoverPrimitive.Portal>
      </PopoverPrimitive.Root>
    </div>
  )
}

export { ResponsiveDetails }
