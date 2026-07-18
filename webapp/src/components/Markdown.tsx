/** Minimal markdown renderer ported from the design prototype. */
export function Markdown({ source }: { source: string }) {
  const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inl = (s: string) =>
    esc(s)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(
        /`(.+?)`/g,
        '<code style="font-family:IBM Plex Mono;font-size:.9em;background:#f1f3f4;padding:1px 4px;border-radius:3px">$1</code>'
      );
  const out: string[] = [];
  let ul = false;
  const closeUl = () => {
    if (ul) {
      out.push("</ul>");
      ul = false;
    }
  };
  for (const ln of source.split("\n")) {
    if (/^### /.test(ln)) {
      closeUl();
      out.push('<h3 style="font-size:13px;font-weight:600;margin:16px 0 6px">' + inl(ln.slice(4)) + "</h3>");
    } else if (/^## /.test(ln)) {
      closeUl();
      out.push('<h2 style="font-size:15px;font-weight:600;margin:20px 0 7px;color:#0e7490">' + inl(ln.slice(3)) + "</h2>");
    } else if (/^# /.test(ln)) {
      closeUl();
      out.push('<h1 style="font-size:19px;font-weight:700;margin:0 0 10px">' + inl(ln.slice(2)) + "</h1>");
    } else if (/^\d+\. /.test(ln) || /^- /.test(ln)) {
      if (!ul) {
        out.push('<ul style="margin:4px 0 4px;padding-left:20px">');
        ul = true;
      }
      out.push(
        '<li style="margin:3px 0;font-size:12.5px;line-height:1.5">' + inl(ln.replace(/^(-|\d+\.) /, "")) + "</li>"
      );
    } else if (ln.trim() === "") {
      closeUl();
    } else {
      closeUl();
      out.push('<p style="font-size:12.5px;line-height:1.6;margin:7px 0;color:#374151">' + inl(ln) + "</p>");
    }
  }
  closeUl();
  return <div dangerouslySetInnerHTML={{ __html: out.join("") }} />;
}
