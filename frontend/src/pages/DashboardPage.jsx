import { useEffect, useState } from "react";
import axios from "axios";

function DashboardPage({ setSelectedRow, setPage }) {
  const [rows, setRows] = useState([]);

  const fetchRows = async () => {
    const res = await axios.get("http://localhost:8000/api/rows/", {
      headers: {
        "X-Tenant-ID": "breathe-esg-default",
      },
    });

    setRows(res.data);
  };

  useEffect(() => {
    fetchRows();
  }, []);

  const approveRow = async (id) => {
    await axios.post(
      `http://localhost:8000/api/rows/${id}/approve/`,
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
      `http://localhost:8000/api/rows/${id}/reject/`,
      {},
      {
        headers: {
          "X-Tenant-ID": "breathe-esg-default",
        },
      }
    );

    fetchRows();
  };

  return (
    <div>
      <h2>Analyst Review Dashboard</h2>

      <div className="table-container">
        <table>
          <thead>
            <tr>
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
