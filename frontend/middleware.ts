import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * 路由守卫：Cookie 里有 token 才放行。
 * 登录态用 Cookie（而非 localStorage）是因为 middleware 在服务端运行，读不到 localStorage；
 * 前端登录成功时会把同一个 token 写进 Cookie，后端 get_current_user 也优先认 Bearer、兜底读 Cookie。
 */
const PUBLIC = ["/login"];

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const token = req.cookies.get("rp_token")?.value;

  if (PUBLIC.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
    if (token) {
      const url = req.nextUrl.clone();
      url.pathname = "/";
      url.search = "";
      return NextResponse.redirect(url);
    }
    return NextResponse.next();
  }

  if (!token) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(pathname + req.nextUrl.search)}`;
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  // 排除静态资源与后端代理，其余全部走守卫
  matcher: ["/((?!_next/static|_next/image|favicon.ico|backend).*)"],
};
