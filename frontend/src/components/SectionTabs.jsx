export default function SectionTabs({ sections, selectedId, onChange, onAdd }) {
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
      {onAdd && (
        <button
          onClick={onAdd}
          className="w-6 h-6 rounded-full bg-gray-100 text-gray-500 hover:bg-blue-100 hover:text-blue-600 text-sm font-bold flex items-center justify-center transition-colors"
          title="Add section"
        >
          +
        </button>
      )}
    </div>
  )
}
