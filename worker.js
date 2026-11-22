/*
 * Local copy of the Cloudflare Worker serving the Ubuntu MATE Community Archive.
*/

// [pattern, builder] — first match wins
const RULES = [
  // /t/31342/4  (id + post number) -> /t/31342
  [/^\/t\/(\d+)\/\d+$/, (m) => `/t/${m[1]}`],

  // /t/some-slug/31342  or  /t/some-slug/31342/4 -> /t/31342
  [/^\/t\/[^/]+\/(\d+)(?:\/\d+)?$/, (m) => `/t/${m[1]}`],

  // /c/feedback/31  or  /c/support/raspberry-pi/19 -> /c/31, /c/19
  [/^\/c\/.+\/(\d+)$/, (m) => `/c/${m[1]}`],

  // /tag/24-04-noble-lts/150 -> /tags/24-04-noble-lts
  [/^\/tag\/([^/]+)\/\d+$/, (m) => `/tags/${m[1]}`],

  // /u -> /users
  [/^\/u$/, () => "/users"],

  // /u/wimpy/summary|activity|badges -> /u/wimpy
  [/^\/u\/([^/]+)\/(?:summary|activity|badges)$/, (m) => `/u/${m[1]}`],

  // /badges/9/autobiographer -> /badge/9
  [/^\/badges\/(\d+)(?:\/[^/]*)?$/, (m) => `/badge/${m[1]}`],

  // Misc
  [/^\/categories$/, () => "/"],
  [/^\/latest$/, () => "/"],
  [/^\/faq$/, () => "/t/5"],
  [/^\/tos$/, () => "/t/4"],
  [/^\/privacy$/, () => "/t/6"],
];

export default {
  async fetch(request, env) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method Not Allowed", {
        status: 405,
        headers: { Allow: "GET, HEAD" },
      });
    }

    const url = new URL(request.url);
    let path = url.pathname;

    // Normalise trailing slash (except root)
    if (path.length > 1 && path.endsWith("/"))
      path = path.slice(0, -1);

    // Redirect rules
    for (const [re, build] of RULES) {
      const m = path.match(re);
      if (m)
        return redirect(url, build(m));
    }

    // /anything.html -> /anything (canonical clean URL)
    if (path.endsWith(".html") && path !== "/index.html") {
      return redirect(url, path.slice(0, -5));
    }

    // Work out the R2 key
    const isIndex = path === "/" || path === "/index.html";
    let key = isIndex ? "index.html" : decodeURIComponent(path.slice(1));
    const tryHtml = !isIndex && key.split("/").pop().includes(".");
    if (!isIndex && !tryHtml)
      key += ".html";

    const conditions = new Headers(request.headers);
    if (conditions.has("if-match")) conditions.delete("if-unmodified-since");
    if (conditions.has("if-none-match")) conditions.delete("if-modified-since");

    let object = await env.BUCKET.get(key, { onlyIf: conditions });
    if (object === null && tryHtml) {
      object = await env.BUCKET.get(`${key}.html`, { onlyIf: conditions });
    }
    if (object === null) {
      const notFound = await env.BUCKET.get("404.html");
      if (notFound === null) {
        console.error("Missing 404.html in R2 bucket");
        return new Response(request.method === "HEAD" ? null : "Not Found", { status: 404 });
      }
      const headers = new Headers();
      notFound.writeHttpMetadata(headers);
      return new Response(request.method === "HEAD" ? null : notFound.body, {
        status: 404,
        headers,
      });
    }

    const headers = new Headers();
    object.writeHttpMetadata(headers);
    headers.set("etag", object.httpEtag);
    headers.set("cache-control", "public, max-age=604800");

    if (!object.body) {
      const ifMatch = conditions.get("if-match");
      const unmodifiedSince = conditions.get("if-unmodified-since");
      const preconditionFailed = ifMatch !== null
        ? ifMatch.trim() !== "*" && !ifMatch.split(",").some((tag) => tag.trim() === object.httpEtag)
        : unmodifiedSince !== null && Math.floor(object.uploaded.getTime() / 1000) > Date.parse(unmodifiedSince) / 1000;
      return new Response(null, { status: preconditionFailed ? 412 : 304, headers });
    }

    return new Response(request.method === "HEAD" ? null : object.body, {
      headers,
    });
  },
};

function redirect(url, newPath) {
  const target = new URL(url);
  target.pathname = newPath;
  return Response.redirect(target.toString(), 302);
}
