"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";

const NAV = [
  { href: "/", label: "总览" },
  { href: "/jobs", label: "岗位广场" },
  { href: "/applications", label: "投递看板" },
];

export function AppShell({
  children,
  wide,
}: {
  children: React.ReactNode;
  wide?: boolean;
}) {
  const pathname = usePathname();
  const { user, signOut } = useAuth();
  const [menu, setMenu] = useState(false);

  return (
    <div className="flex min-h-screen flex-col bg-paper">
      <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-white/85 backdrop-blur-md">
        <div
          className={cn(
            "mx-auto flex h-14 items-center gap-6 px-5",
            wide ? "max-w-[1600px]" : "max-w-6xl",
          )}
        >
          <Link href="/" className="flex items-center gap-2.5">
            <div className="grid h-8 w-8 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-[15px] font-bold text-white shadow-sm">
              R
            </div>
            <div className="leading-tight">
              <div className="text-[15px] font-semibold tracking-tight">ResumePilot</div>
              <div className="text-[10px] font-medium tracking-wide text-brand-600">PRO · 全链路</div>
            </div>
          </Link>

          <nav className="flex items-center gap-1">
            {NAV.map((item) => {
              const active =
                item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "relative rounded-lg px-3 py-1.5 text-[12.5px] font-medium transition",
                    active
                      ? "bg-brand-50 text-brand-700"
                      : "text-slate-500 hover:bg-slate-50 hover:text-ink",
                  )}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="relative ml-auto">
            <button
              onClick={() => setMenu((v) => !v)}
              className="flex items-center gap-2 rounded-full border border-slate-200 bg-white py-1 pl-1 pr-2.5 transition hover:border-slate-300"
            >
              <span className="grid h-6 w-6 place-items-center rounded-full bg-brand-100 text-[11px] font-semibold text-brand-700">
                {(user?.display_name || user?.email || "U").slice(0, 1).toUpperCase()}
              </span>
              <span className="max-w-[110px] truncate text-[12px] text-slate-600">
                {user?.display_name || user?.email || "未登录"}
              </span>
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" className="text-slate-400">
                <path d="m6 9 6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>

            {menu && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setMenu(false)} />
                <div className="absolute right-0 z-20 mt-1.5 w-56 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-card">
                  <div className="border-b border-slate-100 px-3 py-2">
                    <div className="truncate text-[12px] font-medium text-ink">
                      {user?.display_name}
                    </div>
                    <div className="truncate text-[11px] text-slate-400">{user?.email}</div>
                  </div>
                  <Link
                    href="/applications"
                    onClick={() => setMenu(false)}
                    className="block px-3 py-2 text-[12px] text-slate-600 hover:bg-slate-50"
                  >
                    我的投递
                  </Link>
                  <button
                    onClick={signOut}
                    className="block w-full px-3 py-2 text-left text-[12px] text-rose-600 hover:bg-rose-50"
                  >
                    退出登录
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </header>

      <main className={cn("mx-auto w-full flex-1 px-5 py-6", wide ? "max-w-[1600px]" : "max-w-6xl")}>
        {children}
      </main>
    </div>
  );
}
