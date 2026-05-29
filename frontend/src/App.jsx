import { useState } from "react";

import UploadPage from "./pages/UploadPage";
import DashboardPage from "./pages/DashboardPage";
import AuditPage from "./pages/AuditPage";
import RowDetailsPage from "./pages/RowDetailsPage";

function App() {
  const [page, setPage] = useState("upload");
  const [selectedRow, setSelectedRow] = useState(null);

  const renderPage = () => {
    switch (page) {
      case "upload":
        return <UploadPage />;

      case "dashboard":
        return (
          <DashboardPage setSelectedRow={setSelectedRow} setPage={setPage} />
        );

      case "details":
        return <RowDetailsPage row={selectedRow} />;

      case "audit":
        return <AuditPage />;

      default:
        return <UploadPage />;
    }
  };

  return (
    <div id="app-container">
      <h1>Breathe ESG Analyst Workflow</h1>

      <div className="nav-menu">
        <button 
          className={page === "upload" ? "nav-btn active" : "nav-btn"} 
          onClick={() => setPage("upload")}
        >
          Upload Sources
        </button>

        <button 
          className={page === "dashboard" || page === "details" ? "nav-btn active" : "nav-btn"} 
          onClick={() => setPage("dashboard")}
        >
          Review Dashboard
        </button>

        <button 
          className={page === "audit" ? "nav-btn active" : "nav-btn"} 
          onClick={() => setPage("audit")}
        >
          Audit Records
        </button>
      </div>

      {renderPage()}
    </div>
  );
}

export default App;
