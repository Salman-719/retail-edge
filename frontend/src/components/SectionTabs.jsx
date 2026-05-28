export default function SectionTabs({ sections, selectedId, onChange }) {
  if (!sections || sections.length <= 1) return null
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {sections.map(s => (
        <button
          key={s.id}
          onClick={() => onChange(s.id)}
          className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
            s.id === selectedId
              ? 'bg-blue-600 text-white'
              : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
          }`}
        >
          {s.name}
        </button>
      ))}
    </div>
  )
}
