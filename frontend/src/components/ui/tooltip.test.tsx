import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"

async function openTooltip(variant?: "inverted" | "panel") {
  render(
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger>Details</TooltipTrigger>
        <TooltipContent variant={variant}>Tooltip body</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )

  fireEvent.pointerMove(screen.getByText("Details"), { pointerType: "mouse" })
  await screen.findByRole("tooltip")
  return document.querySelector('[data-slot="tooltip-content"]')!
}

describe("TooltipContent", () => {
  it("keeps the default inverted body and arrow", async () => {
    const tooltip = await openTooltip()
    const arrow = tooltip.querySelector('[data-slot="tooltip-arrow"]')

    expect(tooltip).toHaveClass(
      "bg-foreground",
      "px-3",
      "py-1.5",
      "text-background"
    )
    expect(arrow).toHaveClass("bg-foreground", "fill-foreground")
  })

  it("uses an unpadded popover body and arrow for panel content", async () => {
    const tooltip = await openTooltip("panel")
    const arrow = tooltip.querySelector('[data-slot="tooltip-arrow"]')

    expect(tooltip).toHaveClass("bg-popover", "p-0", "text-popover-foreground")
    expect(tooltip).not.toHaveClass("bg-foreground", "px-3", "py-1.5")
    expect(arrow).toHaveClass("bg-popover", "fill-popover")
    expect(arrow).not.toHaveClass("bg-foreground", "fill-foreground")
  })
})
