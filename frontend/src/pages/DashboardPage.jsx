import { useEffect, useState } from "react";
import axios from "axios";

function DashboardPage({ setSelectedRow, setPage }) {
  const [rows, setRows] = useState([]);
  const [selectedIds, setSelectedIds] = useState([]);
  const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

  const fetchRows = async () => {
    const res = await axios.get(`${API_URL}/api/rows/`, {
      headers: {
        "X-Tenant-ID": "breathe-esg-default",
      },
    });
    setRows(res.data);
    setSelectedIds([]); // clear selection after fetch
  };

  useEffect(() => {
    fetchRows();
  }, []);

  const approveRow = async (id) => {
    await axios.post(
      `${API_URL}/api/rows/${id}/approve/`,
      {},
      {
        headers: {
          "X-Tenant-ID": "breathe-esg-default",
        },
      }
    );
    fetchRows();
  };

  const rejectRow = async (id) => {
    await axios.post(
      `${API_URL}/api/rows/${id}/reject/`,
      {},
      {
        headers: {
          "X-Tenant-ID": "breathe-esg-default",
        },
      }
    );
    fetchRows();
  };

  const handleBulkApprove = async () => {
    if (selectedIds.length === 0) return;
    try {
      await axios.post(
        `${API_URL}/api/rows/bulk-approve/`,
        { row_ids: selectedIds },
        {
          headers: {
            "X-Tenant-ID": "breathe-esg-default",
          },
        }
      );
      fetchRows();
    } catch (err) {
      alert("Bulk approval failed: " + err.message);
    }
  };

  const handleBulkReject = async () => {
    if (selectedIds.length === 0) return;
    try {
      await axios.post(
        `${API_URL}/api/rows/bulk-reject/`,
        { row_ids: selectedIds },
        {
          headers: {
            "X-Tenant-ID": "breathe-esg-default",
          },
        }
      );
      fetchRows();
    } catch (err) {
      alert("Bulk rejection failed: " + err.message);
    }
  };

  const handleExport = async (endpoint, filename) => {
    try {
      const res = await axios.get(`${API_URL}/api/${endpoint}/`, {
        headers: {
          "X-Tenant-ID": "breathe-esg-default",
        },
        responseType: "blob",
      });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", filename);
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (err) {
      alert("Export failed: " + err.message);
    }
  };

  const toggleSelectAll = () => {
    const unlockedRows = rows.filter((r) => !r.is_locked);
    if (selectedIds.length === unlockedRows.length) {
      setSelectedIds([]);
    } else {
      setSelectedIds(unlockedRows.map((r) => r.id));
    }
  };

  const toggleSelectRow = (id) => {
    if (selectedIds.includes(id)) {
      setSelectedIds(selectedIds.filter((x) => x !== id));
    } else {
      setSelectedIds([...selectedIds, id]);
    }
  };

  const unlockedRowsCount = rows.filter((r) => !r.is_locked).length;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
        <h2>Analyst Review Dashboard</h2>
        <div style={{ display: "flex", gap: "0.75rem" }}>
          <button className="btn btn-secondary" onClick={() => handleExport("export-normalized", "normalized_ledger.csv")}>
            Export Ledger CSV
          </button>
          <button className="btn btn-secondary" onClick={() => handleExport("export-audit", "audit_trail.csv")}>
            Export Audit CSV
          </button>
        </div>
      </div>

      {selectedIds.length > 0 && (
        <div className="panel-card" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "1rem", marginBottom: "1rem", border: "1px solid var(--accent-light)" }}>
          <span style={{ fontWeight: "500" }}>{selectedIds.length} row(s) selected</span>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button className="btn btn-approve" onClick={handleBulkApprove}>
              Bulk Approve
            </button>
            <button className="btn btn-reject" onClick={handleBulkReject}>
              Bulk Reject
            </button>
          </div>
        </div>
      )}

      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th style={{ width: "40px" }}>
                <input
                  type="checkbox"
                  checked={rows.length > 0 && selectedIds.length === unlockedRowsCount}
                  onChange={toggleSelectAll}
                  disabled={unlockedRowsCount === 0}
                />
              </th>
              <th style={{ width: "80px" }}>ID</th>
              <th style={{ width: "120px" }}>Source</th>
              <th style={{ width: "120px" }}>Status</th>
              <th>Validation Issues</th>
              <th style={{ width: "240px", textAlign: "right" }}>Actions</th>
            </tr>
          </thead>

          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(row.id)}
                    onChange={() => toggleSelectRow(row.id)}
                    disabled={row.is_locked}
                  />
                </td>
                <td style={{ fontWeight: "600" }}>#{row.id}</td>

                <td>
                  <span className="source-badge">{row.source_type}</span>
                </td>

                <td>
                  <span className={`badge badge-${row.status}`}>
                    {row.status === "warning" ? "flagged" : row.status}
                  </span>
                </td>

                <td>
                  {row.validation_issues && row.validation_issues.length > 0 ? (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: "0.375rem" }}>
                      {row.validation_issues.map((issue, idx) => (
                        <span key={idx} className="issue-tag">
                          {issue}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <span style={{ color: "var(--text-secondary)", fontSize: "0.8125rem", fontStyle: "italic" }}>
                      No issues detected
                    </span>
                  )}
                </td>

                <td style={{ textAlign: "right" }}>
                  <div style={{ display: "inline-flex", gap: "0.5rem" }}>
                    <button
                      className="btn-action btn-review"
                      onClick={() => {
                        setSelectedRow(row);
                        setPage("details");
                      }}
                    >
                      Review
                    </button>

                    {!row.is_locked && (
                      <>
                        <button className="btn-action btn-approve" onClick={() => approveRow(row.id)}>
                          Approve
                        </button>

                        <button className="btn-action btn-reject" onClick={() => rejectRow(row.id)}>
                          Reject
                        </button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default DashboardPage;
