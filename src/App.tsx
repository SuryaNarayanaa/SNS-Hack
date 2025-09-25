"use client";

import { SignInWithGoogle } from "./components/SignIn";

export default function App() {
  return (
    <div className="relative min-h-screen overflow-hidden bg-gradient-to-br from-slate-950 via-slate-900 to-indigo-900 text-slate-100">
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -top-20 -left-32 h-64 w-64 rounded-full bg-indigo-500/30 blur-3xl" />
        <div className="absolute bottom-24 right-0 h-80 w-80 rounded-full bg-sky-500/20 blur-3xl" />
        <div className="absolute left-1/2 top-1/2 h-40 w-80 -translate-x-1/2 -translate-y-1/2 rotate-12 rounded-full bg-white/5 blur-2xl" />
      </div>
      <main className="relative z-10 flex min-h-screen flex-col items-center justify-center px-6 py-16">
        <div className="w-full max-w-2xl space-y-10 rounded-3xl border border-white/10 bg-white/5 px-10 py-14 shadow-2xl backdrop-blur">
          <div className="space-y-4 text-center">
            <span className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-4 py-1 text-xs uppercase tracking-[0.35em] text-white/70">
              Convex Studio
            </span>
            <h1 className="text-4xl font-semibold leading-tight text-white sm:text-5xl">
              Build real-time experiences without the boilerplate
            </h1>
            <p className="mx-auto max-w-xl text-base text-white/70 sm:text-lg">
              Sign in with Google to deploy data-driven features, manage your Convex backend, and collaborate with your team in seconds.
            </p>
          </div>
          <div className="grid gap-4 text-left text-sm text-white/70 sm:grid-cols-2">
            <FeatureCard
              title="Realtime data layer"
              description="Sync state across every client instantly with Convex functions and queries."
            />
            <FeatureCard
              title="Secure auth built-in"
              description="Protect routes and APIs with Convex Auth and crystal-clear access controls."
            />
            <FeatureCard
              title="Developer velocity"
              description="Ship quickly with batteries-included tooling, hot reloads, and cloud infrastructure."
            />
            <FeatureCard
              title="Team ready"
              description="Invite collaborators, preview deployments, and monitor logs from one unified dashboard."
            />
          </div>
          <div className="flex flex-col items-center gap-3">
            <div className="w-full max-w-sm">
              <SignInWithGoogle />
            </div>
            <p className="text-xs text-white/60">
              Use your Google account to unlock the dashboard. No credit card required.
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}

function FeatureCard({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-2xl border border-white/10 bg-white/5 p-4 shadow-lg shadow-black/10">
      <h3 className="text-sm font-semibold text-white">{title}</h3>
      <p className="text-xs leading-relaxed text-white/70">{description}</p>
    </div>
  );
}
