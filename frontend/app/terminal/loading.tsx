export default function TerminalLoading() {
  return (
    <div style={{
      height: "100vh",
      background: "#0c0c0c",
      color: "#cccccc",
      fontFamily: "'JetBrains Mono', monospace",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontSize: 12,
    }}>
      <div style={{ textAlign: "center" }}>
        <div style={{ color: "#61d6d6", fontWeight: 700, marginBottom: 8 }}>
          LaT-PFN Terminal
        </div>
        <div style={{ color: "#767676" }}>Loading...</div>
      </div>
    </div>
  );
}
