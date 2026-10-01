import PromptComposer from "@/components/PromptComposer";

export default function Home() {
  return (
    <main className="min-h-screen bg-slate-950 text-white">
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <header className="mb-8 flex items-center justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.25em] text-emerald-400">AI Music Studio</p>
            <h1 className="mt-2 text-4xl font-bold text-white">Kikuyu Song Generator</h1>
          </div>
          <div className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-sm text-emerald-300">
            Gĩkũyũ + Kenyan Sound
          </div>
        </header>

        <PromptComposer />
      </div>
    </main>
  );
}
