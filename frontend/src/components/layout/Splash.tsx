import { useEffect, useState } from 'react'

/** Full-screen loading splash — mirrors the legacy loading screen style. */
export default function Splash() {
  const [dot, setDot] = useState(0)

  useEffect(() => {
    const id = setInterval(() => setDot(d => (d + 1) % 4), 500)
    return () => clearInterval(id)
  }, [])

  const dots = '.'.repeat(dot)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background">
      <div className="flex flex-col items-center gap-6">
        {/* Broom art — images are proxied from the backend */}
        <div className="relative flex items-end justify-center h-40 w-40">
          <img
            src="/sweep.png"
            alt=""
            className="absolute bottom-0 left-1/2 -translate-x-1/2 h-32 object-contain opacity-70"
          />
          <img
            src="/broom.png"
            alt=""
            className="relative h-28 object-contain"
          />
        </div>

        {/* Loading text */}
        <p className="text-muted-foreground text-sm tracking-wide select-none">
          Girls are preparing
          <span className="inline-block w-6 text-left">{dots}</span>
        </p>
      </div>
    </div>
  )
}
