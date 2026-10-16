import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { RacePickerDialog } from "./RacePickerDialog"
import { SkillEditorDialog } from "./SkillEditorDialog"
import type { Slot } from "./raceRules"

const mocks = vi.hoisted(() => ({
  getSkills: vi.fn().mockResolvedValue({ success: true, skills: [] }),
  getActive: vi.fn().mockReturnValue(undefined),
  update: vi.fn(),
}))

vi.mock("@/api/presets", () => ({ getSkills: mocks.getSkills }))
vi.mock("@/stores/presets", () => ({
  usePresets: () => ({ getActive: mocks.getActive, update: mocks.update }),
}))

describe("custom dialog shell compatibility", () => {
  it("uses the shared full-screen Skill Editor shell and restores its 95dvh desktop frame", async () => {
    render(<SkillEditorDialog open onOpenChange={vi.fn()} />)

    const dialog = screen.getByRole("dialog")
    expect(dialog).toHaveClass(
      "h-dvh",
      "max-h-dvh",
      "overflow-hidden",
      "md:h-[95dvh]",
      "md:max-h-[95dvh]",
      "md:rounded-xl",
    )
    expect(dialog).toHaveAttribute("data-size", "full-screen")
    await waitFor(() => expect(mocks.getSkills).toHaveBeenCalled())
  })

  it("moves Race Picker scrolling into DialogBody while keeping its header and footer outside", () => {
    const onOpenChange = vi.fn()
    const onToggle = vi.fn()
    const slot: Slot = {
      label: "Early Jan",
      period: "Early",
      month: "Jan",
      yearIdx: 0,
      races: [
        {
          id: 1,
          name: "Debut",
          date: "Junior Year Early Jan",
          type: "G1",
          terrain: "Turf",
          distance: 1600,
        },
      ],
    }

    render(
      <RacePickerDialog
        open
        onOpenChange={onOpenChange}
        slot={slot}
        selectedRaces={[]}
        onToggle={onToggle}
      />
    )

    const dialog = screen.getByRole("dialog")
    const header = dialog.querySelector<HTMLElement>('[data-slot="dialog-header"]')
    const body = dialog.querySelector<HTMLElement>('[data-slot="dialog-body"]')
    const footer = dialog.querySelector<HTMLElement>('[data-slot="dialog-footer"]')
    const raceButton = within(body!).getByRole("button", { name: /debut/i })

    expect(dialog).toHaveClass(
      "max-h-[calc(100dvh-2rem)]",
      "has-data-[slot=dialog-body]:overflow-hidden",
      "sm:max-w-lg",
      "md:max-h-[80vh]",
    )
    expect(dialog).not.toHaveClass("max-h-[80vh]")
    expect(header).toHaveClass("sticky", "top-0", "pr-10", "md:static", "md:pr-0")
    expect(body).toHaveClass("overflow-y-auto", "py-1", "md:py-0")
    expect(footer).toHaveClass("md:hidden")
    expect(body?.contains(header)).toBe(false)
    expect(body?.contains(footer)).toBe(false)
    expect(header?.nextElementSibling).toBe(body)
    expect(body?.nextElementSibling).toBe(footer)

    fireEvent.click(raceButton)
    expect(onToggle).toHaveBeenCalledWith(slot.races[0], [1])

    fireEvent.click(within(footer!).getByRole("button", { name: "Done" }))
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })
})
