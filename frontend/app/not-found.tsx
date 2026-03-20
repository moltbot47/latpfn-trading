import Link from "next/link";

export default function NotFound() {
  return (
    <div style={{
      minHeight: "100vh",
      background: "#0c0c0c",
      color: "#cccccc",
      fontFamily: "'JetBrains Mono', monospace",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontSize: 12,
    }}>
      <div style={{ textAlign: "center" }}>
        <div style={{ fontSize: 48, fontWeight: 700, color: "#767676", marginBottom: 8 }}>404</div>
        <div style={{ color: "#767676", marginBottom: 24 }}>Page not found</div>
        <Link href="/" style={{ color: "#61d6d6", textDecoration: "none" }}>
          [ Home ]
        </Link>
        <span style={{ color: "#767676", margin: "0 8px" }}>|</span>
        <Link href="/terminal" style={{ color: "#61d6d6", textDecoration: "none" }}>
          [ Terminal ]
        </Link>
      </div>
    </div>
  );
}
