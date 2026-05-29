function RowDetailsPage({ row }) {
  if (!row) {
    return <p>No row selected</p>;
  }

  return (
    <div>
      <h2>Row Details (Activity #{row.id})</h2>

      <div className="details-container">
        <div className="details-column">
          <div className="panel-card">
            <h3>Raw Source Data</h3>
            <p style={{ color: "var(--text-secondary)", fontSize: "0.875rem", marginBottom: "1rem" }}>
              Messy raw data captured exactly as received from the source.
            </p>
            <pre>{JSON.stringify(row.raw_data, null, 2)}</pre>
          </div>
        </div>

        <div className="details-column">
          <div className="panel-card">
            <h3>Normalized Data</h3>
            <p style={{ color: "var(--text-secondary)", fontSize: "0.875rem", marginBottom: "1rem" }}>
              Canonical values resolved and standardized for GHG carbon accounting.
            </p>
            <pre>{JSON.stringify(row.normalized_data, null, 2)}</pre>
          </div>

          {row.validation_issues && row.validation_issues.length > 0 && (
            <div className="panel-card issues-panel">
              <h3>Validation Issues</h3>
              <p style={{ color: "var(--warning-text)", fontSize: "0.875rem", marginBottom: "1rem", fontWeight: "500" }}>
                This record contains warnings that require manual analyst attention:
              </p>
              <ul>
                {row.validation_issues.map((issue, index) => (
                  <li key={index}>{issue}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default RowDetailsPage;
