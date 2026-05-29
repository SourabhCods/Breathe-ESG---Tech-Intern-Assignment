import { useEffect, useState } from "react";
import axios from "axios";

function AuditPage() {
  const [rows, setRows] = useState([]);

  useEffect(() => {
    fetchApprovedRows();
  }, []);

  const fetchApprovedRows = async () => {
    const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");
    const res = await axios.get(`${API_URL}/api/rows/`, {
      headers: {
        "X-Tenant-ID": "breathe-esg-default",
      },
    });

    const approved = res.data.filter((row) => row.status === "approved");

    setRows(approved);
  };

  return (
    <div>
      <h2>Approved Audit Records</h2>

      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th style={{ width: "100px" }}>ID</th>
              <th style={{ width: "200px" }}>Source</th>
              <th>Status</th>
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
                  <span className="badge badge-approved">{row.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default AuditPage;
