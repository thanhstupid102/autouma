import { fireEvent, render, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { OverflowFrame } from "@/components/ui/overflow-frame"
import { ResponsiveDetails } from "@/components/ui/responsive-details"
import {
  Select,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { TouchControlRow } from "@/components/ui/touch-control-row"

function setFinePointer(matches: boolean) {
  const mediaQuery = {
    matches,
    media: "(hover: hover) and (pointer: fine)",
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  } satisfies MediaQueryList
  vi.stubGlobal("matchMedia", vi.fn(() => mediaQuery))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("responsive control variants", () => {
  it("gives every button size a phone target and restores its compact size at md", () => {
    const cases = [
      ["default", "h-11", "md:h-8"],
      ["xs", "h-11", "md:h-6"],
      ["sm", "h-11", "md:h-7"],
      ["lg", "h-11", "md:h-9"],
      ["icon", "size-11", "md:size-8"],
      ["icon-xs", "size-11", "md:size-6"],
      ["icon-sm", "size-11", "md:size-7"],
      ["icon-lg", "size-11", "md:size-9"],
    ] as const

    for (const [size, mobileClass, compactClass] of cases) {
      const { unmount } = render(<Button size={size}>{size}</Button>)
      const button = screen.getByRole("button", { name: size })
      expect(button).toHaveClass(mobileClass, compactClass)
      unmount()
    }
  })

  it("keeps input text at 16px below md while restoring the old height at md", () => {
    render(<Input aria-label="Name" />)
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveClass(
      "h-11",
      "md:h-8",
      "text-base",
      "md:text-sm"
    )
  })

  it("gives both select trigger sizes a phone height and their old compact heights at md", () => {
    const { rerender } = render(
      <Select>
        <SelectTrigger aria-label="Default select">
          <SelectValue placeholder="Choose" />
        </SelectTrigger>
      </Select>
    )
    expect(screen.getByRole("combobox", { name: "Default select" })).toHaveClass(
      "h-11",
      "md:data-[size=default]:h-8"
    )

    rerender(
      <Select>
        <SelectTrigger aria-label="Small select" size="sm">
          <SelectValue placeholder="Choose" />
        </SelectTrigger>
      </Select>
    )
    expect(screen.getByRole("combobox", { name: "Small select" })).toHaveClass(
      "h-11",
      "md:data-[size=sm]:h-7"
    )
  })

  it("enlarges checkbox and switch targets on phones and restores compact visuals at md", () => {
    render(
      <>
        <Checkbox aria-label="Enabled" />
        <Switch aria-label="Automatic" />
        <Switch aria-label="Compact automatic" size="sm" />
      </>
    )

    expect(screen.getByRole("checkbox", { name: "Enabled" })).toHaveClass(
      "size-5",
      "md:size-4",
      "after:size-11",
      "md:after:-inset-y-2"
    )
    expect(screen.getByRole("switch", { name: "Automatic" })).toHaveClass(
      "data-[size=default]:h-6",
      "data-[size=default]:w-11",
      "md:data-[size=default]:h-[18.4px]",
      "md:data-[size=default]:w-[32px]",
      "after:size-11"
    )
    expect(screen.getByRole("switch", { name: "Compact automatic" })).toHaveClass(
      "data-[size=sm]:h-5",
      "data-[size=sm]:w-9",
      "md:data-[size=sm]:h-[14px]",
      "md:data-[size=sm]:w-[24px]"
    )
  })
})

describe("TouchControlRow", () => {
  it("toggles the control when the label text is clicked", () => {
    render(
      <TouchControlRow
        label="Enable retries"
        description="Try the action again after a transient failure."
        control={<Checkbox />}
      />
    )

    const checkbox = screen.getByRole("checkbox")
    expect(checkbox).not.toBeChecked()
    fireEvent.click(screen.getByText("Enable retries"))
    expect(checkbox).toBeChecked()
  })

  it("renders a disabled reason as described text rather than a title", () => {
    render(
      <TouchControlRow
        label="Use saved session"
        control={<Switch />}
        disabled
        disabledReason="Sign in before enabling this option."
      />
    )

    const row = screen.getByText("Use saved session").closest("label")
    const reason = screen.getByText("Sign in before enabling this option.")
    const control = screen.getByRole("switch")
    expect(reason).toBeVisible()
    expect(row).not.toHaveAttribute("title")
    expect(control).toBeDisabled()
    expect(control).toHaveAttribute("aria-describedby", reason.id)
  })
})

describe("dialog shell", () => {
  it("keeps the body scrollable, the footer as a sibling, and the close target at 44px", () => {
    render(
      <Dialog open>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Long dialog</DialogTitle>
          </DialogHeader>
          <DialogBody data-testid="dialog-body">Long content</DialogBody>
          <DialogFooter data-testid="dialog-footer">Actions</DialogFooter>
        </DialogContent>
      </Dialog>
    )

    const dialog = screen.getByRole("dialog")
    const body = screen.getByTestId("dialog-body")
    const footer = screen.getByTestId("dialog-footer")
    const close = within(dialog).getByRole("button", { name: "Close" })
    expect(dialog).toHaveClass(
      "max-h-[calc(100dvh-2rem)]",
      "has-data-[slot=dialog-body]:overflow-hidden"
    )
    expect(body).toHaveClass("min-h-0", "flex-1", "overflow-y-auto")
    expect(body.parentElement).toBe(footer.parentElement)
    expect(body).not.toContainElement(footer)
    expect(close).toHaveClass("size-11")
    expect(close.querySelector("svg")).toHaveClass("size-4")
  })

  it("renders the full-screen size distinctly from the standard size", () => {
    render(
      <>
        <Dialog open>
          <DialogContent data-testid="standard-dialog" showCloseButton={false}>
            <DialogTitle>Standard</DialogTitle>
          </DialogContent>
        </Dialog>
        <Dialog open>
          <DialogContent
            data-testid="full-screen-dialog"
            showCloseButton={false}
            size="full-screen"
          >
            <DialogTitle>Full screen</DialogTitle>
          </DialogContent>
        </Dialog>
      </>
    )

    expect(screen.getByTestId("standard-dialog")).toHaveAttribute("data-size", "default")
    expect(screen.getByTestId("standard-dialog")).toHaveClass(
      "max-h-[calc(100dvh-2rem)]",
      "rounded-xl"
    )
    expect(screen.getByTestId("full-screen-dialog")).toHaveAttribute(
      "data-size",
      "full-screen"
    )
    expect(screen.getByTestId("full-screen-dialog")).toHaveClass(
      "inset-0",
      "h-dvh",
      "max-h-dvh",
      "rounded-none"
    )
  })
})

describe("OverflowFrame", () => {
  it("contains horizontal scrolling without assigning an over-wide width", () => {
    render(<OverflowFrame data-testid="overflow-frame">Wide content</OverflowFrame>)
    const frame = screen.getByTestId("overflow-frame")
    expect(frame).toHaveClass(
      "min-w-0",
      "max-w-full",
      "overflow-x-auto",
      "overscroll-x-contain"
    )
    expect(frame.className).not.toMatch(/(?:^|\s)(?:w-screen|min-w-max)(?:\s|$)/)
  })
})

describe("ResponsiveDetails", () => {
  it("renders an explicit trigger on touch and opens its popover panel", () => {
    setFinePointer(false)
    render(
      <ResponsiveDetails label="Lineage details" content={<p>Spark lineage</p>}>
        <button type="button">Parent card</button>
      </ResponsiveDetails>
    )

    const trigger = screen.getByRole("button", { name: "Lineage details" })
    expect(trigger).toBeVisible()
    expect(trigger.closest('[data-mode="touch"]')).toBeInTheDocument()
    fireEvent.click(trigger)
    const panel = screen.getByRole("dialog", { name: "Lineage details" })
    expect(panel).toHaveTextContent("Spark lineage")
    expect(panel).toHaveClass("border", "bg-popover", "p-4", "shadow-lg")
  })

  it("keeps the tooltip trigger path on a fine pointer", () => {
    setFinePointer(true)
    render(
      <ResponsiveDetails label="Lineage details" content={<p>Spark lineage</p>}>
        <button type="button">Parent card</button>
      </ResponsiveDetails>
    )

    const target = screen.getByRole("button", { name: "Parent card" })
    expect(target.closest('[data-mode="fine"]')).toBeInTheDocument()
    expect(target).toHaveAttribute("data-slot", "tooltip-trigger")
    expect(screen.queryByRole("button", { name: "Lineage details" })).not.toBeInTheDocument()
  })
})
