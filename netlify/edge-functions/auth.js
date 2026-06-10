const COOKIE_NAME = "album_editor_auth";

async function sha256(value) {
  const data = new TextEncoder().encode(value);
  const hash = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(hash))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function readCookie(request, name) {
  const cookie = request.headers.get("cookie") || "";
  const found = cookie
    .split(";")
    .map((item) => item.trim())
    .find((item) => item.startsWith(`${name}=`));
  return found ? decodeURIComponent(found.split("=").slice(1).join("=")) : "";
}

function json(payload, status = 200, headers = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      ...headers,
    },
  });
}

async function sessionToken() {
  const password = Deno.env.get("ACCESS_PASSWORD") || "";
  const secret = Deno.env.get("ACCESS_SESSION_SECRET") || password;
  return sha256(`${password}:${secret}`);
}

async function isAuthenticated(request) {
  const expected = await sessionToken();
  return Boolean(expected) && readCookie(request, COOKIE_NAME) === expected;
}

async function proxyApi(request, url) {
  const backendOrigin = Deno.env.get("BACKEND_ORIGIN");
  if (!backendOrigin) {
    return json(
      {
        error:
          "BACKEND_ORIGIN não foi configurado na Netlify. Hospede o app Python separadamente e aponte essa variável para ele.",
      },
      501,
    );
  }

  const target = new URL(url.pathname + url.search, backendOrigin);
  const headers = new Headers(request.headers);
  headers.delete("host");

  return fetch(target, {
    method: request.method,
    headers,
    body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
    redirect: "manual",
  });
}

export default async (request, context) => {
  const url = new URL(request.url);

  if (url.pathname === "/api/login" && request.method === "POST") {
    const expectedPassword = Deno.env.get("ACCESS_PASSWORD");
    if (!expectedPassword) {
      return json({ error: "ACCESS_PASSWORD não foi configurada na Netlify." }, 500);
    }

    let payload = {};
    try {
      payload = await request.json();
    } catch {
      return json({ error: "Requisição inválida." }, 400);
    }

    if (payload.password !== expectedPassword) {
      return json({ error: "Senha incorreta." }, 401);
    }

    const token = await sessionToken();
    return json(
      { ok: true },
      200,
      {
        "set-cookie": `${COOKIE_NAME}=${encodeURIComponent(
          token,
        )}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=86400`,
      },
    );
  }

  if (url.pathname === "/api/logout") {
    return json(
      { ok: true },
      200,
      {
        "set-cookie": `${COOKIE_NAME}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0`,
      },
    );
  }

  if (url.pathname === "/login.html") {
    return context.next();
  }

  if (!(await isAuthenticated(request))) {
    if (url.pathname.startsWith("/api/")) {
      return json({ error: "Acesso bloqueado. Faça login primeiro." }, 401);
    }
    return Response.redirect(new URL("/login.html", url.origin), 302);
  }

  if (url.pathname.startsWith("/api/")) {
    return proxyApi(request, url);
  }

  return context.next();
};

