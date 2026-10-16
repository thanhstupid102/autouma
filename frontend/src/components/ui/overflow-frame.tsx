import * as React from "react"

import { cn } from "@/lib/utils"

function OverflowFrame({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="overflow-frame"
      className={cn(
        "min-w-0 max-w-full overflow-x-auto overscroll-x-contain",
        className
      )}
      {...props}
    />
  )
}

export { OverflowFrame }
