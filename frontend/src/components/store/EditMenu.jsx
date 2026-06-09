import React, { useEffect, useRef, useState } from 'react'
import { Pencil, Clock, MapPin, Map, ChevronDown } from 'lucide-react'

// Three-path edit menu (C3). Edits are owner/manager only (admin via A1); this
// component is only rendered when canEdit. The read view itself is open to members.
export default function EditMenu({ hasActiveVersion, hasDraft, onSchedule, onPunch, onWizard, onResumeDraft }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  const pick = (fn) => () => { setOpen(false); fn() }

  // No active config yet → primary action is Start Onboarding.
  if (!hasActiveVersion) {
    return (
      <button onClick={onWizard} className="btn-primary">
        {hasDraft ? 'Resume Setup' : 'Start Onboarding'}
      </button>
    )
  }

  const Item = ({ icon: Icon, label, sub, onClick, disabled }) => (
    <button onClick={disabled ? undefined : pick(onClick)} disabled={disabled}
      className="w-full flex items-start gap-2.5 px-3 py-2 text-left hover:bg-gray-50 disabled:opacity-40">
      <Icon size={15} className="text-gray-400 mt-0.5 shrink-0" />
      <span>
        <span className="block text-sm text-gray-800">{label}</span>
        {sub && <span className="block text-[11px] text-gray-400">{sub}</span>}
      </span>
    </button>
  )

  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen((o) => !o)} className="btn-primary flex items-center gap-1.5">
        <Pencil size={14} /> Edit <ChevronDown size={14} />
      </button>
      {open && (
        <div className="absolute right-0 mt-1 w-64 bg-white border border-gray-200 rounded-lg shadow-lg py-1 z-20">
          {hasDraft && (
            <>
              <Item icon={Map} label="Resume draft" sub="Continue the in-progress configuration" onClick={onResumeDraft} />
              <div className="border-t border-gray-100 my-1" />
            </>
          )}
          <Item icon={Clock} label="Edit Schedule" sub="Operating hours · live, no draft" onClick={onSchedule} />
          <Item icon={MapPin} label="Edit Punch Machine" sub="Versioned mini-editor" onClick={onPunch} />
          <Item icon={Map} label="Edit Floor / Zones / Cameras" sub="Full onboarding wizard" onClick={onWizard} />
        </div>
      )}
    </div>
  )
}
