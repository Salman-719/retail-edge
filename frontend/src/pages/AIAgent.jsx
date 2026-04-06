import React from 'react'

export default function AIAgent() {
  return (
    <div className="flex-1 flex flex-col">
      <header className="bg-white border-b px-8 py-4">
        <h2 className="text-lg font-semibold text-gray-800">AI Agent</h2>
        <p className="text-sm text-gray-500">Natural language retail analytics assistant</p>
      </header>

      <div className="flex-1 flex items-center justify-center p-12">
        <div className="text-center max-w-md">
          <div className="text-6xl mb-6">🤖</div>
          <h3 className="text-2xl font-bold text-gray-700 mb-3">In Development</h3>
          <p className="text-gray-500 text-sm leading-relaxed">
            An LLM-powered conversational agent that answers natural-language questions
            about store performance — "Which zone had the highest dwell time yesterday?" —
            using live analytics data will be available in <strong>Milestone 3</strong>.
          </p>
          <div className="mt-6 inline-flex items-center gap-2 px-4 py-2 bg-blue-50 border border-blue-200 rounded-full text-blue-700 text-sm font-medium">
            <span className="w-2 h-2 rounded-full bg-blue-400"></span>
            Milestone 3 Feature
          </div>
        </div>
      </div>
    </div>
  )
}
