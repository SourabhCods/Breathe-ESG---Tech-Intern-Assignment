import { useState } from "react";
import axios from "axios";

function UploadPage() {
  const [sapFile, setSapFile] = useState(null);
  const [utilityFile, setUtilityFile] = useState(null);
  const [travelFile, setTravelFile] = useState(null);

  const uploadFile = async (file, sourceType) => {
    if (!file) {
      alert(`Select ${sourceType} file first`);
      return;
    }

    const formData = new FormData();

    formData.append("file", file);
    formData.append("source_type", sourceType);

    const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");
    await axios.post(`${API_URL}/api/upload/`, formData, {
      headers: {
        "X-Tenant-ID": "breathe-esg-default",
      },
    });

    alert(`${sourceType} uploaded successfully`);
  };

  return (
    <div>
      <h2>Upload Data Sources</h2>

      <div className="upload-grid">
        <div className="upload-card">
          <div>
            <h3>SAP Fuel & Procurement</h3>
            <p>Ingests AL11 semicolon exports, translates German headers, pads IDs, and validates quantity (Menge) profiles.</p>
          </div>
          <div>
            <div className="file-input-wrapper">
              <input type="file" onChange={(e) => setSapFile(e.target.files[0])} />
            </div>
            <button className="btn-primary" onClick={() => uploadFile(sapFile, "sap")}>
              Upload SAP CSV
            </button>
          </div>
        </div>

        <div className="upload-card">
          <div>
            <h3>Utility Electricity</h3>
            <p>Ingests billing portal CSVs, handles peak/off-peak sum-ups, and pro-rates usage fractionally across month boundaries.</p>
          </div>
          <div>
            <div className="file-input-wrapper">
              <input type="file" onChange={(e) => setUtilityFile(e.target.files[0])} />
            </div>
            <button className="btn-primary" onClick={() => uploadFile(utilityFile, "utility")}>
              Upload Utility CSV
            </button>
          </div>
        </div>

        <div className="upload-card">
          <div>
            <h3>Corporate Travel</h3>
            <p>Ingests booking CSVs or webhooks, runs geodesic lookups on IATA codes, and handles cabin multiplier scales.</p>
          </div>
          <div>
            <div className="file-input-wrapper">
              <input type="file" onChange={(e) => setTravelFile(e.target.files[0])} />
            </div>
            <button className="btn-primary" onClick={() => uploadFile(travelFile, "travel")}>
              Upload Travel CSV
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default UploadPage;
